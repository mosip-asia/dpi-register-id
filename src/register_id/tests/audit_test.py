"""Audit log: safe fields only, file or Redis persistence, newest last."""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import redis

from register_id.audit import (
    ACTION_CODES,
    AUDIT_RETENTION_SECONDS,
    EVENTS,
    REASON_CODES,
    REDIS_AUDIT_KEY,
    list_events,
    project_for_citizen,
    record_event,
    search_events,
    tries_used,
)
from register_id.reasons import (
    CODES,
    REASON_CATALOG,
    TRY_CODES,
    citizen_message,
    officer_text,
    rough_device,
    uses_try,
)


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
    monkeypatch.delenv("AUDIT_BACKEND", raising=False)


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


def test_list_events_rejects_corrupt_or_tainted_audit_line() -> None:
    store = MemoryStore()
    record_event(_event(), store=store)
    tainted = _event()
    tainted["faceImage"] = FACE
    store.lines.append(json.dumps(tainted))
    with pytest.raises(ValueError, match="corrupt audit record") as caught:
        list_events(store=store)
    assert FACE not in str(caught.value)
    assert SECRET not in str(caught.value)

    store.lines[-1] = "{not-json"
    with pytest.raises(ValueError, match="corrupt audit record") as invalid:
        list_events(store=store)
    assert FACE not in str(invalid.value)


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


def test_unset_redis_url_does_not_write_an_audit_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))

    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        record_event(_event(detail="must-not-land"))

    assert not log_dir.exists()
    assert not (temp_root / "register-id").exists()
    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        list_events()


def test_log_dir_and_default_temp_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUDIT_BACKEND", "file")
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
    monkeypatch.setenv("AUDIT_BACKEND", "file")
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


def _expired_at(now: float | None = None) -> float:
    base = _stamp() if now is None else now
    return base - AUDIT_RETENTION_SECONDS - 5


def _permanent_event(**overrides: object) -> dict:
    event = _event(
        kind="dispute",
        actor="operator-3",
        uin="300000000001",
        result="success",
        detail="dispute opened",
        timestamp=_expired_at(),
        retention="permanent",
    )
    event.update(overrides)
    return event


def test_permanent_row_older_than_retention_stays_in_memory() -> None:
    store = MemoryStore()
    now = _stamp()
    old = _expired_at(now)
    fresh = record_event(
        _event(detail="fresh", uin="300000000010", timestamp=now),
        store=store,
    )
    permanent = record_event(_permanent_event(timestamp=old), store=store)
    record_event(
        _event(
            detail="stale-activity",
            uin="300000000011",
            timestamp=old,
            retention="activity",
        ),
        store=store,
    )

    assert permanent["retention"] == "permanent"
    assert permanent["timestamp"] == old
    assert set(permanent) == {
        "kind",
        "actor",
        "uin",
        "timestamp",
        "result",
        "detail",
        "retention",
    }
    assert list_events(store=store) == [fresh, permanent]
    assert [event["uin"] for event in list_events(store=store)] == [
        "300000000010",
        "300000000001",
    ]
    assert '"retention":"permanent"' in store.lines[1]
    assert "300000000011" not in "\n".join(
        line for line in store.lines if '"retention":"permanent"' in line
    )


