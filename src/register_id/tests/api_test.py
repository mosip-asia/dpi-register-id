import base64
import pytest
from fastapi.testclient import TestClient
from project.web import app

client = TestClient(app)


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
    mock_jpeg_b64 = base64.b64encode(b"mock-face-bytes").decode("utf-8")
    mock_embedding = [0.05] * 128
    uin = "9876-5432-1098"

    enroll_payload = {
        "uin": uin,
        "fullName": "Test Citizen",
        "email": "test@citizen.asia",
        "faceImage": f"data:image/jpeg;base64,{mock_jpeg_b64}",
        "faceEmbedding": mock_embedding,
        "password": "SecretPassword123!",
    }

    # 1. Enroll
    enroll_res = client.post("/api/enroll", json=enroll_payload)
    assert enroll_res.status_code == 200
    enroll_data = enroll_res.json()
    assert enroll_data["status"] == "SUCCESS"
    assert enroll_data["uin"] == uin
    assert enroll_data["cbeffGenerated"] is True

    # 2. List Citizens
    list_res = client.get("/api/citizens")
    assert list_res.status_code == 200
    uins = [c["uin"] for c in list_res.json()]
    assert uin in uins

    # 3. Authenticate with matching probe
    auth_payload = {
        "uin": uin,
        "liveEmbedding": [0.06] * 128,  # very close to 0.05
        "livenessScore": 92.0,
        "livenessPassed": True,
    }
    auth_res = client.post("/api/authenticate", json=auth_payload)
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["verified"] is True
    assert auth_data["isFaceMatch"] is True
    assert auth_data["livenessPassed"] is True
    assert auth_data["jwtToken"] is not None

    # 4. Authenticate with impostor probe
    impostor_payload = {
        "uin": uin,
        "liveEmbedding": [0.85] * 128,  # far from 0.05
        "livenessScore": 92.0,
        "livenessPassed": True,
    }
    impostor_res = client.post("/api/authenticate", json=impostor_payload)
    assert impostor_res.status_code == 200
    impostor_data = impostor_res.json()
    assert impostor_data["verified"] is False
    assert impostor_data["isFaceMatch"] is False
