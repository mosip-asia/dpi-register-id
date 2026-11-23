"""Browser face-descriptor path: challenge, client liveness, enroll, and 1:1 check."""

import base64
import json
import random
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mock.idrepo import storage as storage_module
from project.web import app
from register_id.challenge_store import RedisChallengeStore, get_challenge_store
from register_id.embedder import embed_face_image
from register_id.face_check import compare_descriptor
from register_id.face_descriptor import (
    DESCRIPTOR_CONSISTENCY_LIMIT,
    DESCRIPTOR_MATCH_THRESHOLD,
    FACE_DESCRIPTOR_ENGINE,
    MIN_BLINKS,
    assess_client_liveness,
    create_face_challenge,
    descriptors_consistent,
    validate_descriptor,
)
from register_id.idrepo_client import IDRepoClient
from register_id.tests.conftest import enroll_headers
from register_id.models import ClientLiveness
from register_id.tests.challenge_store_test import FakeRedis

client = TestClient(app)

GOOD_YAWS = [-0.6, -0.3, 0.0, 0.3, 0.6]


@pytest.fixture
def idrepo(monkeypatch: pytest.MonkeyPatch, tmp_path) -> IDRepoClient:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "face-reader")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    local = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    monkeypatch.setattr("register_id.api.get_idrepo_client", lambda: local)
    return local


def _uin() -> str:
    return f"7100-{secrets.randbelow(10**8):08d}"


def _descriptor(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-0.2, 0.2) for _ in range(128)]


def _noisy(base: list[float], seed: int, scale: float = 0.01) -> list[float]:
    rng = random.Random(seed)
    return [value + rng.uniform(-scale, scale) for value in base]


def _image(tag: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(tag.encode()).decode()


def _consent() -> dict:
    return {
        "accepted": True,
        "purpose": "Store a face template for later identity checks",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }


def _challenge(purpose: str) -> str:
    res = client.post("/api/face/challenge", json={"purpose": purpose})
    assert res.status_code == 200
    return res.json()["challengeId"]


def _liveness(challenge_id: str, blinks: int = 1, yaws: list[float] | None = None) -> dict:
    return {
        "challengeId": challenge_id,
        "engine": FACE_DESCRIPTOR_ENGINE,
        "blinkCount": blinks,
        "sweepYaws": GOOD_YAWS if yaws is None else yaws,
    }


def _model(challenge_id: str, blinks: int = 1, yaws: list[float] | None = None) -> ClientLiveness:
    return ClientLiveness.model_validate(_liveness(challenge_id, blinks, yaws))


def _enroll(uin: str, descriptors: list[list[float]], **overrides) -> object:
    body = {
        "uin": uin,
        "fullName": "Descriptor Citizen",
        "email": "descriptor@citizen.asia",
        "faceImage": _image(f"portrait-{uin}"),
        "faceDescriptors": descriptors,
        "liveness": _liveness(_challenge("enroll")),
        "consent": _consent(),
    }
    body.update(overrides)
    return client.post("/api/enroll", json=body, headers=enroll_headers())


def _seed_gallery(idrepo: IDRepoClient, uin: str, descriptors: list[list[float]]) -> None:
    """Store face-api rows directly when a test is not checking enroll."""
    assert idrepo.add_identity(
        uin=uin,
        full_name="Descriptor Citizen",
        email="descriptor@citizen.asia",
        templates=[
            {"sector": "front", "embedding": values, "engine": FACE_DESCRIPTOR_ENGINE}
            for values in descriptors
        ],
        status="draft",
    )


def _check(uin: str, probe: list[float], challenge_id: str | None = None) -> object:
    return client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "probeDescriptor": probe,
            "liveness": _liveness(challenge_id or _challenge("check")),
        },
    )


# Challenge and client liveness


def test_face_challenge_issues_purpose_and_ttl(idrepo):
    enroll = client.post("/api/face/challenge", json={"purpose": "enroll"})
    assert enroll.status_code == 200
    body = enroll.json()
    assert body["challengeId"].startswith("face_")
    assert body["purpose"] == "enroll"
    assert body["expiresInSeconds"] == 600
    assert body["requiredBlinks"] == MIN_BLINKS == 0
    assert body["sectors"] == ["far-left", "left", "front", "right", "far-right"]
    stored = get_challenge_store().peek(body["challengeId"])
    assert stored is not None and stored["purpose"] == "enroll"

    check = client.post("/api/face/challenge", json={"purpose": "check"}).json()
    assert check["purpose"] == "check"
    assert check["expiresInSeconds"] == 120

    assert client.post("/api/face/challenge", json={"purpose": "login"}).status_code == 422
    assert client.post("/api/face/challenge", json={}).status_code == 422
    extra = client.post("/api/face/challenge", json={"purpose": "check", "ttl": 9999})
    assert extra.status_code == 422