def test_permanent_row_stays_in_file_when_activity_of_the_same_age_is_dropped(
    tmp_path: Path,
) -> None:
    now = _stamp()
    old = _expired_at(now)
    fresh = record_event(
        _event(detail="fresh", uin="300000000020", timestamp=now),
        path=tmp_path,
    )
    permanent = record_event(_permanent_event(timestamp=old, uin="300000000021"), path=tmp_path)
    record_event(
        _event(detail="stale-activity", uin="300000000022", timestamp=old),
        path=tmp_path,
    )
    audit_file = tmp_path / "audit.jsonl"
    after_append = audit_file.read_text(encoding="utf-8")
    assert "300000000022" not in after_append
    assert "300000000021" in after_append
    assert "300000000020" in after_append
    assert list_events(path=tmp_path) == [fresh, permanent]

    planted = {
        "kind": "enroll",
        "actor": "citizen",
        "uin": "300000000023",
        "timestamp": old,
        "result": "failure",
        "detail": "planted-activity",
    }
    with audit_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(planted) + "\n")
    record_event(
        _event(detail="fresh-2", uin="300000000024", timestamp=now + 1),
        path=tmp_path,
    )
    after_rewrite = audit_file.read_text(encoding="utf-8")
    assert "300000000023" not in after_rewrite
    assert "300000000021" in after_rewrite
    assert '"retention":"permanent"' in after_rewrite

    with audit_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(planted) + "\n")
    listed = list_events(path=tmp_path)
    assert [event["uin"] for event in listed] == [
        "300000000020",
        "300000000021",
        "300000000024",
    ]
    assert listed[1]["retention"] == "permanent"
    remaining = audit_file.read_text(encoding="utf-8")
    assert "300000000023" not in remaining
    assert "300000000021" in remaining


def test_permanent_row_stays_in_redis_when_activity_of_the_same_age_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: fake)
    now = _stamp()
    old = _expired_at(now)

    permanent = record_event(_permanent_event(timestamp=old, uin="300000000031"))
    record_event(_event(detail="stale-activity", uin="300000000032", timestamp=old))
    fresh = record_event(_event(detail="fresh", uin="300000000030", timestamp=now))

    assert set(fake.lists) == {REDIS_AUDIT_KEY}
    blob = "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert "300000000032" not in blob
    assert "300000000031" in blob
    assert '"retention":"permanent"' in blob
    assert list_events() == [permanent, fresh]

    fake.lists[REDIS_AUDIT_KEY].append(
        json.dumps(
            {
                "kind": "authenticate",
                "actor": "citizen",
                "uin": "300000000033",
                "timestamp": old,
                "result": "failure",
                "detail": "planted-activity",
            }
        )
    )
    record_event(_event(detail="fresh-2", uin="300000000034", timestamp=now + 1))
    blob = "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert "300000000033" not in blob
    assert "300000000031" in blob
    assert [event["uin"] for event in list_events()] == [
        "300000000031",
        "300000000030",
        "300000000034",
    ]

    fake.lists[REDIS_AUDIT_KEY].append(
        json.dumps(
            {
                "kind": "operator",
                "actor": "operator-1",
                "uin": "300000000035",
                "timestamp": old,
                "result": "failure",
                "detail": "planted-on-read",
            }
        )
    )
    assert [event["uin"] for event in list_events()] == [
        "300000000031",
        "300000000030",
        "300000000034",
    ]
    assert "300000000035" not in "\n".join(fake.lists[REDIS_AUDIT_KEY])
    assert '"retention":"permanent"' in fake.lists[REDIS_AUDIT_KEY][0]


def test_optional_check_fields_round_trip_and_are_absent_when_omitted() -> None:
    store = MemoryStore()
    stored = record_event(
        _event(
            kind="authenticate",
            result="failure",
            detail="no match",
            checkId="chk-7f3a",
            livenessPassed=False,
            livenessScore=0.25,
            matchPassed=False,
            matchScore=0.5,
            network="198.51.100.14",
            browser="Mozilla/5.0 (compatible; RegisterID)",
            reason="face did not match",
            reasonCode="face_mismatch",
            action="login",
        ),
        store=store,
    )
    assert stored["checkId"] == "chk-7f3a"
    assert stored["livenessPassed"] is False
    assert stored["livenessScore"] == 0.25
    assert stored["matchPassed"] is False
    assert stored["matchScore"] == 0.5
    assert stored["network"] == "198.51.100.14"
    assert stored["browser"] == "Mozilla/5.0 (compatible; RegisterID)"
    assert stored["reason"] == "face did not match"
    assert stored["reasonCode"] == "face_mismatch"
    assert stored["action"] == "login"
    assert "retention" not in stored
    assert "fullName" not in stored
    assert list_events(store=store) == [stored]

    plain = record_event(_event(detail="plain"), store=store)
    assert set(plain) == {"kind", "actor", "uin", "timestamp", "result", "detail"}
    assert list_events(store=store)[1] == plain

    blank = record_event(
        _event(detail="blank-reason", reason="   ", retention="activity"),
        store=store,
    )
    assert "reason" not in blank
    assert "retention" not in blank
    assert set(blank) == {"kind", "actor", "uin", "timestamp", "result", "detail"}

    at_limit = record_event(
        _event(
            checkId="c" * 64,
            browser="b" * 200,
            reason="r" * 240,
            network="2001:db8::1",
        ),
        store=store,
    )
    assert at_limit["checkId"] == "c" * 64
    assert at_limit["browser"] == "b" * 200
    assert at_limit["reason"] == "r" * 240
    assert at_limit["network"] == "2001:db8::1"
    assert list_events(store=store)[-1] == at_limit


