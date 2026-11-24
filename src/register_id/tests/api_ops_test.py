"""Operator reads, custodian corrections, and credential failure."""

import base64

from fastapi.testclient import TestClient
from project.web import app
from register_id.idrepo_client import IDRepoClient
from register_id.tests.conftest import enroll_headers
from register_id.keycloak import ProvisionResult

client = TestClient(app)


def _image() -> str:
    encoded = base64.b64encode(b"ops-face-bytes").decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _enroll() -> str:
    res = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "fullName": "Ops Citizen",
            "email": "ops@citizen.asia",
            "faceImage": _image(),
            "consent": {
                "accepted": True,
                "purpose": "Store a face template for later identity checks",
                "acceptedAt": 1_763_000_000.0,
                "language": "eng",
            },
        },
    )
    assert res.status_code == 200
    assert res.json()["recordStatus"] == "draft"
    assert res.json()["cbeffGenerated"] is False
    return res.json()["uin"]


def test_anonymous_registry_read_is_rejected(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "reader-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    uin = _enroll()
    denied = client.get(f"/api/citizens/{uin}")
    assert denied.status_code == 401
    allowed = client.get(
        f"/api/citizens/{uin}",
        headers={"Authorization": "Bearer reader-token"},
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["fullName"] == "Ops Citizen"
    assert "faceImage" not in body
    assert "cbeff" not in body


def test_custodian_updates_disable_and_delete(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "custodian-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "custodian")
    monkeypatch.setattr(
        "register_id.keycloak.KeycloakBridgeClient.set_login_enabled",
        lambda self, uin, email, enabled: ProvisionResult(True, False, "enabled updated"),
    )
    uin = _enroll()
    headers = {"Authorization": "Bearer custodian-token"}

    reader_block = client.post(
        f"/api/citizens/{uin}/demographics",
        headers=headers,
        json={
            "fullName": "Corrected Name",
            "email": "corrected@citizen.asia",
            "reason": "Correct a misspelled legal name",
        },
    )
    assert reader_block.status_code == 200

    disabled = client.post(
        f"/api/citizens/{uin}/login-disabled",
        headers=headers,
        json={"disabled": True, "reason": "Disable login after a desk review"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["loginDisabled"] is True

    deleted = client.post(
        f"/api/citizens/{uin}/delete-face",
        headers=headers,
        json={"reason": "Remove a face that is no longer valid"},
    )
    assert deleted.status_code == 200
    stored = IDRepoClient(enable_inprocess_fallback=True).get_identity(uin, include_biometrics=True)
    assert stored is not None
    assert not stored.get("face_image")


def test_reader_cannot_delete_a_face(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "reader-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    uin = _enroll()
    res = client.post(
        f"/api/citizens/{uin}/delete-face",
        headers={"Authorization": "Bearer reader-token"},
        json={"reason": "Remove a face that is no longer valid"},
    )
    assert res.status_code == 403


def test_empty_operator_token_denies_citizens_and_audit(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "custodian")
    uin = _enroll()
    headers = {"Authorization": "Bearer anything"}
    for path in ("/api/citizens", f"/api/citizens/{uin}", "/api/audit"):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 401
        assert "Ops Citizen" not in denied.text
        assert "ops@citizen.asia" not in denied.text
        assert "faceImage" not in denied.text


def test_reader_cannot_update_demographics(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "reader-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    uin = _enroll()
    res = client.post(
        f"/api/citizens/{uin}/demographics",
        headers={"Authorization": "Bearer reader-token"},
        json={
            "fullName": "Corrected Name",
            "email": "corrected@citizen.asia",
            "reason": "Correct a misspelled legal name",
        },
    )
    assert res.status_code == 403
    stored = IDRepoClient(enable_inprocess_fallback=True).get_identity(uin)
    assert stored is not None
    assert stored["full_name"] == "Ops Citizen"
    assert stored["email"] == "ops@citizen.asia"


def test_anonymous_audit_read_is_rejected(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "reader-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    missing = client.get("/api/audit")
    assert missing.status_code == 401
    wrong = client.get("/api/audit", headers={"Authorization": "Bearer wrong-token"})
    assert wrong.status_code == 401
    assert "uin" not in missing.json()
    assert "uin" not in wrong.json()