def test_face_challenge_uses_redis_store_when_selected(monkeypatch: pytest.MonkeyPatch):
    store = RedisChallengeStore(client=FakeRedis())
    monkeypatch.setattr("register_id.face_descriptor.get_challenge_store", lambda: store)
    issued = create_face_challenge("check", now=1_000)
    assert store.peek(issued.challengeId)["purpose"] == "check"
    assert assess_client_liveness(_model(issued.challengeId), "check", now=1_000).ok is True
    assert assess_client_liveness(_model(issued.challengeId), "check", now=1_000).ok is False


def test_liveness_challenge_is_single_use(idrepo):
    challenge_id = create_face_challenge("check").challengeId
    first = assess_client_liveness(_model(challenge_id), "check")
    assert first.ok is True
    assert first.source == "client"
    assert "reported by the browser" in first.message
    assert "did not measure" in first.message

    second = assess_client_liveness(_model(challenge_id), "check")
    assert second.ok is False
    assert "already used" in second.message


def test_liveness_challenge_expires(idrepo):
    challenge_id = create_face_challenge("check", now=1_000).challengeId
    late = assess_client_liveness(_model(challenge_id), "check", now=1_000 + 121)
    assert late.ok is False
    assert "expired" in late.message

    enroll_id = create_face_challenge("enroll", now=1_000).challengeId
    assert assess_client_liveness(_model(enroll_id), "enroll", now=1_000 + 599).ok is True


def test_liveness_purpose_mismatch_is_rejected(idrepo):
    enroll_id = create_face_challenge("enroll").challengeId
    result = assess_client_liveness(_model(enroll_id), "check")
    assert result.ok is False
    assert "not issued for check" in result.message

    sweep_id = client.post("/api/sweep/challenge").json()["challengeId"]
    sweep_result = assess_client_liveness(_model(sweep_id), "check")
    assert sweep_result.ok is False


def test_zero_blinks_are_accepted_when_the_sweep_is_valid(idrepo):
    result = assess_client_liveness(_model(create_face_challenge("check").challengeId, blinks=0), "check")
    assert result.ok is True
    assert "head sweep" in result.message


@pytest.mark.parametrize(
    "yaws",
    [
        [-0.6, -0.3, -0.3, 0.3, 0.6],
        [0.6, 0.3, 0.0, -0.3, -0.6],
        [-0.6, -0.3, 0.0, 0.05, 0.6],
    ],
)
def test_yaw_that_does_not_step_left_to_right_is_rejected(idrepo, yaws):
    result = assess_client_liveness(
        _model(create_face_challenge("check").challengeId, yaws=yaws), "check"
    )
    assert result.ok is False
    assert result.message == (
        "Head turn not accepted: the browser reported yaw that does not step left to right."
    )


def test_small_yaw_span_is_rejected(idrepo):
    yaws = [-0.2, -0.1, 0.0, 0.1, 0.2]
    result = assess_client_liveness(
        _model(create_face_challenge("check").challengeId, yaws=yaws), "check"
    )
    assert result.ok is False
    assert "browser reported a turn of 0.40" in result.message


@pytest.mark.parametrize(
    "change",
    [
        {"sweepYaws": [-0.6, -0.3, 0.0, 0.3]},
        {"sweepYaws": [-0.6, -0.3, 0.0, 0.3, 0.6, 0.9]},
        {"sweepYaws": [-1.6, -0.3, 0.0, 0.3, 0.6]},
        {"sweepYaws": [float("nan"), -0.3, 0.0, 0.3, 0.6]},
        {"blinkCount": 51},
        {"blinkCount": -1},
        {"engine": "hash"},
        {"extra": True},
    ],
)
def test_client_liveness_model_rejects_bad_shapes(change):
    with pytest.raises(ValidationError):
        ClientLiveness.model_validate({**_liveness("face_x"), **change})


# Descriptor helpers


def test_validate_descriptor_length_and_finite_values():
    good = _descriptor(1)
    assert validate_descriptor(good) == good

    with pytest.raises(ValueError, match="must have 128 values, not 127"):
        validate_descriptor(good[:127])
    for bad in (float("nan"), float("inf"), -float("inf"), 2.5):
        vector = list(good)
        vector[5] = bad
        with pytest.raises(ValueError, match="finite number"):
            validate_descriptor(vector)
    edge = list(good)
    edge[0] = 2.0
    assert validate_descriptor(edge)[0] == 2.0