def test_empty_uin_is_stored_for_failure_and_rejected_for_success() -> None:
    store = MemoryStore()
    stored = record_event(
        _event(
            kind="camera",
            result="failure",
            uin="",
            detail="camera unavailable",
            reasonCode="camera_unavailable",
        ),
        store=store,
    )
    assert "uin" in stored
    assert stored["uin"] == ""
    assert stored["kind"] == "camera"
    assert '"uin":""' in store.lines[0]
    assert list_events(store=store) == [stored]

    with pytest.raises(ValueError):
        record_event(_event(result="success", uin=""), store=store)
    with pytest.raises(ValueError):
        record_event(_event(result="success", uin="   "), store=store)
    saved = record_event(
        _event(result="success", uin="", event="details_saved", appCode="6AEF41", detail="application saved"),
        store=store,
    )
    assert saved["uin"] == ""
    assert saved["appCode"] == "6AEF41"
    assert saved["event"] == "details_saved"
    assert len(store.lines) == 2
    assert list_events(store=store) == [stored, saved]


def test_bad_reason_code_action_and_forbidden_key_are_rejected() -> None:
    assert REASON_CODES == frozenset(
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
    assert ACTION_CODES == frozenset(
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
    store = MemoryStore()
    with pytest.raises(ValueError, match="reasonCode"):
        record_event(_event(reasonCode="not_me"), store=store)
    with pytest.raises(ValueError, match="action"):
        record_event(_event(action="face_mismatch"), store=store)
    with pytest.raises(ValueError, match="retention"):
        record_event(_event(retention="forever"), store=store)
    with pytest.raises(ValueError, match="boolean"):
        record_event(_event(livenessPassed=1), store=store)
    with pytest.raises(ValueError, match="boolean"):
        record_event(_event(matchPassed=0), store=store)
    with pytest.raises(ValueError, match="finite float"):
        record_event(_event(livenessScore=True), store=store)
    with pytest.raises(ValueError, match="finite float"):
        record_event(_event(matchScore=float("inf")), store=store)
    with pytest.raises(ValueError, match="IP address"):
        record_event(_event(network="not-an-ip"), store=store)
    with pytest.raises(ValueError):
        record_event(_event(checkId="c" * 65), store=store)
    with pytest.raises(ValueError):
        record_event(_event(browser="b" * 201), store=store)
    with pytest.raises(ValueError):
        record_event(_event(reason="r" * 241), store=store)

    event = _event(retention="permanent", kind="dispute")
    event["password"] = SECRET
    with pytest.raises(ValueError, match="forbidden field"):
        record_event(event, store=store)
    event = _event(retention="permanent")
    event["faceImage"] = FACE
    with pytest.raises(ValueError, match="forbidden field"):
        record_event(event, store=store)
    event = _event(retention="permanent")
    event["token"] = TOKEN
    with pytest.raises(ValueError, match="forbidden field"):
        record_event(event, store=store)
    assert store.lines == []
    assert list_events(store=store) == []


def test_permanent_row_does_not_contain_face_image_password_or_token() -> None:
    store = MemoryStore()
    stored = record_event(
        _permanent_event(action="not_me", reasonCode="unknown_uin", result="failure"),
        store=store,
    )
    blob = store.lines[0]
    for needle in (SECRET, FACE, TOKEN, "password", "faceImage", "face_image", "embedding"):
        assert needle not in blob
    assert "token" not in blob.lower()
    assert stored["retention"] == "permanent"
    assert "password" not in stored
    assert "faceImage" not in stored
    assert "token" not in stored
    assert list_events(store=store) == [stored]

    for key, value in (("password", SECRET), ("faceImage", FACE), ("token", TOKEN), ("image", FACE)):
        event = _permanent_event()
        event[key] = value
        with pytest.raises(ValueError, match="forbidden field") as caught:
            record_event(event, store=store)
        message = str(caught.value)
        assert SECRET not in message
        assert FACE not in message
        assert TOKEN not in message
    assert len(store.lines) == 1


_PLAIN_KEYS = {"kind", "actor", "uin", "timestamp", "result", "detail"}

_CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.6099.210 Mobile Safari/537.36"
)
_SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)
_CHROME_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_FIREFOX_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
)
_SAFARI_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
)
_EDGE_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)


