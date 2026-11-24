"""Single-use enrolment tickets.

The browser asks for a ticket, sends it once on enrol, and receives a
separate single-use credential ticket bound to the UIN this attempt allocated.
Nothing here is rendered into HTML. A failed write keeps the UIN and the
registration id on the same ticket so a retry does not mint another one.

The record stays in a process-local dict when REDIS_URL is unset, which is
enough for one process and for tests. When REDIS_URL is set, the same record
is stored in Redis so another worker, or this process after a restart, reuses
that registration id and UIN:

- ``register-id:enroll-ticket:ticket:{token}`` — token, expiry, UIN,
  registration id, consumed flag, and credential ticket. The key TTL is the
  remaining ticket life, extended to the credential deadline when a
  credential ticket must still be accepted after the enrol ticket itself
  has expired.
- ``register-id:enroll-ticket:credential:{credential}`` — the enrol token
  for that single-use credential.

A configured Redis that cannot be reached raises EnrollTicketUnavailable.
The in-memory dict is not a fallback.
"""

from __future__ import annotations

import json
import logging
import math
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_TICKETS: dict[str, "Attempt"] = {}
_CREDENTIALS: dict[str, str] = {}
_PREFIX = "register-id:enroll-ticket:"
_UNAVAILABLE = (
    "Enrollment ticket store is unavailable. "
    "REDIS_URL is configured, so the ticket was not kept in process memory."
)


class EnrollTicketUnavailable(Exception):
    """REDIS_URL is set, but the enrolment ticket cannot be stored or read."""