def test_descriptor_consistency_and_comparison():
    base = _descriptor(2)
    assert descriptors_consistent([base, _noisy(base, 3), _noisy(base, 4)]) is True
    assert descriptors_consistent([base, _descriptor(5)]) is False
    assert DESCRIPTOR_CONSISTENCY_LIMIT == 0.6

    empty = compare_descriptor([], base)
    assert empty.is_face_match is False
    assert empty.distance is None
    assert empty.engine == FACE_DESCRIPTOR_ENGINE

    near = compare_descriptor([_descriptor(5), base], _noisy(base, 6))
    assert near.is_face_match is True
    assert near.distance is not None and near.distance < DESCRIPTOR_MATCH_THRESHOLD
    assert near.threshold == DESCRIPTOR_MATCH_THRESHOLD
    assert near.score is not None and near.score > 0

    far = compare_descriptor([base], _descriptor(7))
    assert far.is_face_match is False
    assert far.distance is not None and far.distance >= DESCRIPTOR_MATCH_THRESHOLD


# Enroll


def test_enroll_requires_descriptors_and_liveness_together(idrepo):
    uin = _uin()
    only_descriptors = _enroll(uin, [_descriptor(10)], liveness=None)
    assert only_descriptors.status_code == 422

    body = {
        "uin": uin,
        "fullName": "Half Request",
        "email": "half@citizen.asia",
        "faceImage": _image("half"),
        "liveness": _liveness(_challenge("enroll")),
        "consent": _consent(),
    }
    only_liveness = client.post("/api/enroll", json=body, headers=enroll_headers())
    assert only_liveness.status_code == 422
    assert idrepo.get_identity(uin) is None


def test_enroll_with_descriptors_stores_a_draft_and_the_face_templates(idrepo):
    uin = _uin()
    base = _descriptor(20)
    frames = [base, _noisy(base, 21), _noisy(base, 22)]
    portrait = _image(f"portrait-{uin}")

    res = _enroll(uin, frames)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "SUCCESS"
    assert body["recordStatus"] == "draft"
    assert body["cbeffGenerated"] is True
    assert "faceEngine" not in body
    assert "livenessSource" not in body
    assert "templateCount" not in body
    assert body["message"] == (
        "Citizen demographics stored as a draft via MOSIP IDRepo interface. "
        "The browser report is not a server liveness check."
    )

    stored = idrepo.get_identity(uin, include_biometrics=True)
    assert stored["status"] == "draft"
    assert stored["full_name"] == "Descriptor Citizen"
    assert stored["email"] == "descriptor@citizen.asia"
    assert not stored.get("face_image")
    assert not stored.get("cbeff_xml")
    assert portrait not in json.dumps(stored)
    templates = idrepo.get_face_templates(uin)
    face_rows = [row for row in templates if row.get("engine") == FACE_DESCRIPTOR_ENGINE]
    hash_rows = [row for row in templates if row.get("engine") == "hash"]
    assert [row["embedding"] for row in face_rows] == frames
    assert hash_rows == [
        {"sector": "front", "embedding": embed_face_image(portrait), "engine": "hash"}
    ]


def test_inconsistent_frames_are_rejected_and_nothing_is_stored(idrepo):
    uin = _uin()
    res = _enroll(uin, [_descriptor(30), _descriptor(31)])
    assert res.status_code == 422
    assert res.json()["detail"] == "The captured frames do not look like the same face. Scan again."
    assert idrepo.get_identity(uin) is None
    assert idrepo.get_face_templates(uin) == []

    audit = client.get("/api/audit", headers={"Authorization": "Bearer face-reader"}).json()
    assert any(e["uin"] == uin and e["result"] == "failure" for e in audit)


def test_enroll_rejects_bad_descriptor_and_failed_liveness(idrepo):
    uin = _uin()
    short = _enroll(uin, [_descriptor(40)[:100]])
    assert short.status_code == 422
    assert short.json()["detail"] == "Face descriptor 1 must have 128 values, not 100."

    too_many = _enroll(uin, [_descriptor(41)] * 6)
    assert too_many.status_code == 422

    wrong_purpose = _enroll(uin, [_descriptor(43)], liveness=_liveness(_challenge("check")))
    assert wrong_purpose.status_code == 422
    assert idrepo.get_identity(uin) is None


