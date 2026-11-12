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


def _sweep_challenge() -> str:
    res = client.post("/api/sweep/challenge")
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "HEAD_SWEEP"
    assert body["timeLimitSeconds"] == 90
    return body["challengeId"]


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
    face_image = _data_url(b"mock-face-bytes-enroll-front")
    other_image = _data_url(b"mock-face-bytes-impostor-probe")
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
    assert "face_views" not in stored

    templates = idrepo.get_face_templates(uin)
    front = next(item for item in templates if item["sector"] == "front")
    assert front["embedding"] == embed_face_image(face_image)

    list_res = client.get("/api/citizens")
    assert list_res.status_code == 200
    uins = [c["uin"] for c in list_res.json()]
    assert uin in uins

    auth_res = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveImage": face_image,
            "livenessScore": 92.0,
            "livenessPassed": True,
        },
    )
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["verified"] is False
    assert auth_data["isFaceMatch"] is False
    assert auth_data["livenessPassed"] is False
    assert auth_data["sweepAccepted"] is False
    assert auth_data["jwtToken"] is None
    assert "Head sweep required" in auth_data["message"]

    impostor_res = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveImage": other_image,
            "livenessScore": 92.0,
            "livenessPassed": True,
        },
    )
    assert impostor_res.status_code == 200
    impostor_data = impostor_res.json()
    assert impostor_data["verified"] is False
    assert impostor_data["isFaceMatch"] is False
    assert impostor_data["livenessPassed"] is False


def _head_sweep_views(prefix: str) -> list[dict]:
    sectors = [
        ("far-left", -0.8),
        ("left", -0.4),
        ("front", 0.0),
        ("right", 0.4),
        ("far-right", 0.8),
    ]
    return [
        {
            "sector": sector,
            "yaw": yaw,
            "image": _data_url(f"{prefix}-{sector}".encode()),
        }
        for sector, yaw in sectors
    ]


