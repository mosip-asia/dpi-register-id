"""
SMTP enrollment confirmation mailer.

Sends the citizen their UIN after a successful enroll. The destination is
SMTP_HOST and SMTP_PORT, or the EMAIL_PROVIDER=gmail shortcut. An empty
destination skips sending so local runs without SMTP stay usable. Username
and password are optional. STARTTLS is on unless SMTP_STARTTLS is 0, false,
no, or off. Enrollment does not roll back when mail fails.

When the citizen opts in, the HTML part can carry the browser-drawn ID card.
The face photo is never attached. A bad card image is left out; mail still sends.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Final

import segno

logger = logging.getLogger(__name__)

# host, port — submission port 587. STARTTLS follows SMTP_STARTTLS (default on).
_PROVIDERS: Final[dict[str, tuple[str, int]]] = {
    "gmail": ("smtp.gmail.com", 587),
}


@dataclass(frozen=True)
class EmailResult:
    """Outcome of an enrollment confirmation attempt."""

    sent: bool
    skipped: bool
    detail: str


# data:image/png;base64,<payload>, and the PNG signature those bytes must start with.
_PNG_DATA_URL_PREFIX: Final[str] = "data:image/png;base64,"
_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
_MAX_ID_CARD_BYTES: Final[int] = 2_000_000
_CARD_CONTENT_ID: Final[str] = "id-card"
_QR_CONTENT_ID: Final[str] = "uin-qr"


def decode_id_card_png(value: str | None) -> bytes | None:
    """
    Return PNG bytes for a ``data:image/png;base64,`` URL of at most 2_000_000 bytes.

    Missing, non-PNG, invalid base64, or oversized values return None. Callers
    enroll and send the confirmation without the picture.
    """
    if not isinstance(value, str) or not value.startswith(_PNG_DATA_URL_PREFIX):
        return None
    payload = value[len(_PNG_DATA_URL_PREFIX) :]
    if not payload:
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except ValueError:
        return None
    if len(raw) > _MAX_ID_CARD_BYTES or not raw.startswith(_PNG_MAGIC):
        return None
    return raw


def registration_qr_png(uin: str) -> bytes:
    """PNG QR code whose payload is the registration number and nothing else."""
    buffer = io.BytesIO()
    segno.make(uin, error="h", micro=False).save(buffer, kind="png", scale=8, border=4)
    return buffer.getvalue()


def send_enrollment_email(
    *,
    to: str,
    full_name: str,
    uin: str,
    email_id_card: bool = False,
    id_card_png: bytes | None = None,
) -> EmailResult:
    """
    Email the registration number to ``to``.

    Every delivered message includes a QR code of that number. ``email_id_card``
    and ``id_card_png`` also attach the ID card when both are set.
    Returns skipped when SMTP is not configured. Returns sent=False with a
    short detail when delivery fails. Never raises for SMTP errors.
    """
    provider = (os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    sender = (os.getenv("EMAIL_FROM") or os.getenv("SMTP_USER") or "").strip()
    password = os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_PASSWORD") or ""
    recipient = (to or "").strip()
    host, port, known = _smtp_target(provider)

    if provider and not known:
        return EmailResult(sent=False, skipped=True, detail=f"unknown email provider {provider}")
    if not known and not host:
        return EmailResult(sent=False, skipped=True, detail="email provider unset")
    if not sender:
        return EmailResult(sent=False, skipped=True, detail="email credentials incomplete")
    if not recipient or "@" not in recipient:
        return EmailResult(sent=False, skipped=True, detail="recipient email missing")
    message = _build_message(
        sender=sender,
        to=recipient,
        full_name=full_name,
        uin=uin,
        email_id_card=email_id_card,
        id_card_png=id_card_png,
    )

    try:
        _deliver(host=host, port=port, sender=sender, password=password, message=message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Enrollment email failed for UIN %s: %s", uin, type(exc).__name__)
        return EmailResult(sent=False, skipped=False, detail="email delivery failed")

    logger.info("Enrollment email sent for UIN %s via %s", uin, provider)
    return EmailResult(sent=True, skipped=False, detail="email sent")


def _build_message(
    *,
    sender: str,
    to: str,
    full_name: str,
    uin: str,
    email_id_card: bool = False,
    id_card_png: bytes | None = None,
) -> EmailMessage:
    include_card = bool(email_id_card and id_card_png)
    given = (full_name or "").strip().split()[:1]
    greeting = f"Hello {given[0]}," if given else "Hello,"
    lines = [
        greeting,
        "",
        "Your registration number is",
        uin,
        "",
        "You will need this number to use the ID.",
        "",
        "The QR code in this message is that registration number.",
        "",
    ]
    if include_card:
        lines.extend(["Your ID card is in this message.", ""])
    lines.append("register-id")
    plain = "\n".join(lines) + "\n"

    message = EmailMessage()
    message["Subject"] = "Your register-id registration number"
    message["From"] = sender
    message["To"] = to
    message.set_content(plain)
    message.add_alternative(
        _html_body(greeting=greeting, uin=uin, include_card=include_card),
        subtype="html",
    )
    # The HTML alternative becomes multipart/related; the plain part stays beside it.
    related = message.get_payload()[1]
    _attach_png(related, registration_qr_png(uin), _QR_CONTENT_ID)
    if include_card and id_card_png is not None:
        _attach_png(related, id_card_png, _CARD_CONTENT_ID)
    return message


def _attach_png(part: EmailMessage, payload: bytes, cid: str) -> None:
    part.add_related(payload, maintype="image", subtype="png", cid=f"<{cid}>")


def _html_body(*, greeting: str, uin: str, include_card: bool) -> str:
    safe_greeting = html.escape(greeting, quote=True)
    safe_uin = html.escape(uin, quote=True)
    text = (
        "padding:{pad};font-family:Georgia,'Times New Roman',serif;"
        "font-size:16px;line-height:1.5;color:#24321e;"
    )
    rows = [
        _row(
            '<h1 style="margin:0;font-size:22px;font-weight:normal;line-height:1.3;'
            'color:#3f6433;">Your registration number</h1>',
            "padding:28px 24px 0;font-family:Georgia,'Times New Roman',serif;",
        ),
        _row(safe_greeting, text.format(pad="16px 24px 0")),
        _row("Your registration number is", text.format(pad="12px 24px 0")),
        _row(
            safe_uin,
            "padding:8px 24px 0;font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:18px;line-height:1.4;color:#24321e;",
        ),
        _row("You will need this number to use the ID.", text.format(pad="12px 24px 0")),
        _row(
            "The QR code in this message is that registration number.",
            text.format(pad="12px 24px 0"),
        ),
        '<tr><td style="padding:16px 24px 0;">'
        f'<img src="cid:{_QR_CONTENT_ID}" alt="QR code for registration number {safe_uin}" '
        'style="display:block;width:240px;height:auto;border:0;">'
        "</td></tr>",
    ]
    if include_card:
        rows.append(_row("Your ID card is in this message.", text.format(pad="12px 24px 0")))
        rows.append(
            '<tr><td style="padding:16px 24px 0;">'
            '<img src="cid:id-card" alt="ID card" '
            'style="display:block;max-width:560px;height:auto;border:0;">'
            "</td></tr>"
        )
    rows.append(_row("register-id", text.format(pad="20px 24px 28px")))
    body = "".join(rows)
    return (
        "<!DOCTYPE html><html><body "
        'style="margin:0;padding:0;background-color:#ffffff;color:#24321e;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#ffffff;">'
        '<tr><td align="left">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:560px;background-color:#ffffff;">'
        f"{body}</table></td></tr></table></body></html>"
    )


def _row(inner: str, style: str) -> str:
    return f'<tr><td style="{style}">{inner}</td></tr>'


def _smtp_target(provider: str) -> tuple[str, int, bool]:
    """Generic SMTP_HOST wins. EMAIL_PROVIDER=gmail remains the named shortcut."""
    host = (os.getenv("SMTP_HOST") or "").strip()
    if host:
        raw_port = (os.getenv("SMTP_PORT") or "587").strip()
        try:
            port = int(raw_port)
        except ValueError:
            port = 587
        return host, port, True
    if not provider:
        return "", 587, False
    if provider not in _PROVIDERS:
        return "", 587, False
    known_host, known_port = _PROVIDERS[provider]
    return known_host, known_port, True


def _starttls_enabled() -> bool:
    """STARTTLS unless SMTP_STARTTLS is 0, false, no, or off. Unset stays on."""
    raw = (os.getenv("SMTP_STARTTLS") or "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no", "off"}


def _deliver(
    *,
    host: str,
    port: int,
    sender: str,
    password: str,
    message: EmailMessage,
) -> None:
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if _starttls_enabled():
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if password:
            smtp.login(sender, password)
        smtp.send_message(message)