def test_enroll_without_descriptors_stays_a_hash_draft(idrepo):
    uin = _uin()
    portrait = _image(f"hash-{uin}")
    res = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "uin": uin,
            "fullName": "Hash Citizen",
            "email": "hash@citizen.asia",
            "faceImage": portrait,
            "consent": _consent(),
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["recordStatus"] == "draft"
    assert "faceEngine" not in body
    stored = idrepo.get_identity(uin, include_biometrics=True)
    assert stored["status"] == "draft"
    assert stored["full_name"] == "Hash Citizen"
    assert stored["email"] == "hash@citizen.asia"
    assert not stored.get("face_image")
    assert not stored.get("cbeff_xml")
    assert portrait not in json.dumps(stored)
    templates = idrepo.get_face_templates(uin)
    assert templates
    assert all("engine" not in row for row in templates)


# Authenticate


def test_enrolled_descriptor_matches_on_verify(idrepo):
    uin = _uin()
    base = _descriptor(49)
    enrolled = _enroll(uin, [base, _noisy(base, 50)])
    assert enrolled.status_code == 200, enrolled.text

    body = _check(uin, _noisy(base, 51)).json()
    assert body["isFaceMatch"] is True
    assert body["verified"] is True
    assert body["compared"] is True
    assert body["status"] == "SUCCESS"


def test_authenticate_same_face_matches_on_the_server(idrepo):
    uin = _uin()
    base = _descriptor(50)
    _seed_gallery(idrepo, uin, [base, _noisy(base, 51)])

    res = _check(uin, _noisy(base, 52))
    assert res.status_code == 200
    body = res.json()
    assert body["isFaceMatch"] is True
    assert body["verified"] is True
    assert body["compared"] is True
    assert body["status"] == "SUCCESS"
    assert body["livenessPassed"] is True
    assert body["livenessSource"] == "client"
    assert body["yawSource"] == "client"
    assert body["threshold"] == 0.5
    assert body["euclideanDistance"] < 0.5
    assert body["euclideanDistance"] == round(body["euclideanDistance"], 4)
    assert body["jwtToken"] is None
    assert body["citizen"] == {"uin": uin}


def test_authenticate_different_face_does_not_match(idrepo):
    uin = _uin()
    base = _descriptor(60)
    _seed_gallery(idrepo, uin, [base])

    body = _check(uin, _descriptor(61)).json()
    assert body["isFaceMatch"] is False
    assert body["verified"] is False
    assert body["compared"] is True
    assert body["status"] == "FAILED"
    assert body["euclideanDistance"] >= 0.5


def test_authenticate_replayed_challenge_is_rejected(idrepo):
    uin = _uin()
    base = _descriptor(70)
    _seed_gallery(idrepo, uin, [base])

    challenge_id = _challenge("check")
    assert _check(uin, _noisy(base, 71), challenge_id).json()["isFaceMatch"] is True

    replay = _check(uin, _noisy(base, 72), challenge_id)
    assert replay.status_code == 200
    body = replay.json()
    assert body["status"] == "FAILED"
    assert body["verified"] is False
    assert body["isFaceMatch"] is False
    assert body["livenessPassed"] is False
    assert body["compared"] is False
    assert body["euclideanDistance"] is None
    assert "already used" in body["message"]


def test_authenticate_hash_only_identity_asks_to_enroll_again(idrepo):
    uin = _uin()
    enrolled = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "uin": uin,
            "fullName": "Hash Only",
            "email": "hash-only@citizen.asia",
            "faceImage": _image(f"hash-only-{uin}"),
            "consent": _consent(),
        },
    )
    assert enrolled.status_code == 200

    body = _check(uin, _descriptor(80)).json()
    assert body["compared"] is False
    assert body["isFaceMatch"] is False
    assert body["verified"] is False
    assert body["message"] == (
        "This ID has no face template from the browser model. Enroll again in the portal."
    )


def test_authenticate_descriptor_request_shapes(idrepo):
    uin = _uin()
    assert _enroll(uin, [_descriptor(90)]).status_code == 200

    missing_liveness = client.post(
        "/api/authenticate", json={"uin": uin, "probeDescriptor": _descriptor(90)}
    )
    assert missing_liveness.status_code == 422

    liveness_without_probe = client.post(
        "/api/authenticate",
        json={
            "uin": uin,
            "liveImage": _image("x"),
            "livenessScore": 1.0,
            "livenessPassed": False,
            "liveness": _liveness(_challenge("check")),
        },
    )
    assert liveness_without_probe.status_code == 422

    short_probe = _check(uin, _descriptor(90)[:64])
    assert short_probe.status_code == 422
    assert short_probe.json()["detail"] == "Probe descriptor must have 128 values, not 64."

    unknown = _check("7199-00000000", _descriptor(90))
    assert unknown.status_code == 404


