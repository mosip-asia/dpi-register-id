"""
Staff directory for officers and admins.

Each stored member has id, name, email, role, token_hash, and created_at.
The bearer token is returned once from add_member. Only its sha256 hex digest
is stored. List, role, and authentication results never include the token or
the hash. Tokens, hashes, and passwords are never written to a log.

This is not the audit log. Nothing here appends an audit event.

Storage follows the process environment unless a test injects a store or a directory:
- REDIS_URL set: one JSON string at the Redis key ``register-id:staff``.
  A down Redis raises. There is no silent file fallback, including when
  ``FILE_STORE=1`` is also set.
- REDIS_URL unset: raise. The process does not create or write ``staff.json``.
  ``FILE_STORE=1`` is an explicit opt-in that writes JSON under
  LOG_DIR, or under a directory in the system temp dir when LOG_DIR is unset.
"""

from __future__ import annotations

import hashlib
import hmac
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

from register_id.access import ADMIN, OFFICER

REDIS_STAFF_KEY = "register-id:staff"
_STAFF_FILENAME = "staff.json"
_STAFF_ROLES = frozenset({OFFICER, ADMIN})
_HASH_LENGTH = 64
_MAX_NAME = 200
_MAX_EMAIL = 254
_file_lock = threading.Lock()
_directory_lock = threading.Lock()


class StaffStore(Protocol):
    """Directory store. ``load`` returns stored member records, including hashes."""

    def load(self) -> list[dict[str, Any]]: ...

    def save(self, members: list[dict[str, Any]]) -> None: ...


def add_member(
    name: str,
    email: str,
    role: str,
    *,
    store: StaffStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """
    Add an officer or admin and return the public record plus the bearer token.

    The token is urlsafe random data from 32 bytes. It is not stored. A later
    call cannot read it back. Duplicate emails, compared case-insensitively,
    raise ValueError. An invalid role raises ValueError.
    """
    cleaned_name = _require_name(name)
    cleaned_email = _require_email(email)
    cleaned_role = _require_role(role)
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    created_at = time.time()

    def mutate(members: list[dict[str, Any]]) -> dict[str, Any]:
        if _email_taken(members, cleaned_email):
            raise ValueError("email is already registered")
        member_id = _new_id(members)
        members.append(
            {
                "id": member_id,
                "name": cleaned_name,
                "email": cleaned_email,
                "role": cleaned_role,
                "token_hash": token_hash,
                "created_at": created_at,
            }
        )
        public = _public_member(members[-1])
        public["token"] = token
        return public

    return _update(store, path, mutate)


def list_members(
    *,
    store: StaffStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Return id, name, email, role, and createdAt. Never a token or token hash."""
    members = _read(store, path)
    return [_public_member(member) for member in members]


def remove_member(
    member_id: str,
    *,
    store: StaffStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    """Remove one member. False when the id is not in the directory."""
    target = _clean_id(member_id)

    def mutate(members: list[dict[str, Any]]) -> bool:
        kept = [member for member in members if member["id"] != target]
        if len(kept) == len(members):
            return False
        members[:] = kept
        return True

    return _update(store, path, mutate)


def set_role(
    member_id: str,
    role: str,
    *,
    store: StaffStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """
    Change an officer or admin role.

    Returns the public record, or None when the id is missing.
    An invalid role raises ValueError.
    """
    target = _clean_id(member_id)
    cleaned_role = _require_role(role)

    def mutate(members: list[dict[str, Any]]) -> dict[str, Any] | None:
        for member in members:
            if member["id"] == target:
                member["role"] = cleaned_role
                return _public_member(member)
        return None

    return _update(store, path, mutate)


def authenticate_token(
    token: str,
    *,
    store: StaffStore | None = None,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """
    Return {id, name, email, role} when the bearer token matches a stored hash.

    Comparison uses hmac.compare_digest on the sha256 hex digests.
    A missing or unknown token returns None.
    """
    if not isinstance(token, str) or not token:
        return None
    digest = _hash_token(token)
    found: dict[str, Any] | None = None
    for member in _read(store, path):
        stored_hash = member["token_hash"]
        if len(stored_hash) == len(digest) and hmac.compare_digest(digest, stored_hash):
            if found is None:
                found = member
    if found is None:
        return None
    return _authenticated_member(found)


class FileStaffStore:
    """One JSON document at ``directory / staff.json``."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.file_path = self.directory / _STAFF_FILENAME

    def load(self) -> list[dict[str, Any]]:
        with _file_lock:
            if not self.file_path.is_file():
                return []
            text = self.file_path.read_text(encoding="utf-8")
        return _parse_directory(text)

    def save(self, members: list[dict[str, Any]]) -> None:
        payload = _dump_directory(members)
        with _file_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.file_path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.file_path)


class RedisStaffStore:
    """The whole directory as one JSON string at ``register-id:staff``."""

    def __init__(self, url: str) -> None:
        if not url or not str(url).strip():
            raise ValueError("Redis staff URL is empty")
        self.url = str(url).strip()

    def load(self) -> list[dict[str, Any]]:
        client = self._connect()
        try:
            raw = client.get(REDIS_STAFF_KEY)
        finally:
            client.close()
        if raw is None:
            return []
        return _parse_directory(_decode_redis_value(raw))

    def save(self, members: list[dict[str, Any]]) -> None:
        payload = _dump_directory(members)
        client = self._connect()
        try:
            client.set(REDIS_STAFF_KEY, payload)
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
    store: StaffStore | None,
    path: str | os.PathLike[str] | None,
) -> StaffStore:
    if store is not None and path is not None:
        raise ValueError("pass store or path, not both")
    if store is not None:
        return store
    if path is not None:
        return FileStaffStore(path)
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        _require_redis_url(redis_url)
        return RedisStaffStore(redis_url)
    if os.environ.get("FILE_STORE", "").strip() == "1":
        return _file_store_from_env()
    raise RuntimeError("REDIS_URL is required for the staff directory")


