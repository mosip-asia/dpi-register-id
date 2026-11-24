"""
Short-lived grants that let a citizen read their own identity checks.

A grant lasts 12 hours. Only the sha256 hex digest of the token is stored.
The plaintext token is returned once from ``issue_grant`` and is never written
here again. This file is not an audit log.

Storage follows the process environment unless a caller injects a store or a directory:
- REDIS_URL set: one JSON object at the Redis key ``register-id:activity-grants``.
  A down Redis raises. There is no silent file fallback, including when
  ``FILE_STORE=1`` is also set.
- REDIS_URL unset: raise. The process does not create or write
  ``activity-grants.json``. ``FILE_STORE=1`` is an explicit opt-in that writes
  JSON under LOG_DIR, or under a directory in the system temp dir when LOG_DIR
  is unset.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

REDIS_ACTIVITY_GRANTS_KEY = "register-id:activity-grants"
GRANT_TTL_SECONDS = 12 * 60 * 60
_GRANTS_FILENAME = "activity-grants.json"
_file_lock = threading.Lock()
_directory_lock = threading.Lock()


class ActivityGrantStore(Protocol):
    """One JSON object of token digest to grant."""

    def load(self) -> dict[str, Any]: ...

    def save(self, grants: dict[str, Any]) -> None: ...


def issue_grant(
    uin: str,
    *,
    store: ActivityGrantStore | None = None,
    path: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> str:
    """Return a new plaintext token for this citizen. Only its hash is stored."""
    subject = _require_uin(uin)
    issued_at = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    digest = _hash_token(token)

    def mutate(grants: dict[str, Any]) -> str:
        live = _without_expired(grants, issued_at)
        grants.clear()
        grants.update(live)
        grants[digest] = {"uin": subject, "expiresAt": issued_at + GRANT_TTL_SECONDS}
        return token

    return _update(store, path, mutate)


def resolve_grant(
    token: str,
    *,
    store: ActivityGrantStore | None = None,
    path: str | os.PathLike[str] | None = None,
    now: float | None = None,
) -> str | None:
    """Return the citizen UIN for a live grant, or None. Expired grants are dropped."""
    if not isinstance(token, str) or not token:
        return None
    digest = _hash_token(token)
    clock = time.time() if now is None else now

    def mutate(grants: dict[str, Any]) -> str | None:
        live = _without_expired(grants, clock)
        grants.clear()
        grants.update(live)
        row = live.get(digest)
        if row is None:
            return None
        return str(row["uin"])

    return _update(store, path, mutate)


class FileActivityGrantStore:
    """One JSON object at ``directory / activity-grants.json``."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.file_path = self.directory / _GRANTS_FILENAME

    def load(self) -> dict[str, Any]:
        with _file_lock:
            if not self.file_path.is_file():
                return {}
            text = self.file_path.read_text(encoding="utf-8")
        return _parse_grants(text)

    def save(self, grants: dict[str, Any]) -> None:
        payload = json.dumps(grants, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with _file_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.file_path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.file_path)


class RedisActivityGrantStore:
    """The grant map as one JSON string at ``register-id:activity-grants``."""

    def __init__(self, url: str) -> None:
        if not url or not str(url).strip():
            raise ValueError("Redis activity grant URL is empty")
        self.url = str(url).strip()

    def load(self) -> dict[str, Any]:
        client = self._connect()
        try:
            raw = client.get(REDIS_ACTIVITY_GRANTS_KEY)
        finally:
            client.close()
        if raw is None:
            return {}
        return _parse_grants(_decode_redis_value(raw))

    def save(self, grants: dict[str, Any]) -> None:
        payload = json.dumps(grants, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        client = self._connect()
        try:
            client.set(REDIS_ACTIVITY_GRANTS_KEY, payload)
        finally:
            client.close()

    def _connect(self) -> Any:
        import redis

        return redis.Redis.from_url(
            self.url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )


def _open_store(
    store: ActivityGrantStore | None,
    path: str | os.PathLike[str] | None,
) -> ActivityGrantStore:
    if store is not None and path is not None:
        raise ValueError("pass store or path, not both")
    if store is not None:
        return store
    if path is not None:
        return FileActivityGrantStore(path)
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        _require_redis_url(redis_url)
        return RedisActivityGrantStore(redis_url)
    if os.environ.get("FILE_STORE", "").strip() == "1":
        return _file_store_from_env()
    raise RuntimeError("REDIS_URL is required for activity grants")


def _file_store_from_env() -> FileActivityGrantStore:
    """File store selected only by ``FILE_STORE=1``."""
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if log_dir:
        return FileActivityGrantStore(log_dir)
    return FileActivityGrantStore(Path(tempfile.gettempdir()) / "register-id")


def _require_redis_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use the redis or rediss scheme")
    if parts.hostname is None:
        raise ValueError("REDIS_URL is missing a host")


def _update(
    store: ActivityGrantStore | None,
    path: str | os.PathLike[str] | None,
    mutate: Callable[[dict[str, Any]], Any],
) -> Any:
    backend = _open_store(store, path)
    with _directory_lock:
        grants = _normalize(backend.load())
        result = mutate(grants)
        backend.save(grants)
        return result


def _normalize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("corrupt activity grants")
    return dict(raw)


def _parse_grants(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("corrupt activity grants") from None
    if not isinstance(payload, dict):
        raise ValueError("corrupt activity grants")
    return payload


def _without_expired(grants: dict[str, Any], now: float) -> dict[str, Any]:
    live: dict[str, Any] = {}
    for digest, row in grants.items():
        if not isinstance(digest, str) or len(digest) != 64:
            continue
        if not isinstance(row, dict):
            continue
        uin = row.get("uin")
        expires_at = row.get("expiresAt")
        if not isinstance(uin, str) or not uin:
            continue
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            continue
        expires = float(expires_at)
        if expires != expires or expires in (float("inf"), float("-inf")):
            continue
        if expires <= now:
            continue
        live[digest] = {"uin": uin, "expiresAt": expires}
    return live


def _require_uin(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("uin must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("uin must be non-empty")
    return cleaned


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _decode_redis_value(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode("utf-8")
    if isinstance(item, str):
        return item
    raise ValueError("corrupt activity grants")