def test_image_path_still_never_matches_a_descriptor_identity(idrepo):
    uin = _uin()
    base = _descriptor(95)
    portrait = _image(f"portrait-{uin}")
    assert _enroll(uin, [base], faceImage=portrait).status_code == 200

    res = client.post(
        "/api/authenticate",
        json={"uin": uin, "liveImage": portrait, "livenessScore": 90.0, "livenessPassed": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["isFaceMatch"] is False
    assert body["compared"] is False
    assert body["livenessSource"] is None
    assert body["euclideanDistance"] is None


# Leakage


def test_descriptors_stay_out_of_operator_reads_and_audit(idrepo):
    uin = _uin()
    base = _descriptor(100)
    enrolled = _enroll(uin, [base, _noisy(base, 101)])
    assert enrolled.status_code == 200
    assert enrolled.json()["recordStatus"] == "draft"
    _seed_gallery(idrepo, uin, [base, _noisy(base, 101)])
    _check(uin, _noisy(base, 102))
    _check(uin, _descriptor(103))

    headers = {"Authorization": "Bearer face-reader"}
    citizen = client.get(f"/api/citizens/{uin}", headers=headers)
    assert citizen.status_code == 200
    listing = client.get("/api/citizens", headers=headers)
    assert listing.status_code == 200
    audit = client.get("/api/audit", headers=headers)
    assert audit.status_code == 200

    texts = [
        citizen.text,
        listing.text,
        audit.text,
        json.dumps(idrepo.get_identity(uin)),
        json.dumps(idrepo.list_identities(limit=50)),
    ]
    markers = [repr(value) for value in base[:8]] + [repr(value) for value in _descriptor(103)[:8]]
    for text in texts:
        for marker in markers:
            assert marker not in text
        assert "embedding" not in text

    events = [e for e in audit.json() if e["uin"] == uin]
    assert [e["kind"] for e in events] == ["enroll", "authenticate", "authenticate", "operator"]
    assert "draft stored" in events[0]["detail"]
    assert "browser report is not a server liveness check" in events[0]["detail"]
    assert "biometric" not in events[0]["detail"]
    assert "match at distance" in events[1]["detail"]
    assert "no match at distance" in events[2]["detail"]


# Template rows round-trip


def test_mock_and_client_round_trip_engine_on_template_rows(idrepo):
    uin = _uin()
    rows = [
        {"sector": "front", "embedding": [0.1] * 128, "engine": FACE_DESCRIPTOR_ENGINE},
        {"sector": "front", "embedding": [0.2] * 128, "engine": FACE_DESCRIPTOR_ENGINE},
        {"sector": "front", "embedding": [0.3] * 128, "engine": "hash"},
        {"sector": "left", "embedding": [0.4] * 128},
    ]
    assert idrepo.add_identity(uin=uin, full_name="Rows", templates=rows) is True
    stored = idrepo.get_face_templates(uin)
    key = lambda row: (row["sector"], row["embedding"][0])  # noqa: E731
    assert sorted(stored, key=key) == sorted(rows, key=key)


def test_sqlite_migration_keeps_legacy_template_rows(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(storage_module, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(storage_module, "_SQLITE_PATH", tmp_path / "idrepo.db")
    monkeypatch.setattr(storage_module, "POSTGRES_PORT", 9)

    legacy = sqlite3.connect(str(tmp_path / "idrepo.db"))
    with legacy:
        legacy.execute(
            "CREATE TABLE face_template (uin TEXT NOT NULL, sector TEXT NOT NULL, "
            "embedding TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (uin, sector))"
        )
        legacy.execute(
            "INSERT INTO face_template (uin, sector, embedding) VALUES (?, ?, ?)",
            ("legacy-1", "front", json.dumps([0.5, 0.25])),
        )
    legacy.close()

    store = storage_module.IDRepoStorage()
    assert store.active_backend == "sqlite"
    assert store.get_face_templates("legacy-1") == [{"sector": "front", "embedding": [0.5, 0.25]}]

    assert store.save_face_templates(
        "legacy-1",
        [
            {"sector": "front", "embedding": [0.1, 0.2], "engine": FACE_DESCRIPTOR_ENGINE},
            {"sector": "front", "embedding": [0.3, 0.4], "engine": FACE_DESCRIPTOR_ENGINE},
        ],
    )
    reread = store.get_face_templates("legacy-1")
    assert len(reread) == 2
    assert all(row["engine"] == FACE_DESCRIPTOR_ENGINE for row in reread)
