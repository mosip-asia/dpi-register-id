"""Officer, admin, and citizen activity flows."""

import base64
import json
import random
import secrets

import pytest
from fastapi.testclient import TestClient

from project.web import app
from register_id.activity_grant import GRANT_TTL_SECONDS, issue_grant, resolve_grant
from register_id.audit import list_events
from register_id.face_descriptor import FACE_DESCRIPTOR_ENGINE
from register_id.idrepo_client import IDRepoClient
from register_id.keycloak import ProvisionResult
from register_id.staff import add_member

client = TestClient(app)

GOOD_YAWS = [-0.6, -0.3, 0.0, 0.3, 0.6]


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("FILE_STORE", "1")
    monkeypatch.setenv("AUDIT_BACKEND", "file")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTER_ID_OPERATOR_TOKEN", "stage-operator-token")
    monkeypatch.setenv("REGISTER_ID_OPERATOR_ROLE", "reader")
    monkeypatch.setattr(
        "register_id.keycloak.KeycloakBridgeClient.set_login_enabled",
        lambda self, uin, email, enabled: ProvisionResult(True, False, "enabled updated"),
    )
    local = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    monkeypatch.setattr("register_id.api.get_idrepo_client", lambda: local)
    return tmp_path


def _uin() -> str:
    return f"81{secrets.token_hex(6)}"


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


