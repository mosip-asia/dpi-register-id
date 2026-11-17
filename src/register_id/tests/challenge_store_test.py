import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from register_id.challenge_store import (
    ChallengeStoreError,
    MemoryChallengeStore,
    RedisChallengeStore,
    get_challenge_store,
    in_memory_records,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, name: str, value: str, ex: int | None = None, **kwargs: object) -> bool:
        del kwargs
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def getdel(self, name: str) -> str | None:
        self.ttls.pop(name, None)
        return self.values.pop(name, None)


class UnavailableRedis:
    def set(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisConnectionError("Connection refused")

    def get(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisConnectionError("Connection refused")

    def getdel(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RedisConnectionError("Connection refused")


def test_second_consume_fails_and_peek_does_not_burn() -> None:
    store = MemoryChallengeStore()
    store.issue("sweep_a", {"kind": "sweep"}, 30, now=100)
    assert store.peek("sweep_a")["kind"] == "sweep"
    assert store.peek("sweep_a") is not None

    first = store.consume("sweep_a", now=100)
    assert first.ok is True
    assert first.reason == "ok"
    assert store.peek("sweep_a") is None

    second = store.consume("sweep_a", now=100)
    assert second.ok is False
    assert second.reason == "missing"


def test_expired_challenge_is_consumed_and_then_missing() -> None:
    store = MemoryChallengeStore()
    store.issue("sweep_b", {"kind": "sweep"}, 10, now=50)
    expired = store.consume("sweep_b", now=61)
    assert expired.ok is False
    assert expired.reason == "expired"
    assert store.peek("sweep_b") is None
    again = store.consume("sweep_b", now=61)
    assert again.ok is False
    assert again.reason == "missing"


def test_missing_id_fails() -> None:
    store = MemoryChallengeStore()
    missing = store.consume("no-such-id", now=0)
    assert missing.ok is False
    assert missing.reason == "missing"
    assert store.peek("no-such-id") is None


def test_two_memory_stores_do_not_share_records() -> None:
    left = MemoryChallengeStore()
    right = MemoryChallengeStore()
    left.issue("shared-looking", {"n": 1}, 30, now=0)
    assert right.peek("shared-looking") is None
    assert right.consume("shared-looking", now=0).reason == "missing"
    assert left.consume("shared-looking", now=0).ok is True


def test_redis_store_with_a_fake_client_is_single_use_and_expiring() -> None:
    fake = FakeRedis()
    store = RedisChallengeStore(client=fake)
    store.issue("pad_1", {"targetBlinks": 2}, 10, now=1_000)

    key = "register-id:challenge:pad_1"
    assert key in fake.values
    assert fake.ttls[key] >= 10
    assert "image" not in fake.values[key]

    assert store.peek("pad_1")["targetBlinks"] == 2
    assert store.consume("pad_1", now=1_000).ok is True
    assert store.consume("pad_1", now=1_000).reason == "missing"

    store.issue("pad_2", {"targetBlinks": 2}, 10, now=1_000)
    expired = store.consume("pad_2", now=1_011)
    assert expired.ok is False
    assert expired.reason == "expired"
    assert store.consume("pad_2", now=1_011).reason == "missing"
    assert store.peek("pad_2") is None


def test_redis_outage_raises_and_does_not_fall_back_to_memory() -> None:
    store = RedisChallengeStore(client=UnavailableRedis())
    secret = "image-bytes-must-not-appear"
    with pytest.raises(ChallengeStoreError, match="cannot reach Redis") as issued:
        store.issue("pad_down", {"note": secret}, 10, now=0)
    with pytest.raises(ChallengeStoreError, match="cannot reach Redis") as consumed:
        store.consume("pad_down", now=0)
    assert secret not in str(issued.value)
    assert secret not in str(consumed.value)
    assert "pad_down" not in in_memory_records()


def test_get_challenge_store_reads_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(get_challenge_store(), MemoryChallengeStore)

    monkeypatch.setenv("REDIS_URL", "redis://:secret@127.0.0.1:6390/0")
    selected = get_challenge_store()
    assert isinstance(selected, RedisChallengeStore)
    assert not isinstance(selected, MemoryChallengeStore)
