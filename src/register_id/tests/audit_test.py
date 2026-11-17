"""Audit log: safe fields only, file or Redis persistence, newest last."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import redis

from register_id.audit import REDIS_AUDIT_KEY, list_events, record_event


SECRET = "SuperSecretPassword!"
FACE = "data:image/jpeg;base64,/9j/face-bytes-should-not-be-stored"
EMBEDDING = [0.1, 0.2, 0.3, 0.4]
TOKEN = "Bearer eyJhbGciOiJub25lIn0.payload.sig"


class MemoryStore:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append(self, line: str) -> None:
        self.lines.append(line)

    def read(self, limit: int | None = None) -> list[str]:
        if limit is None:
            return list(self.lines)
        if limit == 0:
            return []
        return list(self.lines[-limit:])


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        data = self.lists.get(key, [])
        count = len(data)
        if count == 0:
            return []
        if start < 0:
            start = count + start
        if end < 0:
            end = count + end
        start = max(start, 0)
        end = min(end, count - 1)
        if start > end:
            return []
        return data[start : end + 1]

    def close(self) -> None:
        return None


class DownRedis:
    def rpush(self, key: str, value: str) -> int:
        raise redis.ConnectionError("redis unavailable")

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        raise redis.ConnectionError("redis unavailable")

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _isolated_audit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("LOG_DIR", raising=False)


def _event(**overrides: object) -> dict:
    event: dict = {
        "kind": "enroll",
        "actor": "citizen",
        "uin": "123456789012",
        "result": "success",
        "detail": "idrepo accepted",
        "timestamp": 1_700_000_000.5,
    }
    event.update(overrides)
    return event


def test_memory_store_appends_in_order_and_limits_from_the_tail() -> None:
    store = MemoryStore()
    first = record_event(_event(detail="first", timestamp=10.0), store=store)
    second = record_event(
        _event(
            kind="credential",
            actor="operator-42",
            result="failure",
            detail="keycloak rejected",
            timestamp=9.0,
        ),
        store=store,
    )
    third = record_event(_event(detail="third", timestamp=11.0), store=store)

    listed = list_events(store=store)
    assert listed == [first, second, third]
    assert [item["detail"] for item in listed] == ["first", "keycloak rejected", "third"]
    assert list_events(2, store=store) == [second, third]
    assert list_events(0, store=store) == []
    assert list_events(limit=None, store=store) == listed

    blob = "\n".join(store.lines)
    for leaked in (SECRET, FACE, "embedding", TOKEN):
        assert leaked not in blob
    assert set(first) == {"kind", "actor", "uin", "timestamp", "result", "detail"}
    assert isinstance(first["timestamp"], float)
    assert second["actor"] == "operator-42"
    assert second["kind"] == "credential"
    assert second["result"] == "failure"


def test_extra_fields_are_omitted() -> None:
    store = MemoryStore()
    stored = record_event(
        _event(fullName="Ada Lovelace", email="ada@example.com"),
        store=store,
    )
    assert "fullName" not in stored
    assert "email" not in stored
    assert "Ada Lovelace" not in store.lines[0]
    assert "ada@example.com" not in store.lines[0]


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "faceImage",
        "face_image",
        "image",
        "liveImage",
        "embedding",
        "faceEmbedding",
        "cbeff",
        "cbeffGenerated",
        "authorization",
        "Authorization",
        "token",
        "access_token",
    ],
)
def test_forbidden_keys_are_rejected_and_not_stored(key: str) -> None:
    store = MemoryStore()
    event = _event()
    event[key] = SECRET if "token" not in key.lower() and key.lower() != "authorization" else TOKEN
    if key in {"faceImage", "face_image", "image", "liveImage"}:
        event[key] = FACE
    if "embed" in key.lower():
        event[key] = EMBEDDING
    if "cbeff" in key.lower():
        event[key] = "<cbeff>face-bytes</cbeff>"

    with pytest.raises(ValueError, match="forbidden field") as caught:
        record_event(event, store=store)

    message = str(caught.value)
    assert SECRET not in message
    assert FACE not in message
    assert TOKEN not in message
    assert store.lines == []
    assert list_events(store=store) == []


def test_nested_secret_keys_and_binary_payloads_are_rejected() -> None:
    store = MemoryStore()
    nested = _event()
    nested["views"] = [{"sector": "front", "image": FACE, "password": SECRET}]
    with pytest.raises(ValueError, match="forbidden field"):
        record_event(nested, store=store)

    binary = _event(detail=b"\xff\xd8\xffraw-face")
    with pytest.raises(ValueError, match="binary payload"):
        record_event(binary, store=store)

    assert store.lines == []


def test_file_log_survives_process_exit(tmp_path: Path) -> None:
    script = """