def _file_store_from_env() -> FileStaffStore:
    """File store selected only by ``FILE_STORE=1``."""
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if log_dir:
        return FileStaffStore(log_dir)
    return FileStaffStore(Path(tempfile.gettempdir()) / "register-id")


def _require_redis_url(url: str) -> None:
    """Reject a URL that would silently target something other than Redis."""
    parts = urlsplit(url)
    if parts.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use the redis or rediss scheme")
    if parts.hostname is None:
        raise ValueError("REDIS_URL is missing a host")


def _read(
    store: StaffStore | None,
    path: str | os.PathLike[str] | None,
) -> list[dict[str, Any]]:
    backend = _open_store(store, path)
    with _directory_lock:
        return _normalize_members(backend.load())


def _update(
    store: StaffStore | None,
    path: str | os.PathLike[str] | None,
    mutate: Callable[[list[dict[str, Any]]], Any],
) -> Any:
    backend = _open_store(store, path)
    with _directory_lock:
        members = _normalize_members(backend.load())
        result = mutate(members)
        backend.save(members)
        return result


def _normalize_members(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("corrupt staff directory")
    return [_require_stored(item) for item in raw]


def _require_stored(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("corrupt staff directory")
    member_id = item.get("id")
    name = item.get("name")
    email = item.get("email")
    role = item.get("role")
    token_hash = item.get("token_hash")
    created_at = item.get("created_at")
    if not isinstance(member_id, str) or not member_id.startswith("stf_"):
        raise ValueError("corrupt staff directory")
    if not isinstance(name, str) or not name:
        raise ValueError("corrupt staff directory")
    if not isinstance(email, str) or not email:
        raise ValueError("corrupt staff directory")
    if not isinstance(role, str) or role not in _STAFF_ROLES:
        raise ValueError("corrupt staff directory")
    if not isinstance(token_hash, str) or len(token_hash) != _HASH_LENGTH:
        raise ValueError("corrupt staff directory")
    if not all(character in "0123456789abcdef" for character in token_hash):
        raise ValueError("corrupt staff directory")
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
        raise ValueError("corrupt staff directory")
    created = float(created_at)
    if created != created or created in (float("inf"), float("-inf")):
        raise ValueError("corrupt staff directory")
    return {
        "id": member_id,
        "name": name,
        "email": email,
        "role": role,
        "token_hash": token_hash,
        "created_at": created,
    }


def _parse_directory(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("corrupt staff directory") from None
    if not isinstance(payload, list):
        raise ValueError("corrupt staff directory")
    return payload


def _dump_directory(members: list[dict[str, Any]]) -> str:
    stored = [_require_stored(member) for member in members]
    return json.dumps(stored, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _public_member(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": member["id"],
        "name": member["name"],
        "email": member["email"],
        "role": member["role"],
        "createdAt": member["created_at"],
    }


def _authenticated_member(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": member["id"],
        "name": member["name"],
        "email": member["email"],
        "role": member["role"],
    }


def _require_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("name must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("name must be non-empty")
    if len(cleaned) > _MAX_NAME:
        raise ValueError("name is too long")
    return cleaned


def _require_email(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("email must be non-empty")
    if len(cleaned) > _MAX_EMAIL:
        raise ValueError("email is too long")
    return cleaned


def _require_role(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("role must be a string")
    cleaned = value.strip().lower()
    if cleaned not in _STAFF_ROLES:
        allowed = ", ".join(sorted(_STAFF_ROLES))
        raise ValueError(f"role must be one of: {allowed}")
    return cleaned


def _clean_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _email_taken(members: list[dict[str, Any]], email: str) -> bool:
    folded = email.casefold()
    return any(member["email"].casefold() == folded for member in members)


def _new_id(members: list[dict[str, Any]]) -> str:
    existing = {member["id"] for member in members}
    for _ in range(5):
        member_id = "stf_" + secrets.token_hex(16)
        if member_id not in existing:
            return member_id
    raise RuntimeError("could not allocate a staff id")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _decode_redis_value(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode("utf-8")
    if isinstance(item, str):
        return item
    raise ValueError("corrupt staff directory")
