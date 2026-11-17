import pytest
from fastapi.testclient import TestClient
from project.web import app
from pydantic import ValidationError
from register_id.consent import ConsentRecord, validate_consent
from register_id.idrepo_client import IDRepoClient
from register_id.models import EnrollRequest

client = TestClient(app)


def _consent(**overrides) -> dict:
    payload = {
        "accepted": True,
        "purpose": "Enroll a face for identity proofing",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }
    payload.update(overrides)
    return payload


def _enroll_kwargs(**overrides) -> dict:
    payload = {
        "uin": "12345678",
        "fullName": "Consent Citizen",
        "email": "consent@citizen.asia",
        "faceImage": "data:image/jpeg;base64,abcd",
        "consent": _consent(),
    }
    payload.update(overrides)
    return payload


def test_validate_consent_records_purpose_time_and_language():
    eng = validate_consent(_consent())
    tha = validate_consent(_consent(language="tha", purpose="จัดเก็บใบหน้าเพื่อยืนยันตัวตน"))

    assert isinstance(eng, ConsentRecord)
    assert eng.accepted is True
    assert eng.purpose == "Enroll a face for identity proofing"
    assert eng.acceptedAt == 1_763_000_000.0
    assert eng.language == "eng"
    assert tha.language == "tha"
    assert set(eng.model_dump()) == {"accepted", "purpose", "acceptedAt", "language"}


def test_validate_consent_rejects_empty_purpose():
    with pytest.raises(ValueError, match="purpose is empty"):
        validate_consent(_consent(purpose=""))
    with pytest.raises(ValueError, match="purpose is empty"):
        validate_consent(_consent(purpose="   "))


def test_validate_consent_rejects_short_purpose():
    with pytest.raises(ValidationError):
        validate_consent(_consent(purpose="short"))


def test_validate_consent_rejects_refusal():
    with pytest.raises(ValueError, match="not accepted"):
        validate_consent(_consent(accepted=False))


def test_validate_consent_rejects_missing_time():
    payload = _consent()
    del payload["acceptedAt"]
    with pytest.raises(ValueError, match="acceptedAt is missing"):
        validate_consent(payload)
    with pytest.raises(ValueError, match="acceptedAt is missing"):
        validate_consent(_consent(acceptedAt=None))


def test_validate_consent_rejects_unknown_language():
    with pytest.raises(ValueError, match="eng or tha"):
        validate_consent(_consent(language="fra"))


def test_validate_consent_rejects_an_image():
    with pytest.raises(ValueError, match="extra fields"):
        validate_consent(_consent(faceImage="data:image/jpeg;base64,aaaa"))


def test_enroll_request_requires_consent():
    payload = _enroll_kwargs()
    del payload["consent"]
    with pytest.raises(ValidationError):
        EnrollRequest(**payload)


def test_enroll_request_rejects_refusal_and_extra_fields():
    with pytest.raises(ValidationError, match="not accepted"):
        EnrollRequest(**_enroll_kwargs(consent=_consent(accepted=False)))
    with pytest.raises(ValidationError):
        EnrollRequest(**_enroll_kwargs(password="SecretPassword123!"))


def test_enroll_request_keeps_face_view_yaw_rules():
    views = [
        {"sector": "far-left", "yaw": -0.20, "image": "far-left"},
        {"sector": "left", "yaw": -0.4, "image": "left"},
        {"sector": "front", "yaw": 0.0, "image": "front"},
        {"sector": "right", "yaw": 0.4, "image": "right"},
        {"sector": "far-right", "yaw": 0.8, "image": "far-right"},
    ]
    with pytest.raises(ValidationError, match="far-left yaw"):
        EnrollRequest(**_enroll_kwargs(faceViews=views))


def test_refused_or_missing_consent_stores_no_face():
    refused_uin = "9876-5432-7701"
    missing_uin = "9876-5432-7702"
    face = "data:image/jpeg;base64,cmVmdXNlZA=="

    refused = client.post(
        "/api/enroll",
        json={
            "uin": refused_uin,
            "fullName": "Refused Citizen",
            "email": "refused@citizen.asia",
            "faceImage": face,
            "consent": _consent(accepted=False),
        },
    )
    missing = client.post(
        "/api/enroll",
        json={
            "uin": missing_uin,
            "fullName": "Missing Consent",
            "email": "missing@citizen.asia",
            "faceImage": face,
        },
    )

    assert refused.status_code == 422
    assert missing.status_code == 422
    idrepo = IDRepoClient(enable_inprocess_fallback=True)
    assert idrepo.get_identity(refused_uin) is None
    assert idrepo.get_identity(missing_uin) is None
