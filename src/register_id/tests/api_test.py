import base64

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
        "password": "SecretPassword123!",
    }

    enroll_res = client.post("/api/enroll", json=enroll_payload)
    assert enroll_res.status_code == 200
    enroll_data = enroll_res.json()
    assert enroll_data["status"] == "SUCCESS"
    assert enroll_data["uin"] == uin
    assert enroll_data["cbeffGenerated"] is True
    assert enroll_data["keycloakProvisioned"] is False

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