def test_api_enroll_and_authenticate_head_sweep():
    uin = "9876-5432-1100"
    views = _head_sweep_views("sweep-enroll")

    enroll_res = client.post(
        "/api/enroll",
        json={
            "uin": uin,
            "fullName": "Sweep Citizen",
            "email": "sweep@citizen.asia",
            "faceImage": _data_url(b"sweep-portrait-for-cbeff"),
            "faceViews": views,
        },
    )
    assert enroll_res.status_code == 200
    assert enroll_res.json()["status"] == "SUCCESS"
    assert "keycloakProvisioned" not in enroll_res.json()

    idrepo = IDRepoClient(enable_inprocess_fallback=True)
    stored = idrepo.get_identity(uin)
    assert stored is not None
    assert "face_embedding" not in stored
    assert "face_views" not in stored

    templates = idrepo.get_face_templates(uin)
    assert [item["sector"] for item in sorted(templates, key=lambda item: item["sector"])] == sorted(
        ["far-left", "left", "front", "right", "far-right"]
    )
    front_image = next(view["image"] for view in views if view["sector"] == "front")
    front_template = next(item for item in templates if item["sector"] == "front")
    assert front_template["embedding"] == embed_face_image(front_image)

    weak_turn = client.post(
        "/api/enroll",
        json={
            "uin": "9876-5432-1101",
            "fullName": "Weak Turn",
            "email": "weak@citizen.asia",
            "faceImage": _data_url(b"weak-turn-portrait"),
            "faceViews": [
                {"sector": "far-left", "yaw": -0.20, "image": _data_url(b"weak-far-left")},
                {"sector": "left", "yaw": -0.4, "image": _data_url(b"weak-left")},
                {"sector": "front", "yaw": 0.0, "image": _data_url(b"weak-front")},
                {"sector": "right", "yaw": 0.4, "image": _data_url(b"weak-right")},
                {"sector": "far-right", "yaw": 0.8, "image": _data_url(b"weak-far-right")},
            ],
        },
    )
    assert weak_turn.status_code == 422

    copied_views = _head_sweep_views("copied-pose")
    copied_image = _data_url(b"copied-frontal-bytes")
    for view in copied_views:
        if view["sector"] in ("front", "far-left"):
            view["image"] = copied_image
    copied = client.post(
        "/api/enroll",
        json={
            "uin": "9876-5432-1102",
            "fullName": "Copied Pose",
            "email": "copied@citizen.asia",
            "faceImage": _data_url(b"copied-portrait"),
            "faceViews": copied_views,
        },
    )
    assert copied.status_code == 422

    missing_sweep = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveImage": _data_url(b"missing-sweep-live-frame"),
            "livenessScore": 92.0,
            "livenessPassed": True,
        },
    )
    assert missing_sweep.status_code == 200
    missing_data = missing_sweep.json()
    assert missing_data["verified"] is False
    assert missing_data["isFaceMatch"] is False
    assert missing_data["livenessPassed"] is False
    assert missing_data["jwtToken"] is None
    assert "Head sweep required" in missing_data["message"]

    challenge_id = _sweep_challenge()
    matched = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveViews": views,
            "livenessScore": 0.0,
            "livenessPassed": False,
            "challengeId": challenge_id,
        },
    )
    assert matched.status_code == 200
    matched_data = matched.json()
    assert matched_data["verified"] is True
    assert matched_data["sweepAccepted"] is True
    assert matched_data["isFaceMatch"] is False
    assert matched_data["livenessPassed"] is False
    assert matched_data["jwtToken"] is None
    assert matched_data["yawSource"] == "client"
    assert "does not show a live head turn" in matched_data["message"]
    assert "no face model" in matched_data["message"]

    replay = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveViews": views,
            "livenessScore": 92.0,
            "livenessPassed": True,
            "challengeId": challenge_id,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["verified"] is False
    assert "already used" in replay.json()["message"]

    other_person = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveViews": _head_sweep_views("sweep-other-person"),
            "livenessScore": 92.0,
            "livenessPassed": True,
            "challengeId": _sweep_challenge(),
        },
    )
    assert other_person.status_code == 200
    other_data = other_person.json()
    assert other_data["verified"] is True
    assert other_data["isFaceMatch"] is False
    assert "Identity was not compared" in other_data["message"]

    duplicate_views = _head_sweep_views("duplicate-pose")
    shared = duplicate_views[0]["image"]
    for view in duplicate_views:
        view["image"] = shared
    duplicate = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveViews": duplicate_views,
            "livenessScore": 0.0,
            "livenessPassed": True,
            "challengeId": _sweep_challenge(),
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["verified"] is False
    assert "not distinct" in duplicate.json()["message"]

    unordered = _head_sweep_views("unordered")
    unordered[0]["yaw"] = -0.39
    unordered[1]["yaw"] = -0.80
    unordered_res = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveViews": unordered,
            "livenessScore": 0.0,
            "livenessPassed": True,
            "challengeId": _sweep_challenge(),
        },
    )
    assert unordered_res.status_code == 200
    assert unordered_res.json()["verified"] is False
    assert "left-to-right" in unordered_res.json()["message"]


def test_enroll_rejects_password_and_client_embedding():
    image = _data_url(b"reject-extra-fields")
    base = {
        "uin": "9876-5432-1300",
        "fullName": "Reject Extra",
        "email": "reject@citizen.asia",
        "faceImage": image,
    }
    with_password = client.post("/api/enroll", json={**base, "password": "SecretPassword123!"})
    assert with_password.status_code == 422
    with_embedding = client.post("/api/enroll", json={**base, "faceEmbedding": [0.1] * 128})
    assert with_embedding.status_code == 422


def test_api_credentials_issue_after_enroll():
    uin = "9876-5432-1400"
    password = "CitizenChosenPass9"
    image = _data_url(b"credential-portrait-bytes")

    short = client.post("/api/credentials", json={"uin": uin, "password": "short"})
    assert short.status_code == 422

    missing = client.post(
        "/api/credentials",
        json={"uin": "9876-5432-1499", "password": password},
    )
    assert missing.status_code == 404

    enroll_res = client.post(
        "/api/enroll",
        json={
            "uin": uin,
            "fullName": "Credential Citizen",
            "email": "credential@citizen.asia",
            "faceImage": image,
        },
    )
    assert enroll_res.status_code == 200
    assert "keycloakProvisioned" not in enroll_res.json()

    issued = client.post("/api/credentials", json={"uin": uin, "password": password})
    assert issued.status_code == 200
    body = issued.json()
    assert body["uin"] == uin
    assert isinstance(body["keycloakProvisioned"], bool)

    stored = IDRepoClient(enable_inprocess_fallback=True).get_identity(uin)
    assert stored is not None
    assert password not in json.dumps(stored)