import sys
from register_id.audit import record_event
record_event(
    {
        "kind": "credential",
        "actor": "citizen",
        "uin": "99887766",
        "result": "failure",
        "detail": "keycloak down",
        "timestamp": 1700000000.5,
        "password": "must-not-be-accepted",
    },
    path=sys.argv[1],
)
"""
    # The child must refuse the password. A clean sibling process writes the real record.
    env = os.environ.copy()
    env.pop("REDIS_URL", None)
    env.pop("LOG_DIR", None)
    refused = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert refused.returncode != 0
    assert not (tmp_path / "audit.jsonl").exists()

    writer = """
import sys
from register_id.audit import record_event
record_event(
    {
        "kind": "credential",
        "actor": "operator-7",
        "uin": "99887766",
        "result": "failure",
        "detail": "keycloak down",
        "timestamp": 1700000000.5,
    },
    path=sys.argv[1],
)
"""
    wrote = subprocess.run(
        [sys.executable, "-c", writer, str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert wrote.returncode == 0, wrote.stderr

    events = list_events(path=tmp_path)
    assert events == [
        {
            "kind": "credential",
            "actor": "operator-7",
            "uin": "99887766",
            "timestamp": 1700000000.5,
            "result": "failure",
            "detail": "keycloak down",
        }
    ]
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "password" not in raw
    assert "must-not-be-accepted" not in raw
    assert json.loads(raw.strip())["uin"] == "99887766"


def test_log_dir_and_default_temp_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    record_event(_event(detail="from-log-dir"), path=None)
    assert (log_dir / "audit.jsonl").is_file()
    assert list_events()[0]["detail"] == "from-log-dir"

    monkeypatch.delenv("LOG_DIR", raising=False)
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))
    record_event(_event(detail="from-temp", uin="555"))
    stored = temp_root / "register-id" / "audit.jsonl"
    assert stored.is_file()
    assert "555" in stored.read_text(encoding="utf-8")
    assert list_events(path=temp_root / "register-id")[-1]["detail"] == "from-temp"


def test_explicit_path_overrides_redis_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    record_event(_event(detail="on-disk"), path=tmp_path)
    assert (tmp_path / "audit.jsonl").is_file()
    assert list_events(1, path=tmp_path)[0]["detail"] == "on-disk"


def test_redis_list_is_appended_and_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: fake)

    first = record_event(_event(detail="redis-1", timestamp=1.25))
    second = record_event(
        _event(kind="credential", actor="operator-9", result="success", detail="redis-2", timestamp=2.5)
    )

    assert set(fake.lists) == {REDIS_AUDIT_KEY}
    assert REDIS_AUDIT_KEY == "register-id:audit"
    assert list_events() == [first, second]
    assert list_events(1) == [second]
    blob = "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert SECRET not in blob
    assert FACE not in blob
    assert "redis-1" in blob and "redis-2" in blob


def test_redis_down_raises_and_does_not_write_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: DownRedis())

    with pytest.raises(redis.ConnectionError):
        record_event(_event())

    assert list(tmp_path.iterdir()) == []
    with pytest.raises(redis.ConnectionError):
        list_events()


def test_invalid_event_is_not_stored() -> None:
    store = MemoryStore()
    with pytest.raises(ValueError):
        record_event(_event(kind="login"), store=store)
    with pytest.raises(ValueError):
        record_event(_event(result="error"), store=store)
    with pytest.raises(ValueError):
        record_event(_event(detail="x" * 241), store=store)
    with pytest.raises(ValueError):
        record_event(_event(actor=""), store=store)
    with pytest.raises(ValueError):
        list_events(-1, store=store)
    assert store.lines == []
