"""
One audit log for enrollment, credential, camera, and dispute attempts.

The log is the Redis list ``register-id:audit`` or the file ``audit.jsonl``.
Activity rows last 30 days (``AUDIT_RETENTION_SECONDS``). Permanent rows stay
in that same log. Images, embeddings, passwords, and tokens are never written.

Activity is the default when ``retention`` is omitted or is ``activity``. On
append and on read, an activity row older than 30 days is removed from the
Redis list and from ``audit.jsonl``, including a row that is already expired
when it is written. A lone expired activity write therefore leaves no UIN
behind, and ``list_events`` does not return it. A permanent row is written
even when its timestamp is already older than 30 days, and append and read
leave it in place. ``list_events`` returns those permanent rows together with
activity rows that are still inside the window.

The Redis key itself has no TTL: an ``EXPIRE`` refreshed by every append would
keep a busy log forever, and a quiet log would delete fresh rows with the old
ones.

Storage follows the process environment unless a caller injects a store or a directory:
- REDIS_URL set: append to the Redis list ``register-id:audit`` and read it back.
  A down Redis raises. There is no silent file fallback, including when
  ``AUDIT_BACKEND=file`` is also set.
- REDIS_URL unset: raise. The process does not create or append ``audit.jsonl``.
  ``AUDIT_BACKEND=file`` is an explicit opt-in that writes JSON lines under
  LOG_DIR, or under a directory in the system temp dir when LOG_DIR is unset.

``list_events`` returns records in append order: oldest first, newest last.
A limit keeps the newest records and preserves that order.
"""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from register_id.reasons import CODES, TRY_CODES, citizen_message, rough_device

