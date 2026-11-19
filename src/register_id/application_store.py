"""
Draft applications shared by every app process.

``get_application_store`` selects the backend from ``REDIS_URL``:

* unset or blank: ``MemoryApplicationStore`` (one process, gone on restart)
* set: ``RedisApplicationStore`` (shared, survives restart)

A configured Redis that cannot be reached raises ``ApplicationStoreError``.
There is no silent fallback to process memory. Payloads are not logged.

Redis stores the application record as a Fernet token. The key is
``APPLICATION_STORE_KEY`` (url-safe Fernet key), not ``DJANGO_SECRET_KEY``.
A missing or invalid key raises ``ApplicationStoreError`` before any write.
``MemoryApplicationStore`` keeps plaintext dicts; it is process-local and is
used only when ``REDIS_URL`` is unset. The key, the token, and demographic
fields are never logged.

A draft application is not a citizen identity.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

_RECORD_PREFIX = "register-id:application:"
_CODE_PREFIX = "register-id:application-code:"
# Keep the key past logical expiry so a late read can still see the record.
_GRACE_SECONDS = 60
_REDIS_TIMEOUT_SECONDS = 2.0


class ApplicationStoreError(RuntimeError):
    """Redis cannot be reached, the Fernet key is missing or invalid, or a code cannot be issued."""


class ApplicationStore(Protocol):
    def save(
        self,
        record: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> bool:
        """
        Store ``record`` when its code is free.

        Return False when that code is already stored. The record carries its
        own ``createdAt`` and ``expiresAt``.
        """

    def load(self, application_id: str) -> dict[str, Any] | None:
        """Return the stored draft, or None when it is absent."""


def _copy(record: dict[str, Any]) -> dict[str, Any]:
    stored = dict(record)
    consent = stored.get("consent")
    if isinstance(consent, dict):
        stored["consent"] = dict(consent)
    return stored


class MemoryApplicationStore:
    """In-process drafts. Each instance has its own maps."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, str] = {}
        self._lock = threading.Lock()

    def save(
        self,
        record: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> bool:
        del ttl_seconds
        clock = time.time() if now is None else now
        code = str(record["code"])
        guid = str(record["id"])
        with self._lock:
            self._prune(clock)
            if code in self.codes:
                return False
            self.codes[code] = guid
            self.records[guid] = _copy(record)
            return True

    def _prune(self, now: float) -> None:
        stale = [
            guid
            for guid, record in self.records.items()
            if float(record.get("expiresAt", 0)) < now - _GRACE_SECONDS
        ]
        for guid in stale:
            record = self.records.pop(guid, None)
            if record is not None:
                self.codes.pop(str(record.get("code")), None)

    def load(self, application_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(application_id)
            if record is None:
                return None
            return _copy(record)


def _fernet_from_environment() -> Fernet:
    """Build a Fernet from APPLICATION_STORE_KEY. Never include the key in errors."""
    raw = os.environ.get("APPLICATION_STORE_KEY", "").strip()
    if not raw:
        raise ApplicationStoreError(
            "APPLICATION_STORE_KEY is required when applications are stored in Redis."
        )
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        raise ApplicationStoreError(
            "APPLICATION_STORE_KEY is not a valid Fernet key."
        ) from None


class RedisApplicationStore:
    """Redis-backed drafts. Keys expire on their own."""

    def __init__(self, url: str | None = None, *, client: Any = None) -> None:
        # Fail closed before a client exists, so a bad key cannot write plaintext.
        self._fernet = _fernet_from_environment()
        if client is not None:
            self._client = client
            return
        if not url:
            raise ApplicationStoreError("REDIS_URL is configured but empty.")
        import redis

        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )

    def save(
        self,
        record: dict[str, Any],
        ttl_seconds: float,
        now: float | None = None,
    ) -> bool:
        del now
        code = str(record["code"])
        guid = str(record["id"])
        encoded = json.dumps(_copy(record), separators=(",", ":")).encode()
        token = self._fernet.encrypt(encoded).decode()
        ttl = max(1, math.ceil(ttl_seconds + _GRACE_SECONDS))

        def _write() -> bool:
            placed = self._client.set(_code_key(code), guid, ex=ttl, nx=True)
            if not placed:
                return False
            self._client.set(_record_key(guid), token, ex=ttl)
            return True

        return self._call("save", _write)

    def load(self, application_id: str) -> dict[str, Any] | None:
        def _read() -> dict[str, Any] | None:
            raw = self._client.get(_record_key(application_id))
            if raw is None:
                return None
            token = raw if isinstance(raw, bytes) else str(raw).encode()
            try:
                payload = self._fernet.decrypt(token)
            except InvalidToken:
                raise ApplicationStoreError("Application record could not be read.") from None
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                raise ApplicationStoreError("Application record could not be read.") from None
            if not isinstance(decoded, dict):
                raise ApplicationStoreError("Application record could not be read.")
            return decoded

        return self._call("load", _read)

    def _call(self, operation: str, fn: Any) -> Any:
        try:
            return fn()
        except (RedisConnectionError, RedisTimeoutError) as exc:
            raise ApplicationStoreError(
                f"Application store cannot reach Redis during {operation}. "
                "REDIS_URL is configured, so applications are not kept in process memory."
            ) from exc


def _record_key(application_id: str) -> str:
    return f"{_RECORD_PREFIX}{application_id}"


def _code_key(code: str) -> str:
    return f"{_CODE_PREFIX}{code}"


_MEMORY = MemoryApplicationStore()
_REDIS: dict[str, RedisApplicationStore] = {}


def in_memory_records() -> dict[str, dict[str, Any]]:
    """The singleton memory map. Unused when REDIS_URL selects Redis."""
    return _MEMORY.records


def get_application_store() -> ApplicationStore:
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return _MEMORY
    store = _REDIS.get(url)
    if store is None:
        store = RedisApplicationStore(url)
        _REDIS[url] = store
    return store
