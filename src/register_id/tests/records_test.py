import uuid

from fastapi.testclient import TestClient
from mock.idrepo.app import idrepo_app
from register_id.access import CUSTODIAN_ROLES, DEMOGRAPHIC_ROLES, require_role
from register_id.idrepo_client import IDRepoClient

mock_client = TestClient(idrepo_app)

FACE = "data:image/jpeg;base64,bW9jay1mYWNl"
CBEFF = "<BIR>mock-face-document</BIR>"


def test_require_role_reader_and_custodian(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "stage-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")

    missing = require_role(None, DEMOGRAPHIC_ROLES)
    assert missing.ok is False
    assert missing.status_code == 401
    assert missing.reason == "missing operator token"

    blank = require_role("   ", DEMOGRAPHIC_ROLES)
    assert blank.status_code == 401
    assert blank.reason == "missing operator token"

    wrong = require_role("Bearer other-token", DEMOGRAPHIC_ROLES)
    assert wrong.ok is False
    assert wrong.status_code == 401
    assert wrong.reason == "invalid operator token"

    scheme = require_role("Basic stage-token", DEMOGRAPHIC_ROLES)
    assert scheme.status_code == 401
    assert scheme.reason == "invalid operator token"

    reader = require_role("Bearer stage-token", DEMOGRAPHIC_ROLES)
    assert reader.ok is True
    assert reader.role == "reader"
    assert reader.status_code is None

    denied = require_role("Bearer stage-token", CUSTODIAN_ROLES)
    assert denied.ok is False
    assert denied.status_code == 403
    assert denied.reason == "operator role 'reader' is not allowed"

    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "Custodian")
    custodian_read = require_role("bearer stage-token", DEMOGRAPHIC_ROLES)
    assert custodian_read.ok is True
    assert custodian_read.role == "custodian"

    custodian_write = require_role("Bearer stage-token", CUSTODIAN_ROLES)
    assert custodian_write.ok is True
    assert custodian_write.role == "custodian"


def test_ordinary_read_omits_biometrics_and_defaults_to_draft():
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    uin = client.generate_uin()

    saved = client.add_identity(
        uin=uin,
        full_name="Draft Citizen",
        email="draft@dopa.gov.th",
        face_image=FACE,
        cbeff_xml=CBEFF,
        templates=[{"sector": "front", "embedding": [0.2, 0.3, 0.4]}],
    )
    assert saved is True

    plain = client.get_identity(uin)
    assert plain is not None
    assert plain["uin"] == uin
    assert plain["full_name"] == "Draft Citizen"
    assert plain["email"] == "draft@dopa.gov.th"
    assert plain["status"] == "draft"
    assert plain["login_disabled"] is False
    assert "face_image" not in plain
    assert "cbeff_xml" not in plain

    listed = client.list_identities(limit=50)
    row = next(item for item in listed if item["uin"] == uin)
    assert row["full_name"] == "Draft Citizen"
    assert row["email"] == "draft@dopa.gov.th"
    assert row["status"] == "draft"
    assert "face_image" not in row
    assert "cbeff_xml" not in row
    assert "faceImage" not in row

    wire = mock_client.get(
        f"/idrepository/v1/identity/uin/{uin}",
        params={"includeBiometrics": "false"},
    )
    assert wire.status_code == 200
    body = wire.json()["response"]["identity"]
    assert "faceImage" not in body
    assert wire.json()["response"]["documents"] == []
    assert body["recordStatus"] == "draft"


def test_custodian_read_includes_biometrics_when_requested():
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    uin = "7788-1200-0001"
    assert client.add_identity(
        uin=uin,
        full_name="Biometric Citizen",
        email="bio@dopa.gov.th",
        face_image=FACE,
        cbeff_xml=CBEFF,
        status="biometric",
    ) is True

    full = client.get_identity(uin, include_biometrics=True)
    assert full is not None
    assert full["status"] == "biometric"
    assert full["face_image"] == FACE
    assert full["cbeff_xml"] == CBEFF

    raw = mock_client.get(
        f"/idrepository/v1/identity/uin/{uin}",
        params={"includeBiometrics": "true"},
    )
    assert raw.json()["response"]["identity"]["faceImage"] == FACE


def test_update_demographics_login_flag_and_delete_face():
    client = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    # A fresh UIN. Reusing one leaves its old created_at, and the recent list
    # of 50 then omits it once the shared registry already has newer rows.
    uin = f"7788-1200-{uuid.uuid4().hex[:8]}"
    templates = [
        {"sector": "front", "embedding": [0.5, 0.6]},
        {"sector": "left", "embedding": [0.1, 0.2]},
    ]
    assert client.add_identity(
        uin=uin,
        full_name="Before Correction",
        email="before@dopa.gov.th",
        face_image=FACE,
        cbeff_xml=CBEFF,
        templates=templates,
        status="biometric",
    ) is True

    assert client.update_demographics(uin, "After Correction", "after@dopa.gov.th") is True
    corrected = client.get_identity(uin, include_biometrics=True)
    assert corrected["full_name"] == "After Correction"
    assert corrected["email"] == "after@dopa.gov.th"
    assert corrected["face_image"] == FACE
    assert corrected["cbeff_xml"] == CBEFF
    assert corrected["status"] == "biometric"
    assert client.get_face_templates(uin)

    assert client.set_login_disabled(uin, True) is True
    assert client.get_identity(uin)["login_disabled"] is True
    listed = next(item for item in client.list_identities(limit=50) if item["uin"] == uin)
    assert listed["login_disabled"] is True
    assert "face_image" not in listed

    assert client.set_login_disabled(uin, False) is True
    assert client.get_identity(uin)["login_disabled"] is False

    assert client.delete_face(uin) is True
    cleared = client.get_identity(uin, include_biometrics=True)
    assert cleared["full_name"] == "After Correction"
    assert cleared["email"] == "after@dopa.gov.th"
    assert cleared["status"] == "biometric"
    assert cleared["face_image"] is None
    assert cleared["cbeff_xml"] is None
    assert client.get_face_templates(uin) == []
    assert mock_client.get(
        f"/ida/v1/face-template/uin/{uin}",
        params={"includeBiometrics": "true"},
    ).status_code == 404

    missing = "7788-1200-0099"
    assert client.update_demographics(missing, "Nobody", "nobody@dopa.gov.th") is False
    assert client.set_login_disabled(missing, True) is False
    assert client.delete_face(missing) is False