def _bounded(name: str, default: int, low: int, high: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return min(max(value, low), high)


def ticket_ttl() -> int:
    return _bounded("ENROLL_TICKET_TTL_SECONDS", 900, 60, 3600)


def credential_ttl() -> int:
    return _bounded("ENROLL_CREDENTIAL_TTL_SECONDS", 900, 60, 3600)


@dataclass
class Attempt:
    ticket: str
    expires_at: float
    uin: str | None = None
    registration_id: str | None = None
    consumed: bool = False
    credential_ticket: str | None = None
    credential_expires: float = 0.0
    credential_used: bool = False

    def alive(self, now: float) -> bool:
        return now <= self.expires_at


def reset_tickets() -> None:
    """Drop process-local tickets. Redis records are left to expire on their TTL."""
    with _LOCK:
        _TICKETS.clear()
        _CREDENTIALS.clear()


def issue_ticket(now: float | None = None) -> Attempt:
    clock = time.time() if now is None else now
    attempt = Attempt(
        ticket=secrets.token_urlsafe(32),
        expires_at=clock + ticket_ttl(),
    )
    _save(attempt, clock)
    return attempt


def get_ticket(ticket: str, now: float | None = None) -> Attempt | None:
    if not ticket:
        return None
    clock = time.time() if now is None else now
    client = _redis_client()
    if client is None:
        with _LOCK:
            attempt = _TICKETS.get(ticket)
        if attempt is None or not attempt.alive(clock):
            return None
        return attempt
    try:
        raw = _call(lambda: client.get(_ticket_key(ticket)))
    finally:
        _close_client(client)
    if not raw:
        return None
    attempt = _load(raw)
    if not attempt.alive(clock):
        return None
    return attempt


def remember_allocation(
    attempt: Attempt,
    uin: str,
    registration_id: str,
    now: float | None = None,
) -> None:
    clock = time.time() if now is None else now
    updated = Attempt(**asdict(attempt))
    updated.uin = uin
    updated.registration_id = registration_id
    _save(updated, clock)
    attempt.uin = uin
    attempt.registration_id = registration_id


def consume_for_credentials(attempt: Attempt, now: float | None = None) -> str:
    clock = time.time() if now is None else now
    credential = secrets.token_urlsafe(32)
    updated = Attempt(**asdict(attempt))
    updated.consumed = True
    updated.credential_ticket = credential
    updated.credential_expires = clock + credential_ttl()
    updated.credential_used = False
    _save(updated, clock)
    attempt.consumed = True
    attempt.credential_ticket = credential
    attempt.credential_expires = updated.credential_expires
    attempt.credential_used = False
    return credential


def take_credential(credential: str, uin: str, now: float | None = None) -> bool:
    """Bind a password set to the enrolment that allocated this UIN. Single use."""
    if not credential or not uin:
        return False
    clock = time.time() if now is None else now
    client = _redis_client()
    if client is None:
        return _take_memory(credential, uin, clock)
    try:
        return _take_redis(client, credential, uin, clock)
    finally:
        _close_client(client)


def _take_memory(credential: str, uin: str, clock: float) -> bool:
    with _LOCK:
        ticket = _CREDENTIALS.get(credential)
        attempt = _TICKETS.get(ticket) if ticket else None
        if attempt is None or attempt.credential_used:
            return False
        if attempt.credential_ticket != credential or attempt.uin != uin:
            return False
        if clock > attempt.credential_expires:
            return False
        attempt.credential_used = True
        _TICKETS[attempt.ticket] = attempt
        return True


def _take_redis(client: Any, credential: str, uin: str, clock: float) -> bool:
    pointer = _call(lambda: client.get(_credential_key(credential)))
    if not isinstance(pointer, str) or not pointer:
        return False
    raw = _call(lambda: client.get(_ticket_key(pointer)))
    if not raw:
        return False
    attempt = _load(raw)
    if attempt.credential_used:
        return False
    if attempt.credential_ticket != credential or attempt.uin != uin:
        return False
    if clock > attempt.credential_expires:
        return False
    claim_ttl = _positive_ttl(attempt.credential_expires, clock)
    claimed = _call(lambda: client.set(_used_key(credential), "1", nx=True, ex=claim_ttl))
    if not claimed:
        return False
    attempt.credential_used = True
    _write_redis(client, attempt, clock)
    return True


def _save(attempt: Attempt, now: float) -> None:
    client = _redis_client()
    if client is None:
        with _LOCK:
            _TICKETS[attempt.ticket] = Attempt(**asdict(attempt))
            if attempt.credential_ticket:
                _CREDENTIALS[attempt.credential_ticket] = attempt.ticket
        return
    try:
        _write_redis(client, attempt, now)
    finally:
        _close_client(client)


def _write_redis(client: Any, attempt: Attempt, now: float) -> None:
    payload = _dump(attempt)
    deadline = attempt.expires_at
    credential = attempt.credential_ticket
    if credential and attempt.credential_expires > deadline:
        deadline = attempt.credential_expires
    _call(
        lambda: client.setex(
            _ticket_key(attempt.ticket),
            _positive_ttl(deadline, now),
            payload,
        )
    )
    if credential:
        cred_ttl = _positive_ttl(attempt.credential_expires, now)
        _call(lambda: client.setex(_credential_key(credential), cred_ttl, attempt.ticket))


def _positive_ttl(deadline: float, now: float) -> int:
    return max(1, math.ceil(deadline - now))


def _ticket_key(ticket: str) -> str:
    return f"{_PREFIX}ticket:{ticket}"


def _credential_key(credential: str) -> str:
    return f"{_PREFIX}credential:{credential}"


def _used_key(credential: str) -> str:
    return f"{_PREFIX}used:{credential}"


def _dump(attempt: Attempt) -> str:
    return json.dumps(asdict(attempt), separators=(",", ":"))


def _load(raw: str | bytes) -> Attempt:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("ticket record is not an object")
        ticket = data["ticket"]
        uin = data.get("uin")
        registration_id = data.get("registration_id")
        credential_ticket = data.get("credential_ticket")
        consumed = data.get("consumed", False)
        credential_used = data.get("credential_used", False)
        if not isinstance(ticket, str):
            raise TypeError("ticket token is not a string")
        if uin is not None and not isinstance(uin, str):
            raise TypeError("uin is not a string")
        if registration_id is not None and not isinstance(registration_id, str):
            raise TypeError("registration id is not a string")
        if credential_ticket is not None and not isinstance(credential_ticket, str):
            raise TypeError("credential ticket is not a string")
        if not isinstance(consumed, bool) or not isinstance(credential_used, bool):
            raise TypeError("ticket flags are not booleans")
        return Attempt(
            ticket=ticket,
            expires_at=float(data["expires_at"]),
            uin=uin,
            registration_id=registration_id,
            consumed=consumed,
            credential_ticket=credential_ticket,
            credential_expires=float(data.get("credential_expires") or 0.0),
            credential_used=credential_used,
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise EnrollTicketUnavailable(_UNAVAILABLE) from exc


def _redis_url() -> str | None:
    raw = os.getenv("REDIS_URL")
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _redis_client() -> Any | None:
    url = _redis_url()
    if url is None:
        return None
    try:
        import redis
    except ImportError as exc:
        raise EnrollTicketUnavailable(_UNAVAILABLE) from exc
    try:
        return redis.Redis.from_url(
            url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
            retry_on_timeout=False,
        )
    except Exception as exc:
        if _is_store_outage(exc):
            raise EnrollTicketUnavailable(_UNAVAILABLE) from exc
        raise


def _close_client(client: Any | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        logger.debug("Enrolment ticket Redis client close failed")


def _call(operation: Any) -> Any:
    try:
        return operation()
    except EnrollTicketUnavailable:
        raise
    except Exception as exc:
        if _is_store_outage(exc):
            raise EnrollTicketUnavailable(_UNAVAILABLE) from exc
        raise


def _is_store_outage(exc: BaseException) -> bool:
    try:
        from redis.exceptions import RedisError
    except ImportError:
        return isinstance(exc, OSError)
    return isinstance(exc, (RedisError, OSError))