def test_catalog_reason_codes_round_trip_and_plain_record_stays_six_keys() -> None:
    store = MemoryStore()
    matched = record_event(
        _event(
            kind="authenticate",
            result="failure",
            detail="no match",
            reasonCode="MATCH-1",
        ),
        store=store,
    )
    turned = record_event(
        _event(
            kind="authenticate",
            result="failure",
            detail="head turn",
            reasonCode="PAD-1",
        ),
        store=store,
    )
    plain = record_event(_event(detail="plain"), store=store)

    assert matched["reasonCode"] == "MATCH-1"
    assert turned["reasonCode"] == "PAD-1"
    assert set(plain) == _PLAIN_KEYS
    assert "reasonCode" not in plain
    assert list_events(store=store) == [matched, turned, plain]
    assert "MATCH-1" not in REASON_CODES
    assert "face_mismatch" in REASON_CODES


def test_project_for_citizen_hides_network_and_uses_catalog_sentence() -> None:
    raw_agent = _CHROME_ANDROID
    stored = record_event(
        _event(
            kind="authenticate",
            event="authenticate",
            result="failure",
            actor="officer-ada",
            detail="officer note about the scan",
            reason="free-text-mismatch-note",
            reasonCode="MATCH-1",
            network="198.51.100.14",
            source="198.51.100.14 · Chrome on Android",
            browser=raw_agent,
            eventId="evt-match-1",
            checkId="chk-match-1",
            matchScore=0.12,
            livenessScore=0.34,
            uin="111111111111",
        ),
        store=MemoryStore(),
    )
    view = project_for_citizen(stored)
    assert view == {
        "eventId": "evt-match-1",
        "checkId": "chk-match-1",
        "time": stored["timestamp"],
        "event": "authenticate",
        "result": "failure",
        "message": "This face did not match the ID.",
        "device": "Chrome on Android",
    }
    blob = json.dumps(view)
    for hidden in (
        "198.51.100.14",
        "officer-ada",
        "officer note",
        "free-text-mismatch-note",
        raw_agent,
        "Pixel",
        "120.0.6099.210",
        "111111111111",
        "0.12",
        "0.34",
    ):
        assert hidden not in blob
    for hidden_key in ("network", "source", "actor", "detail", "reason", "uin", "browser"):
        assert hidden_key not in view
    assert view["device"] != raw_agent

    passed = project_for_citizen(
        _event(kind="authenticate", result="success", detail="ok", browser="")
    )
    assert passed["message"] == "Your face check passed"
    assert passed["device"] == ""
    assert "eventId" not in passed
    assert "checkId" not in passed

    created = project_for_citizen(_event(kind="enroll", result="success"))
    assert created["message"] == "Your ID was created"
    reported = project_for_citizen(
        _event(kind="dispute", event="activity_reported", result="success")
    )
    assert reported["event"] == "activity_reported"
    assert reported["message"] == "You reported this check"
    notified = project_for_citizen(
        _event(kind="operator", event="notification_sent", result="success")
    )
    assert notified["message"] == citizen_message("LIMIT-1")
    assert notified["message"] == (
        "An officer needs to check this. Visit the office with your code."
    )
    unnamed = project_for_citizen(
        _event(kind="authenticate", result="failure", reasonCode="face_mismatch")
    )
    assert unnamed["message"] == ""
    sourced = project_for_citizen(
        _event(
            kind="authenticate",
            result="failure",
            source="203.0.113.8 · Safari on iPhone",
        )
    )
    assert sourced["device"] == ""
    assert "203.0.113.8" not in json.dumps(sourced)


