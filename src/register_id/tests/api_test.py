import base64
import json

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from project.web import app
from register_id.embedder import embed_face_image
from register_id.enroll_limit import (
    ENROLL_LIMIT_WINDOW_SECONDS,
    ENROLL_SUCCESS_LIMIT,
    EnrollLimitExceeded,
    EnrollLimitUnavailable,
    RedisEnrollLimiter,
    ensure_enroll_allowed,
    record_enroll_success,
    reset_enroll_limits,
)
from register_id.idrepo_client import IDRepoClient
from register_id.tests.conftest import TEST_ENROLL_TOKEN, enroll_headers

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


def _sweep_challenge() -> str:
    res = client.post("/api/sweep/challenge")
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "HEAD_SWEEP"
    assert body["timeLimitSeconds"] == 90
    return body["challengeId"]


def test_enroll_returns_502_when_idrepo_write_fails(monkeypatch):
    class FailingRepo:
        last_error = "connection refused"

        def add_identity(self, **kwargs: object) -> bool:
            del kwargs
            return False

    captured: list[dict] = []

    def capture(event: dict, **kwargs: object) -> dict:
        del kwargs
        captured.append(dict(event))
        return event

    monkeypatch.setattr("register_id.api.get_idrepo_client", lambda: FailingRepo())
    monkeypatch.setattr("register_id.api.record_event", capture)
    uin = "9876-5432-5020"
    res = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "uin": uin,
            "fullName": "Failed Write",
            "email": "fail@citizen.asia",
            "faceImage": _data_url(b"mock-face-bytes-write-fail"),
            "consent": _consent(),
        },
    )
    assert res.status_code == 502
    assert "MOSIP IDRepo" in res.json()["detail"]
    assert "connection refused" in res.json()["detail"]
    assert "faceImage" not in res.text
    stored = IDRepoClient(
        base_url="http://127.0.0.1:9",
        enable_inprocess_fallback=True,
    ).get_identity(uin)
    assert stored is None
    assert captured
    assert captured[-1]["kind"] == "enroll"
    assert captured[-1]["result"] == "failure"
    assert "idrepo" in captured[-1]["detail"]


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