REDIS_AUDIT_KEY = "register-id:audit"
# Activity rows only. Permanent rows stay in the same log.
AUDIT_RETENTION_SECONDS = 30 * 24 * 60 * 60
REASON_CODES = frozenset(
    {
        "liveness_failed",
        "face_mismatch",
        "no_face_template",
        "bad_descriptor",
        "unknown_uin",
        "sweep_rejected",
        "enroll_failed",
        "enroll_write_failed",
        "camera_unavailable",
        "camera_quality",
        "rate_limited",
    }
)
ACTION_CODES = frozenset(
    {
        "demographics",
        "login",
        "delete_face",
        "add_staff",
        "remove_staff",
        "set_role",
        "not_me",
    }
)
EVENTS = frozenset(
    {
        "details_saved",
        "camera",
        "enroll",
        "authenticate",
        "activity_reported",
        "notification_sent",
        "report_opened",
        "uin_locked",
        "uin_unlocked",
        "details_corrected",
        "login_on",
        "login_off",
        "face_removed",
        "role_changed",
        "marked_checked",
        "retention_changed",
    }
)
_AUDIT_FILENAME = "audit.jsonl"
_KINDS = frozenset({"enroll", "credential", "authenticate", "operator", "camera", "dispute"})
_RESULTS = frozenset({"success", "failure"})
_RETENTIONS = frozenset({"activity", "permanent"})
_FIELDS = ("kind", "actor", "uin", "timestamp", "result", "detail")
_MAX_CHECK_ID = 64
_MAX_EVENT_ID = 64
_MAX_APP_CODE = 16
_MAX_SESSION_ID = 64
_MAX_SOURCE = 120
_MAX_SERVICE = 32
_MAX_REQUEST_ID = 64
_MAX_NETWORK = 64
_MAX_BROWSER = 200
_MAX_REASON = 240
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
    Append one audit event and return the stored record.

    ``event`` must carry kind, actor, uin, and result. timestamp defaults to
    the current unix time. detail defaults to an empty string. ``uin`` may be
    empty only when result is failure. Optional check, client, reason, action,
    and user-action fields (``eventId``, ``event``, ``appCode``, ``sessionId``,
    ``source``, ``service``, ``requestId``) are stored only when the caller
    supplied them. ``retention``
    of ``activity`` (or omitted) is left off the record. ``retention`` of
    ``permanent`` is stored, and that row is written even when the timestamp
    is already older than the activity window. An activity row that is already
    older than the window is not kept in the file or the Redis list.

    Mappings that contain a secret key (password, faceImage, image, embedding,
    cbeff, authorization, token, including nested keys) are rejected and not
    written. Any other extra key is omitted. Binary values are rejected.
    Invalid optional values raise ``ValueError`` and write nothing.
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
    Activity rows older than ``AUDIT_RETENTION_SECONDS`` are left out. Every
    permanent row is included, whatever its age.
    """
    _check_limit(limit)
    lines = _open_store(store, path).read(limit)
    cutoff = _retention_cutoff()
    records = [_project_line(line) for line in lines]
    return [record for record in records if not _record_expired(record, cutoff)]


def project_for_citizen(record: Mapping[str, Any]) -> dict[str, Any]:
    """Citizen view of one row: own outcome only, with no network or officer text.

    ``eventId`` and ``checkId`` are included when the row has them. ``device``
    is a short browser label from ``browser``, or an empty string when that
    field is absent. The raw user agent, source, IP, actor, detail, and scores
    are left out.
    """
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    happened = _citizen_event_name(record)
    projected: dict[str, Any] = {}
    for key in ("eventId", "checkId"):
        value = record.get(key)
        if isinstance(value, str) and value:
            projected[key] = value
    projected["time"] = record.get("timestamp")
    projected["event"] = happened
    projected["result"] = record.get("result")
    projected["message"] = _citizen_outcome(record, happened)
    projected["device"] = _citizen_device(record)
    return projected


def tries_used(records: list[Mapping[str, Any]], uin: str) -> int:
    """Failed authenticate rows for ``uin`` whose reason spends a try.

    A row counts when ``kind`` or ``event`` is ``authenticate``, ``result`` is
    ``failure``, and ``reasonCode`` is one of ``TRY_CODES`` (FACE-3, PAD-1,
    PAD-2, MATCH-1).
    """
    count = 0
    for record in records:
        if record.get("uin") != uin or record.get("result") != "failure":
            continue
        if record.get("kind") != "authenticate" and record.get("event") != "authenticate":
            continue
        if record.get("reasonCode") in TRY_CODES:
            count += 1
    return count


def search_events(
    records: list[Mapping[str, Any]],
    *,
    uin: str | None = None,
    app_code: str | None = None,
    session_id: str | None = None,
    on_date: str | None = None,
) -> list[Mapping[str, Any]]:
    """Filter loaded rows. Empty filters are ignored. Append order is kept.

    ``on_date`` is a ``YYYY-MM-DD`` calendar day in UTC, matched to ``timestamp``.
    ``app_code`` matches ``appCode``. ``session_id`` matches ``sessionId``.
    """
    matched: list[Mapping[str, Any]] = []
    for record in records:
        if _filter_active(uin) and record.get("uin") != uin:
            continue
        if _filter_active(app_code) and record.get("appCode") != app_code:
            continue
        if _filter_active(session_id) and record.get("sessionId") != session_id:
            continue
        if _filter_active(on_date) and _timestamp_utc_date(record.get("timestamp")) != on_date:
            continue
        matched.append(record)
    return matched


def _citizen_event_name(record: Mapping[str, Any]) -> str:
    named = record.get("event")
    if not isinstance(named, str) or not named.strip():
        named = record.get("kind")
    if not isinstance(named, str):
        return ""
    return named.strip()


def _citizen_outcome(record: Mapping[str, Any], happened: str) -> str:
    if happened == "notification_sent":
        return citizen_message("LIMIT-1")
    if happened == "activity_reported":
        return "You reported this check"
    code = record.get("reasonCode")
    if isinstance(code, str) and code in CODES:
        return citizen_message(code)
    if record.get("result") == "success" and happened == "authenticate":
        return "Your face check passed"
    if record.get("result") == "success" and happened == "enroll":
        return "Your ID was created"
    return ""


def _citizen_device(record: Mapping[str, Any]) -> str:
    browser = record.get("browser")
    if not isinstance(browser, str) or not browser.strip():
        return ""
    return rough_device(browser)


def _filter_active(value: str | None) -> bool:
    return value is not None and value != ""


def _timestamp_utc_date(timestamp: Any) -> str:
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return ""
    if timestamp != timestamp or timestamp in (float("inf"), float("-inf")):
        return ""
    try:
        moment = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.date().isoformat()


class FileAuditStore:
    """JSON lines in ``directory / audit.jsonl``. A new process can read the file.

    Activity rows older than the retention window are removed on append and on
    read. Permanent rows in the same file stay.
    """

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.file_path = self.directory / _AUDIT_FILENAME

    def append(self, line: str) -> None:
        if "\n" in line or "\r" in line:
            raise ValueError("audit line must be a single line")
        with _file_lock:
            cutoff = _retention_cutoff()
            existing = self._read_lines_locked()
            kept, dropped = _without_expired(existing, cutoff)
            # An already-expired activity line is not stored. Permanent rows are
            # stored even when the timestamp is already past the window. Prune
            # still runs so older activity UINs do not remain.
            if _line_expired(line, cutoff):
                if dropped:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    self._write_lines_locked(kept)
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            if dropped:
                self._write_lines_locked([*kept, line])
            else:
                self._append_line_locked(line)

    def read(self, limit: int | None = None) -> list[str]:
        _check_limit(limit)
        with _file_lock:
            existing = self._read_lines_locked()
            kept, dropped = _without_expired(existing, _retention_cutoff())
            if dropped:
                self._write_lines_locked(kept)
            lines = kept
        if limit is None:
            return lines
        if limit == 0:
            return []
        return lines[-limit:]

    def _read_lines_locked(self) -> list[str]:
        if not self.file_path.is_file():
            return []
        text = self.file_path.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if line.strip()]

    def _append_line_locked(self, line: str) -> None:
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _write_lines_locked(self, lines: list[str]) -> None:
        payload = "".join(f"{line}\n" for line in lines)
        with self.file_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())


class RedisAuditStore:
    """Append-only Redis list. The list, not this process, holds the log.

    Activity rows older than the retention window are removed on append and on
    read. Permanent rows in the same list stay. The key is not given a TTL.
    """

    def __init__(self, url: str) -> None:
        if not url or not str(url).strip():
            raise ValueError("Redis audit URL is empty")
        self.url = str(url).strip()

    def append(self, line: str) -> None:
        client = self._connect()
        try:
            cutoff = _retention_cutoff()
            self._prune(client, cutoff)
            if not _line_expired(line, cutoff):
                client.rpush(REDIS_AUDIT_KEY, line)
        finally:
            client.close()

    def read(self, limit: int | None = None) -> list[str]:
        _check_limit(limit)
        client = self._connect()
        try:
            lines = self._prune(client)
        finally:
            client.close()
        if limit is None:
            return lines
        if limit == 0:
            return []
        return lines[-limit:]

    def _prune(self, client: Any, cutoff: float | None = None) -> list[str]:
        """Drop expired rows and return the list, oldest first.

        Expired activity rows are removed wherever they sit. Permanent rows
        stay. Append order of the rows that remain is unchanged, so the head
        stays the oldest survivor.
        """
        if cutoff is None:
            cutoff = _retention_cutoff()
        raw = client.lrange(REDIS_AUDIT_KEY, 0, -1)
        lines = [_decode_redis_value(item) for item in raw]
        kept, dropped = _without_expired(lines, cutoff)
        if dropped:
            client.delete(REDIS_AUDIT_KEY)
            for item in kept:
                client.rpush(REDIS_AUDIT_KEY, item)
        return kept

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
    if os.environ.get("AUDIT_BACKEND", "").strip().lower() == "file":
        return _file_store_from_env()
    raise RuntimeError("REDIS_URL is required for the audit log")


def _file_store_from_env() -> FileAuditStore:
    """File store selected only by ``AUDIT_BACKEND=file``."""
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
    # Empty before a UIN exists: a failure, or a saved application (appCode).
    event_name = event.get("event")
    allow_empty_uin = result == "failure" or event_name == "details_saved"
    uin = _require_text(event["uin"], "uin", _MAX_UIN, allow_empty=allow_empty_uin)
    if "detail" in event and event["detail"] is not None:
        detail = _require_text(event["detail"], "detail", _MAX_DETAIL, allow_empty=True)
    else:
        detail = ""
    timestamp = _require_timestamp(event.get("timestamp"))
    record = {
        "kind": kind,
        "actor": actor,
        "uin": uin,
        "timestamp": timestamp,
        "result": result,
        "detail": detail,
    }
    _fill_optional(record, event)
    return record


def _fill_optional(record: dict[str, Any], event: Mapping[str, Any]) -> None:
    """Copy supplied optional fields. Omit a blank reason and activity retention."""
    if "checkId" in event:
        record["checkId"] = _require_text(
            event["checkId"], "checkId", _MAX_CHECK_ID, allow_empty=False
        )
    if "livenessPassed" in event:
        record["livenessPassed"] = _require_bool(event["livenessPassed"], "livenessPassed")
    if "livenessScore" in event:
        record["livenessScore"] = _require_finite_float(event["livenessScore"], "livenessScore")
    if "matchPassed" in event:
        record["matchPassed"] = _require_bool(event["matchPassed"], "matchPassed")
    if "matchScore" in event:
        record["matchScore"] = _require_finite_float(event["matchScore"], "matchScore")
    if "network" in event:
        record["network"] = _require_ip(event["network"])
    if "browser" in event:
        record["browser"] = _require_text(
            event["browser"], "browser", _MAX_BROWSER, allow_empty=False
        )
    if "reason" in event:
        reason = _require_text(event["reason"], "reason", _MAX_REASON, allow_empty=True)
        if reason:
            record["reason"] = reason
    if "reasonCode" in event:
        record["reasonCode"] = _require_token(
            event["reasonCode"], "reasonCode", REASON_CODES | CODES
        )
    if "eventId" in event:
        record["eventId"] = _require_text(
            event["eventId"], "eventId", _MAX_EVENT_ID, allow_empty=False
        )
    if "event" in event:
        record["event"] = _require_token(event["event"], "event", EVENTS)
    if "appCode" in event:
        record["appCode"] = _require_text(
            event["appCode"], "appCode", _MAX_APP_CODE, allow_empty=False
        )
    if "sessionId" in event:
        record["sessionId"] = _require_text(
            event["sessionId"], "sessionId", _MAX_SESSION_ID, allow_empty=False
        )
    if "source" in event:
        record["source"] = _require_text(event["source"], "source", _MAX_SOURCE, allow_empty=False)
    if "service" in event:
        record["service"] = _require_text(
            event["service"], "service", _MAX_SERVICE, allow_empty=False
        )
    if "requestId" in event:
        record["requestId"] = _require_text(
            event["requestId"], "requestId", _MAX_REQUEST_ID, allow_empty=False
        )
    if "action" in event:
        record["action"] = _require_token(event["action"], "action", ACTION_CODES)
    if "retention" in event:
        retention = _require_token(event["retention"], "retention", _RETENTIONS)
        if retention == "permanent":
            record["retention"] = "permanent"


def _require_bool(value: Any, field: str) -> bool:
    # 0 and 1 are ints. Only a real bool is accepted.
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_finite_float(value: Any, field: str) -> float:
    # bool is an int subclass and is not a score.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite float")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be a finite float")
    return number


def _require_ip(value: Any) -> str:
    text = _require_text(value, "network", _MAX_NETWORK, allow_empty=False)
    try:
        ipaddress.ip_address(text)
    except ValueError:
        raise ValueError("network must be an IP address") from None
    return text


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


def _retention_cutoff() -> float:
    return time.time() - AUDIT_RETENTION_SECONDS


def _record_expired(record: Mapping[str, Any], cutoff: float) -> bool:
    """Activity rows age out. Permanent rows in the same log do not."""
    if record.get("retention") == "permanent":
        return False
    return record["timestamp"] < cutoff


def _line_expired(line: str, cutoff: float) -> bool:
    """Whether a well-formed activity row is older than ``cutoff``.

    A permanent row is never expired. A line ``_project_line`` rejects is kept.
    The existing corrupt-record error still surfaces when that line is read
    back, and the message stays free of images and secrets.
    """
    try:
        record = _project_line(line)
    except ValueError:
        return False
    return _record_expired(record, cutoff)


def _without_expired(lines: list[str], cutoff: float) -> tuple[list[str], bool]:
    kept: list[str] = []
    dropped = False
    for line in lines:
        if _line_expired(line, cutoff):
            dropped = True
            continue
        kept.append(line)
    return kept, dropped


def _require_timestamp(value: Any) -> float:
    if value is None:
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
