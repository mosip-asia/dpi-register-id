"""
Single-use expiring challenges shared by every app process.

``get_challenge_store`` selects the backend from ``REDIS_URL``:

* unset or blank: ``MemoryChallengeStore`` (one process, gone on restart)
* set: ``RedisChallengeStore`` (shared, survives restart)

A configured Redis that cannot be reached raises ``ChallengeStoreError``.
There is no silent fallback to process memory. Payloads are not logged.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

_PREFIX = "register-id:challenge:"
# Keep the key past logical expiry so a late consume can still report "expired"
# instead of looking like an id that never existed. Matches the old prune window.
_GRACE_SECONDS = 60
_REDIS_TIMEOUT_SECONDS = 2.0

ConsumeReason = Literal["ok", "missing", "expired"]


class ChallengeStoreError(RuntimeError):
    """REDIS_URL is set, but Redis cannot be reached."""


@dataclass(frozen=True)
class ConsumeResult:
    ok: bool
    reason: ConsumeReason
    record: dict[str, Any] | None = None


class ChallengeStore(Protocol):
    def issue(
        self,
        challenge_id: str,
        payload: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> None:
        """Store a new challenge that expires ``ttl_seconds`` after ``now``."""

    def consume(self, challenge_id: str, now: float | None = None) -> ConsumeResult:
        """
        Take the challenge once.

        A second consume fails. An expired challenge is taken and fails.
        A missing id fails.
        """

    def peek(self, challenge_id: str) -> dict[str, Any] | None:
        """Return the stored record without consuming it."""


def _stamp(payload: dict[str, Any], ttl_seconds: float, now: float) -> dict[str, Any]:
    record = dict(payload)
    record["createdAt"] = record.get("createdAt", now)
    record["expiresAt"] = now + ttl_seconds
    return record


class MemoryChallengeStore:
    """In-process challenges. Each instance has its own map."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        challenge_id: str,
        payload: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> None:
        clock = time.time() if now is None else now
        record = _stamp(payload, ttl_seconds, clock)
        with self._lock:
            self._prune(clock)
            self.records[challenge_id] = record

    def consume(self, challenge_id: str, now: float | None = None) -> ConsumeResult:
        clock = time.time() if now is None else now
        with self._lock:
            record = self.records.pop(challenge_id, None)
            return _judge(record, clock)

    def peek(self, challenge_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(challenge_id)
            if record is None:
                return None
            return dict(record)

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, record in self.records.items()
            if float(record.get("expiresAt", 0)) < now - _GRACE_SECONDS
        ]
        for key in stale:
            self.records.pop(key, None)


def _judge(record: dict[str, Any] | None, now: float) -> ConsumeResult:
    if record is None:
        return ConsumeResult(ok=False, reason="missing", record=None)
    if now > float(record["expiresAt"]):
        return ConsumeResult(ok=False, reason="expired", record=dict(record))
    return ConsumeResult(ok=True, reason="ok", record=dict(record))


class RedisChallengeStore:
    """Redis-backed challenges. Keys expire on their own."""

    def __init__(self, url: str | None = None, *, client: Any = None) -> None:
        if client is not None:
            self._client = client
            return
        if not url:
            raise ChallengeStoreError("REDIS_URL is configured but empty.")
        import redis

        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )

    def issue(
        self,
        challenge_id: str,
        payload: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> None:
        clock = time.time() if now is None else now
        record = _stamp(payload, ttl_seconds, clock)
        key = _key(challenge_id)
        encoded = json.dumps(record, separators=(",", ":"))
        ttl = max(1, math.ceil(ttl_seconds + _GRACE_SECONDS))
        self._call("issue", lambda: self._client.set(key, encoded, ex=ttl))

    def consume(self, challenge_id: str, now: float | None = None) -> ConsumeResult:
        clock = time.time() if now is None else now
        raw = self._call("consume", lambda: self._client.getdel(_key(challenge_id)))
        if not raw:
            return ConsumeResult(ok=False, reason="missing", record=None)
        return _judge(_decode(raw), clock)

    def peek(self, challenge_id: str) -> dict[str, Any] | None:
        raw = self._call("peek", lambda: self._client.get(_key(challenge_id)))
        if not raw:
            return None
        return _decode(raw)

    def _call(self, operation: str, fn: Any) -> Any:
        try:
            return fn()
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise ChallengeStoreError(
                f"Challenge store cannot reach Redis during {operation}. "
                "REDIS_URL is configured, so challenges are not kept in process memory."
            ) from exc


def _key(challenge_id: str) -> str:
    return f"{_PREFIX}{challenge_id}"


def _decode(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ChallengeStoreError("Challenge record in Redis is not an object.")
    return loaded


_MEMORY = MemoryChallengeStore()
_REDIS: dict[str, RedisChallengeStore] = {}


def in_memory_records() -> dict[str, dict[str, Any]]:
    """The singleton memory map. Unused when REDIS_URL selects Redis."""
    return _MEMORY.records


def get_challenge_store() -> ChallengeStore:
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return _MEMORY
    store = _REDIS.get(url)
    if store is None:
        store = RedisChallengeStore(url)
        _REDIS[url] = store
    return store
