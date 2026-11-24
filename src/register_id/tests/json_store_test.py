"""Locks, staff, and activity grants: Redis, or a file only when opted in."""

import tempfile
from pathlib import Path

import pytest
import redis

from register_id.activity_grant import issue_grant
from register_id.locks import set_locked
from register_id.staff import add_member


class DownRedis:
    def get(self, key: str) -> str | None:
        raise redis.ConnectionError("redis unavailable")

    def set(self, key: str, value: str) -> bool:
        raise redis.ConnectionError("redis unavailable")

    def close(self) -> None:
        return None


def _use_each_store() -> tuple[str, str]:
    set_locked("100", True)
    member = add_member("Desk Officer", "officer.store@register.test", "officer")
    return member["token"], issue_grant("100")


def test_unset_redis_url_does_not_write_json_stores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("FILE_STORE", raising=False)
    monkeypatch.setenv("AUDIT_BACKEND", "file")
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))

    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        set_locked("100", True)
    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        add_member("Desk Officer", "officer.store@register.test", "officer")
    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        issue_grant("100")

    assert not log_dir.exists()
    assert not (temp_root / "register-id").exists()


def test_file_store_opt_in_writes_under_log_dir_or_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("FILE_STORE", "1")
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    staff_token, grant_token = _use_each_store()
    locks = (log_dir / "locks.json").read_text(encoding="utf-8")
    staff = (log_dir / "staff.json").read_text(encoding="utf-8")
    grants = (log_dir / "activity-grants.json").read_text(encoding="utf-8")
    assert "100" in locks
    assert "officer.store@register.test" in staff
    assert staff_token not in staff
    assert grant_token not in grants

    monkeypatch.delenv("LOG_DIR", raising=False)
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp_root))
    set_locked("200", True)
    stored = temp_root / "register-id" / "locks.json"
    assert stored.is_file()
    assert "200" in stored.read_text(encoding="utf-8")


def test_redis_down_does_not_write_json_stores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("FILE_STORE", "1")
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: DownRedis())

    with pytest.raises(redis.ConnectionError):
        set_locked("100", True)
    with pytest.raises(redis.ConnectionError):
        add_member("Desk Officer", "officer.store@register.test", "officer")
    with pytest.raises(redis.ConnectionError):
        issue_grant("100")

    assert list(tmp_path.iterdir()) == []
