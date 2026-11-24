"""
UIN lock flags for the citizen portal.

A locked UIN is rejected at face check. This store holds only UIN strings.
It does not store faces, descriptors, passwords, or tokens, and it does not
write the audit log.

Storage follows the process environment unless a test injects a store or a directory:
- REDIS_URL set: one JSON string at the Redis key ``register-id:locks``.
  A down Redis raises. There is no silent file fallback, including when
  ``FILE_STORE=1`` is also set.
- REDIS_URL unset: raise. The process does not create or write ``locks.json``.
  ``FILE_STORE=1`` is an explicit opt-in that writes JSON under
  LOG_DIR, or under a directory in the system temp dir when LOG_DIR is unset.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

REDIS_LOCKS_KEY = "register-id:locks"
_LOCKS_FILENAME = "locks.json"
_MAX_UIN = 64
_file_lock = threading.Lock()
_directory_lock = threading.Lock()


class LockStore(Protocol):
    """Set of locked UINs."""

    def load(self) -> list[str]: ...

    def save(self, locked: list[str]) -> None: ...


def is_locked(
    uin: str,
    *,
    store: LockStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    """True when ``uin`` is in the lock set."""
    target = _clean_uin(uin)
    if not target:
        return False
    return target in _read(store, path)


def set_locked(
    uin: str,
    locked: bool,
    *,
    store: LockStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Add or remove ``uin``. A false flag removes it. The audit log is untouched."""
    target = _clean_uin(uin)
    if not target:
        raise ValueError("uin must be non-empty")
    if not isinstance(locked, bool):
        raise ValueError("locked must be a boolean")

    def mutate(items: list[str]) -> None:
        if locked:
            if target not in items:
                items.append(target)
            return
        if target in items:
            items.remove(target)

    _update(store, path, mutate)


class FileLockStore:
    """One JSON document at ``directory / locks.json``."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.file_path = self.directory / _LOCKS_FILENAME

    def load(self) -> list[str]:
        with _file_lock:
            if not self.file_path.is_file():
                return []
            text = self.file_path.read_text(encoding="utf-8")
        return _parse_locks(text)

    def save(self, locked: list[str]) -> None:
        payload = _dump_locks(locked)
        with _file_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.file_path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.file_path)


class RedisLockStore:
    """The lock set as one JSON string at ``register-id:locks``."""

    def __init__(self, url: str) -> None:
        if not url or not str(url).strip():
            raise ValueError("Redis locks URL is empty")
        self.url = str(url).strip()

    def load(self) -> list[str]:
        client = self._connect()
        try:
            raw = client.get(REDIS_LOCKS_KEY)
        finally:
            client.close()
        if raw is None:
            return []
        return _parse_locks(_decode_redis_value(raw))

    def save(self, locked: list[str]) -> None:
        payload = _dump_locks(locked)
        client = self._connect()
        try:
            client.set(REDIS_LOCKS_KEY, payload)
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
    store: LockStore | None,
    path: str | os.PathLike[str] | None,
) -> LockStore:
    if store is not None and path is not None:
        raise ValueError("pass store or path, not both")
    if store is not None:
        return store
    if path is not None:
        return FileLockStore(path)
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        _require_redis_url(redis_url)
        return RedisLockStore(redis_url)
    if os.environ.get("FILE_STORE", "").strip() == "1":
        return _file_store_from_env()
    raise RuntimeError("REDIS_URL is required for the lock set")


def _file_store_from_env() -> FileLockStore:
    """File store selected only by ``FILE_STORE=1``."""
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if log_dir:
        return FileLockStore(log_dir)
    return FileLockStore(Path(tempfile.gettempdir()) / "register-id")


def _require_redis_url(url: str) -> None:
    """Reject a URL that would silently target something other than Redis."""
    parts = urlsplit(url)
    if parts.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use the redis or rediss scheme")
    if parts.hostname is None:
        raise ValueError("REDIS_URL is missing a host")


def _read(
    store: LockStore | None,
    path: str | os.PathLike[str] | None,
) -> list[str]:
    backend = _open_store(store, path)
    with _directory_lock:
        return _normalize(backend.load())


def _update(
    store: LockStore | None,
    path: str | os.PathLike[str] | None,
    mutate: Callable[[list[str]], None],
) -> None:
    backend = _open_store(store, path)
    with _directory_lock:
        items = _normalize(backend.load())
        mutate(items)
        backend.save(items)


def _normalize(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("corrupt lock set")
    locked: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("corrupt lock set")
        uin = _clean_uin(item)
        if not uin:
            raise ValueError("corrupt lock set")
        if uin not in locked:
            locked.append(uin)
    return locked


def _parse_locks(text: str) -> list[str]:
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("corrupt lock set") from None
    if not isinstance(payload, list):
        raise ValueError("corrupt lock set")
    return payload


def _dump_locks(locked: list[str]) -> str:
    stored = _normalize(locked)
    return json.dumps(stored, ensure_ascii=False, separators=(",", ":"))


def _clean_uin(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _MAX_UIN:
        return ""
    return cleaned


def _decode_redis_value(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode("utf-8")
    if isinstance(item, str):
        return item
    raise ValueError("corrupt lock set")
