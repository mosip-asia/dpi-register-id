"""
Audit trail for enrollment and credential-issue attempts.

Each record stores kind, actor, uin, timestamp, result, and a short detail.
Face images, embeddings, CBEFF payloads, passwords, and tokens are never written.

Storage follows the process environment unless a test injects a store or a directory:
- REDIS_URL set: append to the Redis list ``register-id:audit`` and read it back.
  A down Redis raises. There is no silent file fallback.
- REDIS_URL unset: append JSON lines under LOG_DIR, or under a directory in the
  system temp dir when LOG_DIR is unset.

``list_events`` returns records in append order: oldest first, newest last.
A limit keeps the newest records and preserves that order.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

REDIS_AUDIT_KEY = "register-id:audit"
_AUDIT_FILENAME = "audit.jsonl"
_KINDS = frozenset({"enroll", "credential", "authenticate", "operator"})
_RESULTS = frozenset({"success", "failure"})
_FIELDS = ("kind", "actor", "uin", "timestamp", "result", "detail")
# Matched against keys with underscores and hyphens removed, case-insensitive.
_FORBIDDEN_MARKERS = (
    "password",
    "faceimage",
    "image",
    "embedding",
    "cbeff",
    "authorization",
    "token",
)
_MAX_ACTOR = 128
_MAX_UIN = 64
_MAX_DETAIL = 240
_MAX_DEPTH = 12
_file_lock = threading.Lock()


class AuditStore(Protocol):
    """Line store. ``read`` returns append order, honoring ``limit`` from the tail."""

    def append(self, line: str) -> None: ...

    def read(self, limit: int | None = None) -> list[str]: ...


def record_event(
    event: Mapping[str, Any],
    *,
    store: AuditStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """
    Append one enroll or credential attempt and return the stored record.

    ``event`` must carry kind, actor, uin, and result. timestamp defaults to
    the current unix time. detail defaults to an empty string.

    Mappings that contain a secret key (password, faceImage, image, embedding,
    cbeff, authorization, token, including nested keys) are rejected and not
    written. Any other extra key is omitted. Binary values are rejected.
    """
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    _reject_forbidden(event)
    record = _build_record(event)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    _open_store(store, path).append(line)
    return dict(record)


def list_events(
    limit: int | None = None,
    *,
    store: AuditStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return stored audit records, oldest first and newest last.

    ``limit`` keeps the newest ``limit`` records. ``None`` returns the whole log.
    """
    _check_limit(limit)
    lines = _open_store(store, path).read(limit)
    return [_project_line(line) for line in lines]


