"""SMTP enrollment confirmation: config gates, delivery, and enroll wiring."""

import base64

import pytest
from fastapi.testclient import TestClient

from project.web import app
from register_id.email import (
    EmailResult,
    decode_id_card_png,
    registration_qr_png,
    send_enrollment_email,
)

client = TestClient(app)


def _data_url(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _consent() -> dict:
    return {
        "accepted": True,
        "purpose": "Store a face template for later identity checks",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }


# 1x1 PNG. Magic bytes are \x89PNG\r\n\x1a\n.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_data_url(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _png_parts(message):
    return [part for part in message.walk() if part.get_content_type() == "image/png"]


def _png_by_cid(message, cid: str):
    matches = [part for part in _png_parts(message) if part["Content-ID"].strip("<>") == cid]
    assert len(matches) == 1
    return matches[0]


def _part_text(message, content_type: str) -> str:
    matches = [
        part.get_content()
        for part in message.walk()
        if part.get_content_type() == content_type
    ]
    assert len(matches) == 1
    return matches[0]


def _configure_gmail(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float = 0):
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            calls.setdefault("ehlo", 0)
            calls["ehlo"] = int(calls["ehlo"]) + 1

        def starttls(self, context=None):
            calls["starttls"] = True
            calls["tls_context"] = context is not None

        def login(self, user: str, password: str):
            calls["login"] = (user, password)

        def send_message(self, message):
            calls["message"] = message

    monkeypatch.setattr("register_id.email.smtplib.SMTP", FakeSMTP)
    return calls


def _capture_enrollment_email(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def record(**kwargs):
        captured.update(kwargs)
        return EmailResult(sent=True, skipped=False, detail="email sent")

    monkeypatch.setattr("register_id.api.send_enrollment_email", record)
    return captured


def test_send_skips_when_provider_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    result = send_enrollment_email(to="citizen@example.com", full_name="Ada", uin="1111-2222")
    assert result.skipped is True
    assert result.sent is False
    assert "unset" in result.detail


def test_send_skips_unknown_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "postmark")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    result = send_enrollment_email(to="citizen@example.com", full_name="Ada", uin="1111-2222")
    assert result.skipped is True
    assert "unknown" in result.detail


def test_send_skips_incomplete_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    result = send_enrollment_email(to="citizen@example.com", full_name="Ada", uin="1111-2222")
    assert result.skipped is True
    assert "incomplete" in result.detail


def test_send_delivers_via_smtp(monkeypatch: pytest.MonkeyPatch):
    calls = _configure_gmail(monkeypatch)

    result = send_enrollment_email(
        to="citizen@example.com",
        full_name="Ada Lovelace",
        uin="1234-5678-9012",
    )
    assert result.sent is True
    assert result.skipped is False
    assert calls["host"] == "smtp.gmail.com"
    assert calls["port"] == 587
    assert calls["starttls"] is True
    assert calls["login"] == ("sender@example.com", "app-password")
    message = calls["message"]
    assert message["To"] == "citizen@example.com"
    assert message["From"] == "sender@example.com"
    assert message["Subject"] == "Your register-id registration number"
    assert message.get_content_type() == "multipart/alternative"
    plain = _part_text(message, "text/plain")
    assert "1234-5678-9012" in plain
    assert "Ada" in plain
    assert "\n1234-5678-9012\n" in plain
    assert "use the ID" in plain
    assert "The QR code in this message is that registration number." in plain
    assert plain.strip().endswith("register-id")
    assert "ID card" not in plain
    html = _part_text(message, "text/html")
    assert "1234-5678-9012" in html
    assert "#24321e" in html
    assert "#3f6433" in html
    assert "<table" in html
    assert 'src="cid:uin-qr"' in html
    qr = _png_by_cid(message, "uin-qr")
    assert qr.get_content() == registration_qr_png("1234-5678-9012")
    assert _png_by_cid(message, "uin-qr")["Content-Disposition"].startswith("inline")


def test_send_embeds_id_card_when_opted_in(monkeypatch: pytest.MonkeyPatch):
    calls = _configure_gmail(monkeypatch)
    uin = "1234-5678-9012"
    result = send_enrollment_email(
        to="citizen@example.com",
        full_name="Ada Lovelace",
        uin=uin,
        email_id_card=True,
        id_card_png=_TINY_PNG,
    )
    assert result.sent is True
    message = calls["message"]
    assert message.get_content_type() == "multipart/alternative"
    assert message["Subject"] == "Your register-id registration number"
    plain = _part_text(message, "text/plain")
    assert "Ada" in plain
    assert f"\n{uin}\n" in plain
    assert "Your ID card is in this message." in plain

    related = [
        part
        for part in message.iter_parts()
        if part.get_content_type() == "multipart/related"
    ]
    assert len(related) == 1
    html = _part_text(message, "text/html")
    assert uin in html
    assert "cid:id-card" in html
    assert 'alt="ID card"' in html
    assert "max-width:560px" in html
    images = [
        part for part in related[0].walk() if part.get_content_type() == "image/png"
    ]
    assert len(images) == 2
    assert _png_by_cid(message, "id-card").get_content() == _TINY_PNG
    assert _png_by_cid(message, "uin-qr").get_content() == registration_qr_png(uin)
    other_images = [
        part.get_content_type()
        for part in message.walk()
        if part.get_content_type().startswith("image/")
        and part.get_content_type() != "image/png"
    ]
    assert other_images == []


def test_decode_id_card_png_rejects_bad_payloads():
    assert _TINY_PNG.startswith(_PNG_MAGIC)
    assert decode_id_card_png(None) is None
    assert decode_id_card_png("") is None
    assert decode_id_card_png(_png_data_url(_TINY_PNG)) == _TINY_PNG
    assert decode_id_card_png(_data_url(b"not-a-png")) is None
    assert decode_id_card_png("data:image/png;base64,!!!!") is None
    assert decode_id_card_png(_png_data_url(b"not-a-png")) is None

    exact = _PNG_MAGIC + b"\x00" * (2_000_000 - len(_PNG_MAGIC))
    assert decode_id_card_png(_png_data_url(exact)) == exact
    oversized = _PNG_MAGIC + b"\x00" * (2_000_001 - len(_PNG_MAGIC))
    assert decode_id_card_png(_png_data_url(oversized)) is None


def test_enroll_bad_id_card_image_still_succeeds(monkeypatch: pytest.MonkeyPatch):
    captured = _capture_enrollment_email(monkeypatch)
    payload = {
        "uin": "5555-6666-7701",
        "fullName": "Bad Card",
        "email": "bad-card@citizen.asia",
        "faceImage": _data_url(b"mock-face-bytes-bad-card"),
        "consent": _consent(),
        "emailIdCard": True,
        "idCardImage": _png_data_url(b"not-a-png"),
    }
    response = client.post("/api/enroll", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert captured["email_id_card"] is True
    assert captured["id_card_png"] is None

    oversized = _PNG_MAGIC + b"\x00" * (2_000_001 - len(_PNG_MAGIC))
    captured.clear()
    oversized_payload = {
        "uin": "5555-6666-7702",
        "fullName": "Huge Card",
        "email": "huge-card@citizen.asia",
        "faceImage": _data_url(b"mock-face-bytes-huge-card"),
        "consent": _consent(),
        "emailIdCard": True,
        "idCardImage": _png_data_url(oversized),
    }
    oversized_response = client.post("/api/enroll", json=oversized_payload)
    assert oversized_response.status_code == 200
    assert captured["email_id_card"] is True
    assert captured["id_card_png"] is None


def test_enroll_email_id_card_false_drops_image(monkeypatch: pytest.MonkeyPatch):
    captured = _capture_enrollment_email(monkeypatch)
    payload = {
        "uin": "5555-6666-7703",
        "fullName": "No Card Mail",
        "email": "no-card@citizen.asia",
        "faceImage": _data_url(b"mock-face-bytes-no-card"),
        "consent": _consent(),
        "emailIdCard": False,
        "idCardImage": _png_data_url(_TINY_PNG),
    }
    response = client.post("/api/enroll", json=payload)
    assert response.status_code == 200
    assert captured["to"] == "no-card@citizen.asia"
    assert captured["full_name"] == "No Card Mail"
    assert captured["uin"] == "5555-6666-7703"
    assert captured["email_id_card"] is False
    assert captured["id_card_png"] is None


def test_send_reports_delivery_failure(monkeypatch: pytest.MonkeyPatch):
    import smtplib

    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")

    class BoomSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise smtplib.SMTPAuthenticationError(535, b"bad")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("register_id.email.smtplib.SMTP", BoomSMTP)
    result = send_enrollment_email(to="citizen@example.com", full_name="Ada", uin="1111-2222")
    assert result.sent is False
    assert result.skipped is False
    assert "failed" in result.detail


def test_enroll_includes_email_result(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "register_id.api.send_enrollment_email",
        lambda **kwargs: EmailResult(sent=True, skipped=False, detail="email sent"),
    )
    payload = {
        "uin": "5555-6666-7777",
        "fullName": "Mail Citizen",
        "email": "mail@citizen.asia",
        "faceImage": _data_url(b"mock-face-bytes-email"),
        "consent": _consent(),
    }
    response = client.post("/api/enroll", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["emailSent"] is True
    assert body["emailStatus"] == "email sent"


def test_enroll_succeeds_when_email_skipped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "register_id.api.send_enrollment_email",
        lambda **kwargs: EmailResult(sent=False, skipped=True, detail="email provider unset"),
    )
    payload = {
        "uin": "5555-6666-8888",
        "fullName": "Skip Citizen",
        "email": "skip@citizen.asia",
        "faceImage": _data_url(b"mock-face-bytes-email-skip"),
        "consent": _consent(),
    }
    response = client.post("/api/enroll", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["emailSent"] is False
    assert "unset" in body["emailStatus"]