def test_tries_used_counts_only_try_reason_codes() -> None:
    uin = "123456789012"
    other = "999999999999"

    def row(**overrides: object) -> dict:
        base: dict = {
            "kind": "authenticate",
            "event": "authenticate",
            "actor": "citizen",
            "uin": uin,
            "result": "failure",
            "timestamp": 1.0,
            "detail": "",
        }
        base.update(overrides)
        return base

    records = [
        row(reasonCode="FACE-3"),
        row(reasonCode="PAD-1"),
        row(reasonCode="PAD-2"),
        row(reasonCode="MATCH-1"),
        row(reasonCode="CAM-1"),
        row(reasonCode="MATCH-2"),
        row(reasonCode="SESSION-1"),
        row(reasonCode="SYS-1"),
        row(reasonCode="LIMIT-1"),
        row(reasonCode="face_mismatch"),
        row(reasonCode="MATCH-1", result="success"),
        row(kind="enroll", event="enroll", reasonCode="MATCH-1"),
        row(reasonCode="MATCH-1", uin=other),
        row(kind="camera", event="authenticate", reasonCode="PAD-1"),
    ]
    assert tries_used(records, uin) == 5
    assert tries_used(records, other) == 1
    assert tries_used(records, "000000000000") == 0
    assert TRY_CODES == frozenset({"FACE-3", "PAD-1", "PAD-2", "MATCH-1"})


def test_search_events_filters_uin_app_code_session_and_utc_date() -> None:
    on_day = datetime(2026, 11, 24, 0, 30, tzinfo=timezone.utc).timestamp()
    # 20:00 UTC is the next calendar day in UTC+7, and still 23 Nov in UTC.
    previous_evening = datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc).timestamp()
    records = [
        {
            "uin": "111",
            "appCode": "6AEF41",
            "sessionId": "sess-a",
            "timestamp": on_day,
            "detail": "first",
        },
        {
            "uin": "222",
            "appCode": "6AEF41",
            "sessionId": "sess-a",
            "timestamp": on_day,
            "detail": "other-uin",
        },
        {
            "uin": "111",
            "appCode": "BBBBBB",
            "sessionId": "sess-a",
            "timestamp": on_day,
            "detail": "other-app",
        },
        {
            "uin": "111",
            "appCode": "6AEF41",
            "sessionId": "sess-b",
            "timestamp": previous_evening,
            "detail": "previous-utc-day",
        },
        {
            "uin": "111",
            "appCode": "6AEF41",
            "sessionId": "sess-a",
            "timestamp": on_day,
            "detail": "again",
        },
    ]
    assert [item["detail"] for item in search_events(records, uin="111")] == [
        "first",
        "other-app",
        "previous-utc-day",
        "again",
    ]
    assert [item["detail"] for item in search_events(records, app_code="6AEF41")] == [
        "first",
        "other-uin",
        "previous-utc-day",
        "again",
    ]
    assert [item["detail"] for item in search_events(records, session_id="sess-a")] == [
        "first",
        "other-uin",
        "other-app",
        "again",
    ]
    assert [item["detail"] for item in search_events(records, on_date="2026-11-24")] == [
        "first",
        "other-uin",
        "other-app",
        "again",
    ]
    assert [item["detail"] for item in search_events(records, on_date="2026-11-23")] == [
        "previous-utc-day",
    ]
    narrowed = search_events(
        records,
        uin="111",
        app_code="6AEF41",
        session_id="sess-a",
        on_date="2026-11-24",
    )
    assert [item["detail"] for item in narrowed] == ["first", "again"]
    assert search_events(records, uin="", app_code=None, session_id="", on_date=None) == records


