import base64
import json

from fastapi.testclient import TestClient
from project.web import app
from register_id.embedder import embed_face_image
from register_id.idrepo_client import IDRepoClient

client = TestClient(app)


def _data_url(payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def test_api_check_liveness_endpoint():
    payload = {
        "blinkCount": 2,
        "minEar": 0.17,
        "maxEar": 0.31,
        "durationMs": 2800.0,
    }
    res = client.post("/api/checkLiveness", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PASSED"
    assert data["livenessScore"] >= 80.0


def test_api_enroll_and_authenticate_flow():
    face_image = _data_url(b"mock-face-bytes")
    vector = embed_face_image(face_image)
    uin = "9876-5432-1098"

    enroll_payload = {
        "uin": uin,
        "fullName": "Test Citizen",
        "email": "test@citizen.asia",
        "faceImage": face_image,
    }

    enroll_res = client.post("/api/enroll", json=enroll_payload)
    assert enroll_res.status_code == 200
    enroll_data = enroll_res.json()
    assert enroll_data["status"] == "SUCCESS"
    assert enroll_data["uin"] == uin
    assert enroll_data["cbeffGenerated"] is True
    assert "keycloakProvisioned" not in enroll_data

    idrepo = IDRepoClient(enable_inprocess_fallback=True)
    stored = idrepo.get_identity(uin)
    assert stored is not None
    assert "face_embedding" not in stored

    templates = idrepo.get_face_templates(uin)
    front = next(item for item in templates if item["sector"] == "front")
    assert front["embedding"] == vector

    list_res = client.get("/api/citizens")
    assert list_res.status_code == 200
    uins = [c["uin"] for c in list_res.json()]
    assert uin in uins

    auth_res = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveEmbedding": vector,
            "livenessScore": 92.0,
            "livenessPassed": True,
        },
    )
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["verified"] is True
    assert auth_data["isFaceMatch"] is True
    assert auth_data["livenessPassed"] is True
    assert auth_data["jwtToken"] is not None

    impostor_res = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveEmbedding": [0.85] * 128,
            "livenessScore": 92.0,
            "livenessPassed": True,
        },
    )
    assert impostor_res.status_code == 200
    impostor_data = impostor_res.json()
    assert impostor_data["verified"] is False
    assert impostor_data["isFaceMatch"] is False


def test_enroll_rejects_password_and_client_embedding():
    face_image = _data_url(b"reject-extra-fields")
    base = {
        "uin": "9876-5432-1498",
        "fullName": "No Extras",
        "email": "extras@citizen.asia",
        "faceImage": face_image,
    }
    with_password = client.post("/api/enroll", json={**base, "password": "SecretPassword123!"})
    assert with_password.status_code == 422
    with_embedding = client.post("/api/enroll", json={**base, "faceEmbedding": [0.1] * 128})
    assert with_embedding.status_code == 422


def test_api_credentials_issue_after_enroll():
    face_image = _data_url(b"credentials-after-enroll")
    uin = "9876-5432-1497"
    password = "CitizenChosenPass9"
    enroll = client.post(
        "/api/enroll",
        json={
            "uin": uin,
            "fullName": "Credential Citizen",
            "email": "cred@citizen.asia",
            "faceImage": face_image,
        },
    )
    assert enroll.status_code == 200

    short = client.post("/api/credentials", json={"uin": uin, "password": "short"})
    assert short.status_code == 422

    missing = client.post(
        "/api/credentials",
        json={"uin": "9876-5432-1499", "password": password},
    )
    assert missing.status_code == 404

    issued = client.post("/api/credentials", json={"uin": uin, "password": password})
    assert issued.status_code == 200
    body = issued.json()
    assert body["status"] == "SUCCESS"
    assert body["uin"] == uin
    assert body["keycloakProvisioned"] is False

    idrepo = IDRepoClient(enable_inprocess_fallback=True)
    stored = idrepo.get_identity(uin)
    assert password not in json.dumps(stored)
