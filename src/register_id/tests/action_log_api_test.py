"""User-action rows on the portal API. No duration or telemetry fields."""

import base64
import json
import random
import secrets

import pytest
from fastapi.testclient import TestClient

from project.web import app
from register_id.audit import list_events
from register_id.face_descriptor import FACE_DESCRIPTOR_ENGINE
from register_id.idrepo_client import IDRepoClient
from register_id.reasons import citizen_message
from register_id.staff import add_member

client = TestClient(app)

GOOD_YAWS = [-0.6, -0.3, 0.0, 0.3, 0.6]
CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PROBE_IP = "198.51.100.20"


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("FILE_STORE", "1")
    monkeypatch.setenv("AUDIT_BACKEND", "file")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "stage-operator-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    local = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    monkeypatch.setattr("register_id.api.get_idrepo_client", lambda: local)
    return tmp_path


def _uin() -> str:
    return f"82{secrets.token_hex(6)}"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _image(tag: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(tag.encode()).decode()


def _consent() -> dict:
    return {
        "accepted": True,
        "purpose": "Store a face template for later identity checks",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }


def _descriptor(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-0.2, 0.2) for _ in range(128)]


def _noisy(base: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    return [value + rng.uniform(-0.01, 0.01) for value in base]


def _challenge(purpose: str) -> str:
    response = client.post("/api/face/challenge", json={"purpose": purpose})
    assert response.status_code == 200, response.text
    return response.json()["challengeId"]


def _liveness(purpose: str) -> dict:
    return {
        "challengeId": _challenge(purpose),
        "engine": FACE_DESCRIPTOR_ENGINE,
        "blinkCount": 1,
        "sweepYaws": GOOD_YAWS,
    }


def _enroll_descriptor(email: str, descriptors: list[list[float]]) -> str:
    from register_id.tests.conftest import enroll_headers

    response = client.post(
        "/api/enroll",
        headers={**enroll_headers(), "User-Agent": CHROME},
        json={
            "fullName": "Checked Citizen",
            "email": email,
            "gender": "Female",
            "dateOfBirth": "1990-01-02",
            "faceImage": _image(email),
            "faceDescriptors": descriptors,
            "liveness": _liveness("enroll"),
            "consent": _consent(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["uin"]


def _authenticate(uin: str, probe: list[float]) -> object:
    return client.post(
        "/api/authenticate",
        headers={"User-Agent": CHROME, "X-Forwarded-For": PROBE_IP},
        json={
            "uin": uin,
            "probeDescriptor": probe,
            "liveness": _liveness("check"),
        },
    )


def _activity(token: str) -> dict:
    response = client.get("/api/me/activity", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _assert_no_telemetry(payload: object) -> None:
    text = json.dumps(payload)
    for banned in ("duration", "latency", "elapsed", "telemetry"):
        assert banned not in text


def test_citizen_activity_has_message_and_device_without_network(isolated):
    base = _descriptor(21)
    uin = _enroll_descriptor("checked@citizen.asia", [base])
    matched = _authenticate(uin, _noisy(base, 22))
    assert matched.status_code == 200, matched.text
    body = matched.json()
    assert body["verified"] is True

    payload = _activity(body["activityToken"])
    assert payload["uin"] == uin
    assert payload["triesUsed"] == 0
    assert payload["askWasThisYou"] is False
    checks = payload["checks"]
    assert checks
    for row in checks:
        assert row["message"]
        assert row["device"] == "Chrome"
        assert "network" not in row
        assert "source" not in row
        assert "actor" not in row
    rendered = json.dumps(payload)
    assert PROBE_IP not in rendered
    _assert_no_telemetry(payload)


def test_match_failures_ask_was_this_you_only_at_three_tries(isolated):
    base = _descriptor(31)
    other = _descriptor(99)
    uin = _enroll_descriptor("checked@citizen.asia", [base])

    def fail_once() -> dict:
        response = _authenticate(uin, other)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verified"] is False
        return body

    first = fail_once()
    after_one = _activity(first["activityToken"])
    assert after_one["triesUsed"] == 1
    assert after_one["askWasThisYou"] is False

    camera = client.post(
        "/api/attempts",
        headers={"User-Agent": CHROME, "X-Forwarded-For": "203.0.113.8"},
        json={"kind": "camera", "reasonCode": "CAM-1", "detail": "permission denied"},
    )
    assert camera.status_code == 204
    after_camera = _activity(first["activityToken"])
    assert after_camera["triesUsed"] == 1
    assert after_camera["askWasThisYou"] is False

    fail_once()
    after_two = _activity(first["activityToken"])
    assert after_two["triesUsed"] == 2
    assert after_two["askWasThisYou"] is False

    fail_once()
    after_three = _activity(first["activityToken"])
    assert after_three["triesUsed"] == 3
    assert after_three["askWasThisYou"] is True
    _assert_no_telemetry(after_three)

    notices = [
        event
        for event in list_events()
        if event.get("uin") == uin and event.get("event") == "notification_sent"
    ]
    assert len(notices) == 1
    assert notices[0]["reasonCode"] == "LIMIT-1"
    assert notices[0]["result"] == "failure"
    failures = [
        event
        for event in list_events()
        if event.get("uin") == uin
        and event.get("event") == "authenticate"
        and event.get("result") == "failure"
    ]
    assert [event.get("reasonCode") for event in failures] == ["MATCH-1", "MATCH-1", "MATCH-1"]


def test_not_me_is_visible_to_the_officer_without_an_ip_for_the_citizen(isolated):
    base = _descriptor(41)
    uin = _enroll_descriptor("checked@citizen.asia", [base])
    matched = _authenticate(uin, _noisy(base, 42))
    assert matched.status_code == 200, matched.text
    body = matched.json()
    headers = _headers(body["activityToken"])
    reported = client.post(
        f"/api/me/activity/{body['checkId']}/not-me",
        headers={**headers, "User-Agent": CHROME, "X-Forwarded-For": PROBE_IP},
        json={"detail": "I did not stand at that desk"},
    )
    assert reported.status_code == 200, reported.text

    activity = _activity(body["activityToken"])
    rendered = json.dumps(activity)
    assert PROBE_IP not in rendered
    assert "network" not in rendered
    assert "actor" not in rendered
    reported_rows = [row for row in activity["checks"] if row.get("event") == "activity_reported"]
    assert reported_rows
    assert reported_rows[0]["message"]
    assert "source" not in reported_rows[0]
    assert body["checkId"] in activity["disputes"]

    officer = add_member("Desk Officer", "officer.action@register.test", "officer")
    reports = client.get("/api/reports", headers=_headers(officer["token"]))
    assert reports.status_code == 200, reports.text
    visible = [row for row in reports.json() if row.get("checkId") == body["checkId"]]
    assert visible
    assert visible[-1]["event"] == "activity_reported"
    assert _image(uin) not in reports.text
    assert "faceImage" not in reports.text
    _assert_no_telemetry(reports.json())


def test_lock_blocks_authenticate_with_the_citizen_sentence(isolated):
    base = _descriptor(51)
    uin = _enroll_descriptor("checked@citizen.asia", [base])
    officer = add_member("Lock Officer", "officer.lock@register.test", "officer")
    locked = client.post(
        f"/api/citizens/{uin}/lock",
        headers=_headers(officer["token"]),
        json={"locked": True, "reason": "Desk hold after a review"},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["locked"] is True
    reread = client.get(f"/api/citizens/{uin}", headers=_headers(officer["token"]))
    assert reread.status_code == 200
    assert reread.json()["locked"] is True

    blocked = _authenticate(uin, _noisy(base, 52))
    assert blocked.status_code == 423
    assert blocked.json()["detail"] == citizen_message("ID-2")
    assert blocked.json()["detail"] == "This ID is locked. Visit the office."

    rows = [event for event in list_events() if event.get("uin") == uin and event.get("event") == "uin_locked"]
    assert rows
    assert rows[-1]["reason"] == "Desk hold after a review"
    assert rows[-1]["result"] == "success"
    denied = [
        event
        for event in list_events()
        if event.get("uin") == uin and event.get("reasonCode") == "ID-2"
    ]
    assert denied
    assert denied[-1]["event"] == "authenticate"
    assert denied[-1]["result"] == "failure"
    _assert_no_telemetry(list_events())


def test_audit_uin_query_keeps_one_citizen(isolated):
    officer = add_member("Audit Officer", "officer.audit@register.test", "officer")
    first = _enroll_descriptor("first@citizen.asia", [_descriptor(61)])
    second = _enroll_descriptor("second@citizen.asia", [_descriptor(62)])

    filtered = client.get(
        "/api/audit",
        headers=_headers(officer["token"]),
        params={"uin": first},
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert rows
    assert {row["uin"] for row in rows} == {first}
    assert all(row.get("event") == "enroll" for row in rows)
    _assert_no_telemetry(rows)