class FileAuditStore:
    """JSON lines in ``directory / audit.jsonl``. A new process can read the file."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.file_path = self.directory / _AUDIT_FILENAME

    def append(self, line: str) -> None:
        if "\n" in line or "\r" in line:
            raise ValueError("audit line must be a single line")
        with _file_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def read(self, limit: int | None = None) -> list[str]:
        _check_limit(limit)
        with _file_lock:
            if not self.file_path.is_file():
                return []
            text = self.file_path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.strip()]
        if limit is None:
            return lines
        if limit == 0:
            return []
        return lines[-limit:]


class RedisAuditStore:
    """Append-only Redis list. The list, not this process, holds the log."""

    def __init__(self, url: str) -> None:
        if not url or not str(url).strip():
            raise ValueError("Redis audit URL is empty")
        self.url = str(url).strip()

    def append(self, line: str) -> None:
        client = self._connect()
        try:
            client.rpush(REDIS_AUDIT_KEY, line)
        finally:
            client.close()

    def read(self, limit: int | None = None) -> list[str]:
        _check_limit(limit)
        client = self._connect()
        try:
            if limit == 0:
                return []
            if limit is None:
                raw = client.lrange(REDIS_AUDIT_KEY, 0, -1)
            else:
                raw = client.lrange(REDIS_AUDIT_KEY, -limit, -1)
        finally:
            client.close()
        return [_decode_redis_value(item) for item in raw]

    def _connect(self) -> Any:
        import redis

        return redis.Redis.from_url(
            self.url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )


def _open_store(
    store: AuditStore | None,
    path: str | os.PathLike[str] | None,
) -> AuditStore:
    if store is not None and path is not None:
        raise ValueError("pass store or path, not both")
    if store is not None:
        return store
    if path is not None:
        return FileAuditStore(path)
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        _require_redis_url(redis_url)
        return RedisAuditStore(redis_url)
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if log_dir:
        return FileAuditStore(log_dir)
    return FileAuditStore(Path(tempfile.gettempdir()) / "register-id")


def _require_redis_url(url: str) -> None:
    """Reject a URL that would silently target something other than Redis."""
    parts = urlsplit(url)
    if parts.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use the redis or rediss scheme")
    if parts.hostname is None:
        raise ValueError("REDIS_URL is missing a host")


def _build_record(event: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in ("kind", "actor", "uin", "result") if field not in event]
    if missing:
        raise ValueError(f"audit event is missing {', '.join(missing)}")

    kind = _require_token(event["kind"], "kind", _KINDS)
    result = _require_token(event["result"], "result", _RESULTS)
    actor = _require_text(event["actor"], "actor", _MAX_ACTOR, allow_empty=False)
    uin = _require_text(event["uin"], "uin", _MAX_UIN, allow_empty=False)
    if "detail" in event and event["detail"] is not None:
        detail = _require_text(event["detail"], "detail", _MAX_DETAIL, allow_empty=True)
    else:
        detail = ""
    timestamp = _require_timestamp(event.get("timestamp"))
    return {
        "kind": kind,
        "actor": actor,
        "uin": uin,
        "timestamp": timestamp,
        "result": result,
        "detail": detail,
    }


def _require_token(value: Any, field: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if cleaned not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ValueError(f"{field} must be one of: {allowed_list}")
    return cleaned


def _require_text(value: Any, field: str, max_len: int, *, allow_empty: bool) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("audit event rejected: binary payload")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValueError(f"{field} must be non-empty")
    if len(cleaned) > max_len:
        raise ValueError(f"{field} is too long")
    return cleaned


def _require_timestamp(value: Any) -> float:
    if value is None:
        import time

        value = time.time()
    # bool is an int subclass and is not a unix time.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timestamp must be a unix time")
    timestamp = float(value)
    if timestamp != timestamp or timestamp in (float("inf"), float("-inf")):
        raise ValueError("timestamp must be a finite unix time")
    return timestamp


def _reject_forbidden(value: Any, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("audit event rejected: nesting is too deep")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("audit event rejected: binary payload")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _key_is_forbidden(key):
                raise ValueError(f"audit event rejected: forbidden field {key!r}")
            _reject_forbidden(child, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _reject_forbidden(child, depth + 1)


def _key_is_forbidden(key: Any) -> bool:
    normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
    return any(marker in normalized for marker in _FORBIDDEN_MARKERS)


def _project_line(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("corrupt audit record") from exc
    if not isinstance(payload, dict):
        raise ValueError("corrupt audit record")
    if _mapping_has_forbidden_key(payload):
        raise ValueError("corrupt audit record")
    missing = [field for field in _FIELDS if field not in payload]
    if missing:
        raise ValueError("corrupt audit record")
    record = _build_record(payload)
    return record


def _mapping_has_forbidden_key(value: Any, depth: int = 0) -> bool:
    if depth > _MAX_DEPTH:
        return True
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _key_is_forbidden(key) or _mapping_has_forbidden_key(child, depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_mapping_has_forbidden_key(child, depth + 1) for child in value)
    return False


def _decode_redis_value(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode("utf-8")
    if isinstance(item, str):
        return item
    raise ValueError("corrupt audit record")


def _check_limit(limit: int | None) -> None:
    if limit is None:
        return
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
