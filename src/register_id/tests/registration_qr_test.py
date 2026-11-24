"""Registration QR on the enrollment email, and what that mail must not keep."""

import base64
import json
import secrets
import smtplib

import pytest
import segno
from fastapi.testclient import TestClient

from project.web import app
from register_id.email import registration_qr_png
from register_id.face_descriptor import FACE_DESCRIPTOR_ENGINE
from register_id.idrepo_client import IDRepoClient
from register_id.tests.conftest import enroll_headers

client = TestClient(app)

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_GOOD_YAWS = [-0.6, -0.3, 0.0, 0.3, 0.6]


def _uin() -> str:
    return f"7300-{secrets.randbelow(10**8):08d}"


def _data_url(payload: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode()


def _png_data_url(payload: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode()


def _consent() -> dict:
    return {
        "accepted": True,
        "purpose": "Store a face template for later identity checks",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }


def _descriptor() -> list[float]:
    return [0.01] * 128


def _configure_gmail(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float = 0):
            calls["host"] = host
            calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            return None

        def starttls(self, context=None):
            calls["starttls"] = context is not None

        def login(self, user: str, password: str):
            calls["login"] = (user, password)

        def send_message(self, message):
            calls["message"] = message

    monkeypatch.setattr("register_id.email.smtplib.SMTP", FakeSMTP)
    return calls


def _png_by_cid(message, cid: str):
    matches = [
        part
        for part in message.walk()
        if part.get_content_type() == "image/png" and part["Content-ID"].strip("<>") == cid
    ]
    assert len(matches) == 1
    return matches[0]


def _enroll(uin: str, **extra) -> object:
    body = {
        "fullName": "Ada Lovelace",
        "email": "ada@citizen.asia",
        "faceImage": _data_url(f"portrait-{uin}".encode()),
        "consent": _consent(),
    }
    body.update(extra)
    from register_id.idrepo_client import IDRepoClient

    original = IDRepoClient.generate_uin
    IDRepoClient.generate_uin = lambda self, _uin=uin: _uin
    try:
        return client.post("/api/enroll", json=body, headers=enroll_headers())
    finally:
        IDRepoClient.generate_uin = original


def test_registration_qr_is_the_uin_and_not_a_micro_symbol():
    dashed = "1234-5678-9012"
    digits = "8722413085"
    for uin in (dashed, digits):
        symbol = segno.make(uin, error="h", micro=False)
        wrapped = segno.make(f"UIN {uin}", error="h", micro=False)
        assert symbol.is_micro is False
        assert symbol.error == "H"
        assert symbol.matrix != wrapped.matrix
        assert registration_qr_png(uin).startswith(b"\x89PNG\r\n\x1a\n")
        assert registration_qr_png(uin) != registration_qr_png(f"UIN {uin}")


def test_enroll_email_carries_that_uins_qr_and_not_the_face(monkeypatch: pytest.MonkeyPatch):
    calls = _configure_gmail(monkeypatch)
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "qr-reader")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    uin = _uin()
    face = f"portrait-{uin}".encode()
    response = _enroll(
        uin,
        emailIdCard=True,
        idCardImage=_png_data_url(_TINY_PNG),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["emailSent"] is True
    assert body["uin"] == uin

    message = calls["message"]
    assert _png_by_cid(message, "uin-qr").get_content() == registration_qr_png(uin)
    assert _png_by_cid(message, "id-card").get_content() == _TINY_PNG
    mailed = message.as_string()
    assert base64.b64encode(face).decode() not in mailed
    assert "http://" not in mailed.split("cid:uin-qr", 1)[-1]

    idrepo = IDRepoClient(enable_inprocess_fallback=True)
    stored = json.dumps(idrepo.get_identity(uin, include_biometrics=True))
    card_b64 = base64.b64encode(_TINY_PNG).decode()
    assert card_b64 not in stored

    audit = client.get("/api/audit", headers={"Authorization": "Bearer qr-reader"}).json()
    events = [event for event in audit if event["uin"] == uin]
    assert events
    assert card_b64 not in json.dumps(events)
    assert "email sent" in events[-1]["detail"]


def test_smtp_failure_keeps_the_enrollment(monkeypatch: pytest.MonkeyPatch):
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
    uin = _uin()
    response = _enroll(uin)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["emailSent"] is False
    assert "failed" in body["emailStatus"]
    stored = IDRepoClient(enable_inprocess_fallback=True).get_identity(uin)
    assert stored is not None
    assert stored["uin"] == uin


def test_client_uin_is_rejected_before_mail_or_storage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    opened: list[str] = []

    class SpySMTP:
        def __init__(self, *args, **kwargs):
            opened.append("open")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("register_id.email.smtplib.SMTP", SpySMTP)
    response = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "uin": "12",
            "fullName": "Ada Lovelace",
            "email": "ada@citizen.asia",
            "faceImage": _data_url(b"portrait"),
            "consent": _consent(),
        },
    )
    assert response.status_code == 422
    assert "allocates the UIN" in response.text
    assert opened == []
    assert IDRepoClient(enable_inprocess_fallback=True).get_identity("12") is None


def test_descriptor_enroll_mails_the_same_qr(monkeypatch: pytest.MonkeyPatch):
    calls = _configure_gmail(monkeypatch)
    uin = _uin()
    challenge = client.post("/api/face/challenge", json={"purpose": "enroll"})
    assert challenge.status_code == 200
    response = _enroll(
        uin,
        faceDescriptors=[_descriptor(), _descriptor(), _descriptor()],
        liveness={
            "challengeId": challenge.json()["challengeId"],
            "engine": FACE_DESCRIPTOR_ENGINE,
            "blinkCount": 1,
            "sweepYaws": _GOOD_YAWS,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recordStatus"] == "biometric"
    assert body["cbeffGenerated"] is True
    uin = body["uin"]
    assert body["emailSent"] is True
    assert _png_by_cid(calls["message"], "uin-qr").get_content() == registration_qr_png(uin)
    assert "id-card" not in calls["message"].as_string()
