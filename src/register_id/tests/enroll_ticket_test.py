"""Enrolment tickets keep one registration id across retries and restarts."""

import json
import time

import pytest
from redis.exceptions import RedisError

from register_id import enroll_ticket
from register_id.enroll_ticket import (
    Attempt,
    EnrollTicketUnavailable,
    consume_for_credentials,
    get_ticket,
    issue_ticket,
    remember_allocation,
    reset_tickets,
    take_credential,
    ticket_ttl,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def setex(self, name: str, ttl: int, value: str) -> bool:
        self.values[name] = value
        self.ttls[name] = ttl
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
        if nx and name in self.values:
            return None
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    def close(self) -> None:
        return None


class DownRedis:
    def setex(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisError("connection refused")

    def get(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisError("connection refused")

    def set(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisError("connection refused")

    def close(self) -> None:
        return None


def test_registration_id_stays_in_memory_when_redis_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    now = 5_000.0
    attempt = issue_ticket(now=now)
    remember_allocation(attempt, "uin-mem", "rid-mem", now=now)
    loaded = get_ticket(attempt.ticket, now=now + 1)
    assert loaded is not None
    assert loaded.registration_id == "rid-mem"
    assert loaded.uin == "uin-mem"
    credential = consume_for_credentials(attempt, now=now + 1)
    assert take_credential(credential, "uin-mem", now=now + 1) is True
    assert take_credential(credential, "uin-mem", now=now + 1) is False
    assert take_credential(credential, "other-uin", now=now + 1) is False
    reset_tickets()
    assert get_ticket(attempt.ticket, now=now + 1) is None


def test_remembered_registration_id_survives_cleared_memory_when_redis_is_faked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://ticket.internal:6379/0")
    monkeypatch.setattr(enroll_ticket, "_redis_client", lambda: fake)
    now = 1_700_000_000.0
    attempt = issue_ticket(now=now)
    remember_allocation(attempt, "uin-1", "rid-kept", now=now + 5)

    stored = json.loads(fake.values[f"register-id:enroll-ticket:ticket:{attempt.ticket}"])
    assert stored["ticket"] == attempt.ticket
    assert stored["uin"] == "uin-1"
    assert stored["registration_id"] == "rid-kept"
    assert stored["consumed"] is False
    assert stored["credential_ticket"] is None
    assert fake.ttls[f"register-id:enroll-ticket:ticket:{attempt.ticket}"] == ticket_ttl() - 5

    enroll_ticket._TICKETS[attempt.ticket] = Attempt(
        ticket=attempt.ticket,
        expires_at=attempt.expires_at,
        uin="uin-other",
        registration_id="rid-other",
    )
    reset_tickets()
    assert enroll_ticket._TICKETS == {}
    assert enroll_ticket._CREDENTIALS == {}

    loaded = get_ticket(attempt.ticket, now=now + 5)
    assert loaded is not None
    assert loaded.registration_id == "rid-kept"
    assert loaded.uin == "uin-1"
    assert loaded.consumed is False

    credential = consume_for_credentials(loaded, now=now + 5)
    reset_tickets()
    again = get_ticket(attempt.ticket, now=now + 5)
    assert again is not None
    assert again.registration_id == "rid-kept"
    assert again.consumed is True
    assert again.credential_ticket == credential
    assert take_credential(credential, "uin-1", now=now + 5) is True
    assert take_credential(credential, "uin-1", now=now + 5) is False
    assert enroll_ticket._TICKETS == {}
    assert enroll_ticket._CREDENTIALS == {}


def test_down_redis_does_not_fall_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://ticket.internal:6379/0")
    monkeypatch.setattr(enroll_ticket, "_redis_client", lambda: DownRedis())
    future = time.time() + 600
    decoy = Attempt(ticket="decoy", expires_at=future, registration_id="local-id")
    enroll_ticket._TICKETS["decoy"] = decoy

    with pytest.raises(EnrollTicketUnavailable, match="REDIS_URL"):
        issue_ticket(now=time.time())
    assert list(enroll_ticket._TICKETS) == ["decoy"]

    with pytest.raises(EnrollTicketUnavailable, match="REDIS_URL"):
        get_ticket("decoy", now=time.time())
    with pytest.raises(EnrollTicketUnavailable, match="REDIS_URL"):
        remember_allocation(decoy, "uin", "second-id", now=time.time())
    assert decoy.registration_id == "local-id"
    assert enroll_ticket._TICKETS["decoy"].registration_id == "local-id"
    with pytest.raises(EnrollTicketUnavailable, match="REDIS_URL"):
        take_credential("cred", "uin", now=time.time())


def test_configured_redis_down_does_not_keep_a_local_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    with pytest.raises(EnrollTicketUnavailable, match="REDIS_URL"):
        issue_ticket(now=time.time())
    assert enroll_ticket._TICKETS == {}
