"""
Hourly cap on successful enrollment writes.

The enroll route passes the citizen email. Each email has its own window, so
one person's enrollments do not use up another person's cap.

``get_enroll_limiter`` selects the backend from ``REDIS_URL``:

* unset or blank: process memory (one process, gone on restart)
* set: Redis, one counter key per subject

A configured Redis that cannot be reached raises ``EnrollLimitUnavailable``.
There is no silent fallback to process memory, and the limit is not skipped.

The Redis key gets ``EXPIRE`` when the first success opens the window. That
TTL is the bound. This is not a per-event audit log.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Protocol

from redis.exceptions import RedisError

# Successful IDRepo writes allowed for one subject during the window below.
ENROLL_SUCCESS_LIMIT = 30
ENROLL_LIMIT_WINDOW_SECONDS = 60 * 60

_KEY_PREFIX = "register-id:enroll-limit:"
_REDIS_TIMEOUT_SECONDS = 2.0


class EnrollLimitExceeded(Exception):
    """This token already has ENROLL_SUCCESS_LIMIT successful writes in the window."""


class EnrollLimitUnavailable(Exception):
    """REDIS_URL is set, but the enrollment counter cannot be used."""


class EnrollLimiter(Protocol):
    def writes_in_window(self, token: str, now: float | None = None) -> int:
        """Successful writes still inside the current window."""

    def record(self, token: str, now: float | None = None) -> None:
        """Count one successful IDRepo write."""


def _bucket_id(token: str) -> str:
    """Stable id for the token. The raw token is not the stored key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _Bucket:
    def __init__(self, count: int, started: float) -> None:
        self.count = count
        self.started = started


class MemoryEnrollLimiter:
    """In-process counters. Each token has its own window."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def writes_in_window(self, token: str, now: float | None = None) -> int:
        clock = time.time() if now is None else now
        with self._lock:
            bucket = self._live(_bucket_id(token), clock)
            if bucket is None:
                return 0
            return bucket.count

    def record(self, token: str, now: float | None = None) -> None:
        clock = time.time() if now is None else now
        with self._lock:
            key = _bucket_id(token)
            bucket = self._live(key, clock)
            if bucket is None:
                self._buckets[key] = _Bucket(1, clock)
                return
            bucket.count += 1

    def _live(self, key: str, now: float) -> _Bucket | None:
        bucket = self._buckets.get(key)
        if bucket is None:
            return None
        if now - bucket.started >= ENROLL_LIMIT_WINDOW_SECONDS:
            self._buckets.pop(key, None)
            return None
        return bucket


class RedisEnrollLimiter:
    """One Redis counter per token. EXPIRE on that key is the window."""

    def __init__(self, url: str | None = None, *, client: Any = None) -> None:
        if client is not None:
            self._client = client
            return
        if not url:
            raise EnrollLimitUnavailable("REDIS_URL is configured but empty.")
        import redis

        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )

    def writes_in_window(self, token: str, now: float | None = None) -> int:
        del now
        raw = self._call("read", lambda: self._client.get(_redis_key(token)))
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise EnrollLimitUnavailable("Enrollment limit store is unavailable.") from exc

    def record(self, token: str, now: float | None = None) -> None:
        del now
        key = _redis_key(token)

        def _incr() -> None:
            count = int(self._client.incr(key))
            # The first success opens the window. Later writes must not
            # refresh the TTL, or a steady caller would never hit the bound.
            if count == 1:
                self._client.expire(key, ENROLL_LIMIT_WINDOW_SECONDS)

        self._call("record", _incr)

    def _call(self, operation: str, fn: Any) -> Any:
        try:
            return fn()
        except RedisError as exc:
            raise EnrollLimitUnavailable(
                "Enrollment limit store is unavailable. "
                f"REDIS_URL is configured, so the {operation} was not skipped."
            ) from exc


def _redis_key(token: str) -> str:
    return f"{_KEY_PREFIX}{_bucket_id(token)}"


_MEMORY = MemoryEnrollLimiter()
_REDIS: dict[str, RedisEnrollLimiter] = {}


def reset_enroll_limits() -> None:
    """Drop process-memory buckets and cached Redis clients."""
    _MEMORY.reset()
    _REDIS.clear()


def get_enroll_limiter() -> EnrollLimiter:
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return _MEMORY
    limiter = _REDIS.get(url)
    if limiter is None:
        limiter = RedisEnrollLimiter(url)
        _REDIS[url] = limiter
    return limiter


def enroll_success_limit() -> int:
    """Successful writes allowed for one ticket or client during the window."""
    raw = os.getenv("ENROLL_SUCCESS_LIMIT", "").strip()
    if not raw:
        return ENROLL_SUCCESS_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return ENROLL_SUCCESS_LIMIT
    return min(max(value, 1), 10000)


def ensure_enroll_allowed(token: str, now: float | None = None) -> None:
    """Raise when this subject is already at the configured cap in the window."""
    if get_enroll_limiter().writes_in_window(token, now) >= enroll_success_limit():
        raise EnrollLimitExceeded()


def record_enroll_success(token: str, now: float | None = None) -> None:
    """Count one successful IDRepo write. Validation failures must not call this."""
    get_enroll_limiter().record(token, now)