def test_api_enroll_and_authenticate_flow(monkeypatch):
    face_image = _data_url(b"mock-face-bytes-enroll-front")
    other_image = _data_url(b"mock-face-bytes-impostor-probe")
    uin = "9876-5432-1098"

    enroll_payload = {
        "uin": uin,
        "fullName": "Test Citizen",
        "email": "test@citizen.asia",
        "faceImage": face_image,
        "consent": _consent(),
    }

    enroll_res = client.post("/api/enroll", headers=enroll_headers(), json=enroll_payload)
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

    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "test-operator")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    closed = client.get("/api/citizens")
    assert closed.status_code == 401
    headers = {"Authorization": "Bearer test-operator"}
    list_res = client.get("/api/citizens", headers=headers)
    assert list_res.status_code == 200
    detail_res = client.get(f"/api/citizens/{uin}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["uin"] == uin

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
        headers=enroll_headers(),
        json={
            "uin": uin,
            "fullName": "Sweep Citizen",
            "email": "sweep@citizen.asia",
            "faceImage": _data_url(b"sweep-portrait-for-cbeff"),
            "faceViews": views,
            "consent": _consent(),
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
        headers=enroll_headers(),
        json={
            "uin": "9876-5432-1101",
            "fullName": "Weak Turn",
            "email": "weak@citizen.asia",
            "faceImage": _data_url(b"weak-turn-portrait"),
            "consent": _consent(),
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
        headers=enroll_headers(),
        json={
            "uin": "9876-5432-1102",
            "fullName": "Copied Pose",
            "email": "copied@citizen.asia",
            "faceImage": _data_url(b"copied-portrait"),
            "faceViews": copied_views,
            "consent": _consent(),
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
        "consent": _consent(),
    }
    with_password = client.post("/api/enroll", headers=enroll_headers(), json={**base, "password": "SecretPassword123!"})
    assert with_password.status_code == 422
    with_embedding = client.post("/api/enroll", headers=enroll_headers(), json={**base, "faceEmbedding": [0.1] * 128})
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
        headers=enroll_headers(),
        json={
            "uin": uin,
            "fullName": "Credential Citizen",
            "email": "credential@citizen.asia",
            "faceImage": image,
            "consent": _consent(),
        },
    )
    assert enroll_res.status_code == 200
    assert "keycloakProvisioned" not in enroll_res.json()

    issued = client.post("/api/credentials", json={"uin": uin, "password": password})
    assert issued.status_code == 502
    assert "Keycloak did not store the login" in issued.json()["detail"]

    stored = IDRepoClient(enable_inprocess_fallback=True).get_identity(uin)
    assert stored is not None
    assert password not in json.dumps(stored)


def _enroll_body(uin: str, *, accepted: bool = True) -> dict:
    consent = _consent()
    consent["accepted"] = accepted
    return {
        "uin": uin,
        "fullName": "Limited Citizen",
        "email": "limited@citizen.asia",
        "faceImage": _data_url(b"enroll-limit-face-marker"),
        "consent": consent,
    }


def _stored(uin: str):
    return IDRepoClient(enable_inprocess_fallback=True).get_identity(uin)


def test_enroll_does_not_require_a_shared_token():
    uin = "4290-0000-8001"
    body = _enroll_body(uin)

    missing = client.post("/api/enroll", json=body)
    assert missing.status_code == 200, missing.text
    assert TEST_ENROLL_TOKEN not in missing.text
    assert body["faceImage"] not in missing.text
    assert _stored(uin) is not None


def test_enroll_rate_limit_blocks_the_31st_success_and_ignores_validation_failures(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    rejected = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json=_enroll_body("4290-0000-8100", accepted=False),
    )
    assert rejected.status_code == 422
    assert _stored("4290-0000-8100") is None

    for index in range(ENROLL_SUCCESS_LIMIT):
        uin = f"4291-{index:04d}-0000"
        response = client.post("/api/enroll", headers=enroll_headers(), json=_enroll_body(uin))
        assert response.status_code == 200, response.text
        assert _stored(uin) is not None

    blocked_uin = "4291-0030-0000"
    blocked = client.post("/api/enroll", json=_enroll_body(blocked_uin))
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Enrollment rate limit exceeded."
    assert TEST_ENROLL_TOKEN not in blocked.text
    assert _enroll_body(blocked_uin)["faceImage"] not in blocked.text
    assert _stored(blocked_uin) is None

    other = _enroll_body("4291-0031-0000")
    other["email"] = "Someone-Else@citizen.asia"
    allowed = client.post("/api/enroll", json=other)
    assert allowed.status_code == 200, allowed.text
    assert _stored("4291-0031-0000") is not None

    same_person = _enroll_body("4291-0032-0000")
    same_person["email"] = "  Limited@Citizen.asia  "
    still_blocked = client.post("/api/enroll", json=same_person)
    assert still_blocked.status_code == 429
    assert _stored("4291-0032-0000") is None


def test_memory_enroll_window_resets_when_the_hour_passes(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_enroll_limits()
    token = "window-token"
    opened = 1_000.0
    for _ in range(ENROLL_SUCCESS_LIMIT):
        ensure_enroll_allowed(token, now=opened)
        record_enroll_success(token, now=opened)
    with pytest.raises(EnrollLimitExceeded):
        ensure_enroll_allowed(token, now=opened + ENROLL_LIMIT_WINDOW_SECONDS - 1)
    ensure_enroll_allowed(token, now=opened + ENROLL_LIMIT_WINDOW_SECONDS)


def test_enroll_limit_uses_redis_and_fails_closed_when_it_is_down(monkeypatch):
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}
            self.expires: dict[str, int] = {}

        def get(self, name: str) -> str | None:
            return self.values.get(name)

        def incr(self, name: str) -> int:
            count = int(self.values.get(name, "0")) + 1
            self.values[name] = str(count)
            return count

        def expire(self, name: str, seconds: int) -> bool:
            self.expires[name] = seconds
            return True

    class DownRedis:
        def get(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RedisError("connection refused")

        def incr(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RedisError("connection refused")

        def expire(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RedisError("connection refused")

    fake = FakeRedis()
    holder = {"client": fake}

    def selected() -> RedisEnrollLimiter:
        return RedisEnrollLimiter(client=holder["client"])

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("register_id.enroll_limit.get_enroll_limiter", selected)

    uin = "4292-0000-0001"
    saved = client.post("/api/enroll", headers=enroll_headers(), json=_enroll_body(uin))
    assert saved.status_code == 200
    assert len(fake.values) == 1
    key, value = next(iter(fake.values.items()))
    assert value == "1"
    assert fake.expires[key] == ENROLL_LIMIT_WINDOW_SECONDS
    assert TEST_ENROLL_TOKEN not in key
    assert "limited@citizen.asia" not in key
    assert _enroll_body(uin)["faceImage"] not in key
    assert _stored(uin) is not None

    holder["client"] = DownRedis()
    blocked_uin = "4292-0000-0002"
    down = client.post("/api/enroll", headers=enroll_headers(), json=_enroll_body(blocked_uin))
    assert down.status_code == 503
    assert down.json()["detail"] == "Enrollment limit store is unavailable."
    assert TEST_ENROLL_TOKEN not in down.text
    assert _enroll_body(blocked_uin)["faceImage"] not in down.text
    assert _stored(blocked_uin) is None


def test_configured_redis_is_required_for_the_enroll_limit(monkeypatch):
    """REDIS_URL selects Redis, and a down counter is not replaced with memory."""

    class DownRedis:
        def get(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RedisError("connection refused")

    monkeypatch.setenv("REDIS_URL", "redis://limiter.internal:6379/0")
    reset_enroll_limits()

    def use_down(self, url: str | None = None, *, client: object = None) -> None:
        del url, client
        self._client = DownRedis()

    monkeypatch.setattr(RedisEnrollLimiter, "__init__", use_down)
    with pytest.raises(EnrollLimitUnavailable):
        ensure_enroll_allowed(TEST_ENROLL_TOKEN)