def test_user_action_fields_round_trip_and_are_absent_when_omitted() -> None:
    assert EVENTS == frozenset(
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
    store = MemoryStore()
    supplied = {
        "eventId": "a7f3c2e1",
        "event": "uin_locked",
        "appCode": "6AEF41",
        "sessionId": "11111111-2222-3333-4444-555555555555",
        "source": "203.0.113.10 · Chrome on Android",
        "service": "portal",
        "requestId": "r-81e",
    }
    stored = record_event(
        _event(kind="operator", actor="officer-a", detail="locked", **supplied),
        store=store,
    )
    for key, value in supplied.items():
        assert stored[key] == value
    assert list_events(store=store) == [stored]

    plain = record_event(_event(detail="no-optionals"), store=store)
    assert set(plain) == _PLAIN_KEYS
    for key in supplied:
        assert key not in plain
    assert list_events(store=store)[1] == plain
    plain_line = store.lines[1]
    for key in ("eventId", "appCode", "sessionId", "source", "service", "requestId"):
        assert key not in plain_line
    assert '"event"' not in plain_line

    at_limit = record_event(
        _event(
            eventId="e" * 64,
            event="marked_checked",
            appCode="a" * 16,
            sessionId="s" * 64,
            source="x" * 120,
            service="p" * 32,
            requestId="r" * 64,
        ),
        store=store,
    )
    assert at_limit["eventId"] == "e" * 64
    assert at_limit["appCode"] == "a" * 16
    assert at_limit["sessionId"] == "s" * 64
    assert at_limit["source"] == "x" * 120
    assert at_limit["service"] == "p" * 32
    assert at_limit["requestId"] == "r" * 64
    assert list_events(store=store)[-1] == at_limit

    rejected = MemoryStore()
    for overrides in (
        {"eventId": "e" * 65},
        {"appCode": "a" * 17},
        {"sessionId": "s" * 65},
        {"source": "x" * 121},
        {"service": "p" * 33},
        {"requestId": "r" * 65},
        {"eventId": ""},
        {"event": "credential"},
        {"reasonCode": "MATCH-9"},
    ):
        with pytest.raises(ValueError):
            record_event(_event(**overrides), store=rejected)
    assert rejected.lines == []


def test_reason_catalog_and_rough_device_labels() -> None:
    assert len(REASON_CATALOG) == 25
    assert CODES == frozenset(REASON_CATALOG)
    assert TRY_CODES <= CODES
    for code, (officer, citizen, flag) in REASON_CATALOG.items():
        assert officer_text(code) == officer
        assert citizen_message(code) == citizen
        assert officer != ""
        assert citizen != ""
        assert uses_try(code) is flag
    assert officer_text("nope") == ""
    assert citizen_message("face_mismatch") == ""
    assert uses_try("nope") is False
    assert uses_try("CAM-1") is False
    assert uses_try("MATCH-1") is True
    assert rough_device(_CHROME_ANDROID) == "Chrome on Android"
    assert rough_device(_SAFARI_IPHONE) == "Safari on iPhone"
    assert rough_device(_CHROME_DESKTOP) == "Chrome"
    assert rough_device(_FIREFOX_DESKTOP) == "Firefox"
    assert rough_device(_SAFARI_MAC) == "Safari"
    assert rough_device(_EDGE_DESKTOP) == "Edge"
    assert rough_device("curl/8.0") == "unknown"
    assert rough_device("203.0.113.5") == "unknown"
    assert rough_device("") == "unknown"
    labeled = rough_device(_CHROME_DESKTOP + " 203.0.113.5")
    assert labeled == "Chrome"
    assert "203.0.113.5" not in labeled
    assert _CHROME_DESKTOP not in labeled