def _enroll(name: str, email: str) -> str:
    from register_id.tests.conftest import enroll_headers

    response = client.post(
        "/api/enroll",
        headers=enroll_headers(),
        json={
            "fullName": name,
            "email": email,
            "gender": "Female",
            "dateOfBirth": "1990-01-02",
            "faceImage": _image(email),
            "consent": _consent(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["uin"]


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


def _enroll_descriptor(email: str, descriptors: list[list[float]]) -> dict:
    from register_id.tests.conftest import enroll_headers

    response = client.post(
        "/api/enroll",
        headers=enroll_headers(),
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
    return response.json()


def _authenticate(uin: str, probe: list[float]) -> dict:
    response = client.post(
        "/api/authenticate",
        headers={"User-Agent": "DeskCheck/1.0", "X-Forwarded-For": "198.51.100.10"},
        json={
            "uin": uin,
            "probeDescriptor": probe,
            "liveness": _liveness("check"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _permanent(action: str, actor: str, reason: str) -> dict:
    matches = [
        event
        for event in list_events()
        if event.get("action") == action and event.get("actor") == actor and event.get("result") == "success"
    ]
    assert matches, action
    event = matches[-1]
    assert event["retention"] == "permanent"
    assert event["reason"] == reason
    assert event["actor"] == actor
    return event


def test_activity_grant_stores_only_a_hash_and_expires(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    token = issue_grant("8100-grant", path=tmp_path, now=1_000.0)
    assert resolve_grant(token, path=tmp_path, now=1_000.0 + GRANT_TTL_SECONDS - 1) == "8100-grant"
    assert resolve_grant(token, path=tmp_path, now=1_000.0 + GRANT_TTL_SECONDS) is None
    assert token not in (tmp_path / "activity-grants.json").read_text(encoding="utf-8")


def test_officer_can_search_and_correct_but_not_administer(isolated):
    officer = add_member("Desk Officer", "officer.desk@register.test", "officer")
    headers = _headers(officer["token"])
    email = "naree@citizen.asia"
    uin = _enroll("Naree Somsak", email)

    anonymous = client.get("/api/desk/session")
    assert anonymous.status_code == 401
    operator = client.get("/api/desk/session", headers=_headers("stage-operator-token"))
    assert operator.status_code == 200
    assert operator.json() == {"role": "reader", "actor": "reader"}
    session = client.get("/api/desk/session", headers=headers)
    assert session.status_code == 200
    assert session.json() == {"role": "officer", "actor": "officer.desk@register.test"}

    found = client.get("/api/citizens", headers=headers, params={"q": email})
    assert found.status_code == 200
    rows = found.json()
    assert len(rows) == 1
    assert rows[0]["uin"] == uin
    assert rows[0]["fullName"] == "Naree Somsak"
    assert rows[0]["email"] == email
    assert rows[0]["loginDisabled"] is False
    assert "faceImage" not in found.text

    person = client.get(f"/api/citizens/{uin}", headers=headers)
    assert person.status_code == 200
    assert person.json()["fullName"] == "Naree Somsak"
    assert person.json()["email"] == email
    assert person.json()["loginDisabled"] is False
    assert person.json()["locked"] is False

    checks = client.get(f"/api/citizens/{uin}/checks", headers=headers)
    assert checks.status_code == 200
    assert checks.json()["uin"] == uin
    assert checks.json()["checks"] == []

    renamed = client.post(
        f"/api/citizens/{uin}/demographics",
        headers=headers,
        json={
            "fullName": "Naree Somsri",
            "email": "naree.somsri@citizen.asia",
            "reason": "Correct a misspelled legal name",
        },
    )
    assert renamed.status_code == 200
    assert renamed.json()["fullName"] == "Naree Somsri"

    disabled = client.post(
        f"/api/citizens/{uin}/login-disabled",
        headers=headers,
        json={"disabled": True, "reason": "Disable login after a desk review"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["loginDisabled"] is True
    reread = client.get(f"/api/citizens/{uin}", headers=headers)
    assert reread.json()["email"] == "naree.somsri@citizen.asia"
    assert reread.json()["loginDisabled"] is True

    denied_face = client.post(
        f"/api/citizens/{uin}/delete-face",
        headers=headers,
        json={"reason": "Remove a face that is no longer valid"},
    )
    assert denied_face.status_code == 403
    denied_checks = client.get("/api/checks", headers=headers)
    assert denied_checks.status_code == 403
    denied_staff = client.post(
        "/api/staff",
        headers=headers,
        json={
            "name": "Extra Officer",
            "email": "extra.officer@register.test",
            "role": "officer",
            "reason": "New desk officer for the registry window",
        },
    )
    assert denied_staff.status_code == 403

    log_text = json.dumps(list_events())
    assert officer["token"] not in log_text
    _permanent("demographics", officer["email"], "Correct a misspelled legal name")
    _permanent("login", officer["email"], "Disable login after a desk review")


def test_admin_manages_staff_face_and_all_checks(isolated):
    admin = add_member("Desk Admin", "admin.desk@register.test", "admin")
    headers = _headers(admin["token"])
    uin = _uin()
    uin = _enroll("Chai Wit", "chai@citizen.asia")

    deleted = client.post(
        f"/api/citizens/{uin}/delete-face",
        headers=headers,
        json={"reason": "Remove a face that is no longer valid"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["faceDeleted"] is True

    created = client.post(
        "/api/staff",
        headers=headers,
        json={
            "name": "New Officer",
            "email": "new.officer@register.test",
            "role": "officer",
            "reason": "New desk officer for the registry window",
        },
    )
    assert created.status_code == 200
    member = created.json()
    assert member["role"] == "officer"
    assert member["token"]
    assert "token_hash" not in member

    promoted = client.post(
        f"/api/staff/{member['id']}/role",
        headers=headers,
        json={"role": "admin", "reason": "Promote officer to admin for the desk"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert "token" not in promoted.json()

    removed = client.request(
        "DELETE",
        f"/api/staff/{member['id']}",
        headers=headers,
        json={"reason": "Officer left the registry desk"},
    )
    assert removed.status_code == 200
    assert removed.json()["removed"] is True
    missing = client.request(
        "DELETE",
        f"/api/staff/{member['id']}",
        headers=headers,
        json={"reason": "Officer left the registry desk"},
    )
    assert missing.status_code == 404

    directory = client.get("/api/staff", headers=headers)
    assert directory.status_code == 200
    assert all(row["id"] != member["id"] for row in directory.json())
    assert all("token" not in row for row in directory.json())

    listing = client.get("/api/checks", headers=headers)
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)

    log_text = json.dumps(list_events())
    assert admin["token"] not in log_text
    assert member["token"] not in log_text
    added = _permanent("add_staff", admin["email"], "New desk officer for the registry window")
    assert added["uin"] == "staff"
    assert member["id"] in added["detail"]
    assert member["token"] not in added["detail"]
    _permanent("set_role", admin["email"], "Promote officer to admin for the desk")
    removed_event = _permanent("remove_staff", admin["email"], "Officer left the registry desk")
    assert member["id"] in removed_event["detail"]
    _permanent("delete_face", admin["email"], "Remove a face that is no longer valid")


def test_authenticate_writes_a_permanent_check_without_the_descriptor(isolated):
    base = _descriptor(7)
    probe = _noisy(base, 8)
    uin = _enroll_descriptor("checked@citizen.asia", [base])["uin"]
    body = _authenticate(uin, probe)
    assert body["verified"] is True
    assert body["checkId"].startswith("chk_")
    assert body["activityToken"]
    assert body["jwtToken"] is None

    text = json.dumps(list_events())
    assert json.dumps(probe) not in text
    assert _image(uin) not in text
    assert body["activityToken"] not in text
    checks = [event for event in list_events() if event.get("kind") == "authenticate" and event.get("uin") == uin]
    assert checks
    event = checks[-1]
    assert event["result"] == "success"
    assert event["retention"] == "permanent"
    assert event["livenessPassed"] is True
    assert event["matchPassed"] is True
    assert isinstance(event["matchScore"], float)
    assert event["checkId"] == body["checkId"]
    assert "reasonCode" not in event
    assert event["network"] == "198.51.100.10"
    assert event["browser"] == "DeskCheck/1.0"


def test_camera_attempt_with_an_empty_uin_is_stored(isolated):
    rejected = client.post(
        "/api/attempts",
        json={"kind": "camera", "reasonCode": "face_mismatch", "detail": "no"},
    )
    assert rejected.status_code == 422
    stored = client.post(
        "/api/attempts",
        headers={"User-Agent": "Kiosk/2", "X-Forwarded-For": "203.0.113.8"},
        json={"kind": "camera", "reasonCode": "camera_unavailable", "detail": "camera off"},
    )
    assert stored.status_code == 204
    assert stored.content == b""
    events = [
        event
        for event in list_events()
        if event.get("reasonCode") == "camera_unavailable" and event.get("uin") == ""
    ]
    assert events
    event = events[-1]
    assert event["kind"] == "camera"
    assert event["actor"] == "citizen"
    assert event["result"] == "failure"
    assert event["retention"] == "permanent"
    assert event["detail"] == "camera off"


def test_citizen_activity_token_can_dispute_only_their_check(isolated):
    first = _descriptor(11)
    second = _descriptor(12)
    own_uin = _enroll_descriptor("own@citizen.asia", [first])["uin"]
    other_uin = _enroll_descriptor("other@citizen.asia", [second])["uin"]

    matched = _authenticate(own_uin, _noisy(first, 13))
    missed = _authenticate(own_uin, second)
    other = _authenticate(other_uin, _noisy(second, 14))
    assert matched["verified"] is True
    assert missed["verified"] is False
    assert missed["activityToken"]
    assert missed["activityToken"] != matched["activityToken"]

    headers = _headers(matched["activityToken"])
    activity = client.get("/api/me/activity", headers=headers)
    assert activity.status_code == 200
    payload = activity.json()
    assert payload["uin"] == own_uin
    assert any(row.get("checkId") == matched["checkId"] for row in payload["checks"])

    reported = client.post(
        f"/api/me/activity/{matched['checkId']}/not-me",
        headers=headers,
        json={"detail": "I did not stand at that desk"},
    )
    assert reported.status_code == 200
    assert reported.json() == {"checkId": matched["checkId"], "reported": True}
    again = client.get("/api/me/activity", headers=headers)
    assert matched["checkId"] in again.json()["disputes"]

    foreign = client.post(
        f"/api/me/activity/{other['checkId']}/not-me",
        headers=headers,
        json={"detail": "This check belongs to someone else"},
    )
    assert foreign.status_code == 404

    failed_headers = _headers(missed["activityToken"])
    failed_activity = client.get("/api/me/activity", headers=failed_headers)
    assert failed_activity.status_code == 200
    assert failed_activity.json()["uin"] == own_uin

    log_text = json.dumps(list_events())
    assert matched["activityToken"] not in log_text
    assert missed["activityToken"] not in log_text
    assert other["activityToken"] not in log_text
    disputes = [event for event in list_events() if event.get("kind") == "dispute" and event.get("uin") == own_uin]
    assert disputes
    assert disputes[-1]["action"] == "not_me"
    assert disputes[-1]["retention"] == "permanent"
    assert disputes[-1]["result"] == "success"
    assert disputes[-1]["reason"] == "I did not stand at that desk"
    assert disputes[-1]["checkId"] == matched["checkId"]
    assert disputes[-1]["actor"] == "citizen"
