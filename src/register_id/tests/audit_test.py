"""Audit log: safe fields only, file or Redis persistence, newest last."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import redis

from register_id.audit import AUDIT_RETENTION_SECONDS, REDIS_AUDIT_KEY, list_events, record_event


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

    def delete(self, key: str) -> int:
        if key in self.lists:
            del self.lists[key]
            return 1
        return 0


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
        "timestamp": float(int(time.time())),
    }
    event.update(overrides)
    return event


def test_memory_store_appends_in_order_and_limits_from_the_tail() -> None:
    store = MemoryStore()
    base = float(int(time.time()))
    first = record_event(_event(detail="first", timestamp=base), store=store)
    second = record_event(
        _event(
            kind="credential",
            actor="operator-42",
            result="failure",
            detail="keycloak rejected",
            timestamp=base - 30,
        ),
        store=store,
    )
    third = record_event(_event(detail="third", timestamp=base + 30), store=store)

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
        "timestamp": float(sys.argv[2]),
    },
    path=sys.argv[1],
)
"""
    stamp = float(int(time.time())) + 0.5
    wrote = subprocess.run(
        [sys.executable, "-c", writer, str(tmp_path), str(stamp)],
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
            "timestamp": stamp,
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

    base = float(int(time.time()))
    first = record_event(_event(detail="redis-1", timestamp=base + 0.25))
    second = record_event(
        _event(
            kind="credential",
            actor="operator-9",
            result="success",
            detail="redis-2",
            timestamp=base + 0.5,
        )
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


def _stamp() -> float:
    return float(int(time.time()))


def test_list_events_drops_expired_rows_and_keeps_fresh_ones() -> None:
    store = MemoryStore()
    now = _stamp()
    record_event(
        _event(detail="stale", uin="100000000001", timestamp=now - AUDIT_RETENTION_SECONDS - 5),
        store=store,
    )
    fresh = record_event(_event(detail="fresh", uin="100000000002", timestamp=now), store=store)
    boundary = record_event(
        _event(
            detail="boundary",
            uin="100000000003",
            timestamp=now - AUDIT_RETENTION_SECONDS + 120,
        ),
        store=store,
    )
    assert list_events(store=store) == [fresh, boundary]


def test_file_audit_drops_expired_rows_on_append_and_read(tmp_path: Path) -> None:
    now = _stamp()
    expired_at = now - AUDIT_RETENTION_SECONDS - 5
    audit_file = tmp_path / "audit.jsonl"
    record_event(
        _event(detail="stale", uin="100000000001", timestamp=expired_at),
        path=tmp_path,
    )
    assert not audit_file.exists()

    record_event(_event(detail="fresh", uin="100000000002", timestamp=now), path=tmp_path)
    after_fresh = audit_file.read_text(encoding="utf-8")
    assert "100000000001" not in after_fresh
    assert "100000000002" in after_fresh

    record_event(
        _event(detail="stale-again", uin="100000000001", timestamp=expired_at),
        path=tmp_path,
    )
    after_append = audit_file.read_text(encoding="utf-8")
    assert "100000000001" not in after_append
    assert "100000000002" in after_append
    assert [event["uin"] for event in list_events(path=tmp_path)] == ["100000000002"]

    planted = {
        "kind": "authenticate",
        "actor": "citizen",
        "uin": "100000000003",
        "timestamp": expired_at,
        "result": "failure",
        "detail": "planted",
    }
    with (tmp_path / "audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(planted) + "\n")
    record_event(
        _event(detail="fresh-2", uin="100000000004", timestamp=now + 1),
        path=tmp_path,
    )
    after_rewrite = audit_file.read_text(encoding="utf-8")
    assert "100000000003" not in after_rewrite
    assert "100000000004" in after_rewrite

    with (tmp_path / "audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(planted) + "\n")
    assert list_events(0, path=tmp_path) == []
    remaining = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "100000000003" not in remaining
    assert "100000000002" in remaining
    assert [event["detail"] for event in list_events(path=tmp_path)] == ["fresh", "fresh-2"]


def test_timestamp_exactly_on_the_cutoff_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frozen = 1_800_000_000.0
    monkeypatch.setattr("register_id.audit.time.time", lambda: frozen)
    cutoff = frozen - AUDIT_RETENTION_SECONDS
    record_event(
        _event(detail="on-cutoff", uin="100000000010", timestamp=cutoff),
        path=tmp_path,
    )
    record_event(
        _event(detail="just-older", uin="100000000011", timestamp=cutoff - 0.001),
        path=tmp_path,
    )
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "100000000010" in text
    assert "100000000011" not in text
    assert [event["detail"] for event in list_events(path=tmp_path)] == ["on-cutoff"]


def test_redis_audit_drops_expired_rows_on_append_and_read(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: fake)
    now = _stamp()
    expired_at = now - AUDIT_RETENTION_SECONDS - 5

    record_event(_event(detail="stale", uin="100000000002", timestamp=expired_at))
    assert REDIS_AUDIT_KEY not in fake.lists

    record_event(_event(detail="fresh-1", uin="100000000001", timestamp=now))
    record_event(_event(detail="stale-again", uin="100000000002", timestamp=expired_at))
    assert "100000000002" not in "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert "100000000001" in "\n".join(fake.lists[REDIS_AUDIT_KEY])

    fake.lists[REDIS_AUDIT_KEY].append(
        json.dumps(
            {
                "kind": "enroll",
                "actor": "citizen",
                "uin": "100000000002",
                "timestamp": expired_at,
                "result": "failure",
                "detail": "already-there",
            }
        )
    )
    record_event(_event(detail="fresh-2", uin="100000000003", timestamp=now + 1))
    blob = "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert "100000000002" not in blob
    assert [event["uin"] for event in list_events()] == ["100000000001", "100000000003"]

    fake.lists[REDIS_AUDIT_KEY].append(
        json.dumps(
            {
                "kind": "operator",
                "actor": "operator-1",
                "uin": "100000000004",
                "timestamp": expired_at,
                "result": "failure",
                "detail": "planted",
            }
        )
    )
    assert [event["uin"] for event in list_events()] == ["100000000001", "100000000003"]
    assert "100000000004" not in "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert fake.lists[REDIS_AUDIT_KEY][0].find("100000000001") != -1
    assert fake.lists[REDIS_AUDIT_KEY][-1].find("100000000003") != -1


def test_retention_prune_still_rejects_a_corrupt_audit_line(tmp_path: Path) -> None:
    now = _stamp()
    record_event(_event(detail="kept", uin="100000000009", timestamp=now), path=tmp_path)
    missing_timestamp = {
        "kind": "enroll",
        "actor": "citizen",
        "uin": "100000000008",
        "result": "success",
        "detail": "no-time",
    }
    expired = _event(
        detail="stale",
        uin="100000000006",
        timestamp=now - AUDIT_RETENTION_SECONDS - 5,
    )
    file_path = tmp_path / "audit.jsonl"
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(expired) + "\n")
        handle.write(json.dumps(missing_timestamp) + "\n")

    with pytest.raises(ValueError, match="corrupt audit record") as missing:
        list_events(path=tmp_path)
    assert FACE not in str(missing.value)
    assert SECRET not in str(missing.value)

    text = file_path.read_text(encoding="utf-8")
    assert "100000000006" not in text
    assert "100000000009" in text
    assert "no-time" in text

    bad_timestamp = _event(detail="bad-time", uin="100000000007", timestamp=now)
    bad_timestamp["timestamp"] = "not-a-time"
    kept_line = file_path.read_text(encoding="utf-8").splitlines()[0]
    file_path.write_text(
        kept_line + "\n" + json.dumps(bad_timestamp) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="timestamp must be a unix time") as invalid:
        list_events(path=tmp_path)
    assert "not-a-time" not in str(invalid.value)
    assert FACE not in str(invalid.value)
