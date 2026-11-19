"""Draft applications: a code and demographics, not an IDRepo identity."""

import json
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from project.web import app
from register_id.application import APPLICATION_TTL_SECONDS, CODE_ALPHABET
from register_id.application_store import (
    ApplicationStoreError,
    MemoryApplicationStore,
    RedisApplicationStore,
    get_application_store,
    in_memory_records,
)
from register_id.idrepo_client import IDRepoClient
from register_id.tests.challenge_store_test import FakeRedis, UnavailableRedis

client = TestClient(app)

_IDENTITY_KEYS = {"id", "guid", "uuid"}


@pytest.fixture
def applications(monkeypatch: pytest.MonkeyPatch) -> MemoryApplicationStore:
    store = MemoryApplicationStore()
    monkeypatch.setattr("register_id.api.get_application_store", lambda: store)
    return store


def _consent(**overrides: object) -> dict:
    payload = {
        "accepted": True,
        "purpose": "Store a face template for later identity checks",
        "acceptedAt": 1_763_000_000.0,
        "language": "eng",
    }
    payload.update(overrides)
    return payload


def _payload(**overrides: object) -> dict:
    payload = {
        "fullName": " Ada Lovelace ",
        "gender": " female ",
        "dateOfBirth": "1815-12-10",
        "email": " ada@example.com ",
        "researchOptIn": True,
        "reason": "no-camera",
        "consent": _consent(),
    }
    payload.update(overrides)
    return payload


def _create(body: dict | None = None):
    return client.post("/api/applications", json=_payload() if body is None else body)


def _set_store_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APPLICATION_STORE_KEY", key)
    return key


def test_create_stores_a_draft_and_hides_the_guid(applications: MemoryApplicationStore) -> None:
    response = _create()
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"code", "expiresAt", "expiresInSeconds"}
    assert _IDENTITY_KEYS.isdisjoint(body)
    assert body["expiresInSeconds"] == 2_592_000
    assert body["expiresInSeconds"] == APPLICATION_TTL_SECONDS
    assert len(body["code"]) == 6
    assert set(body["code"]) <= set(CODE_ALPHABET)

    assert len(applications.records) == 1
    stored = next(iter(applications.records.values()))
    assert stored["id"] == applications.codes[body["code"]]
    uuid.UUID(stored["id"])
    assert stored["id"] not in response.text
    assert stored["code"] == body["code"]
    assert stored["fullName"] == "Ada Lovelace"
    assert stored["gender"] == "female"
    assert stored["dateOfBirth"] == "1815-12-10"
    assert stored["email"] == "ada@example.com"
    assert stored["researchOptIn"] is True
    assert stored["reason"] == "no-camera"
    assert stored["consent"] == _consent()
    assert set(stored) == {
        "id",
        "code",
        "fullName",
        "gender",
        "dateOfBirth",
        "email",
        "researchOptIn",
        "reason",
        "consent",
        "createdAt",
        "expiresAt",
    }
    assert stored["expiresAt"] == stored["createdAt"] + APPLICATION_TTL_SECONDS
    assert body["expiresAt"] == pytest.approx(stored["expiresAt"], abs=1)


@pytest.mark.parametrize("reason", ["no-camera", "camera-quality"])
def test_both_reasons_are_accepted(applications: MemoryApplicationStore, reason: str) -> None:
    response = _create(_payload(reason=reason))
    assert response.status_code == 201
    stored = next(iter(applications.records.values()))
    assert stored["reason"] == reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"consent": _consent(accepted=False)},
        {"reason": "no-light"},
        {"email": "ada.example.com"},
        {"email": "ada@example"},
        {"photo": "data:image/jpeg;base64,abcd"},
        {"fullName": "   "},
        {"dateOfBirth": "10-12-1815"},
    ],
)
def test_invalid_application_is_422(applications: MemoryApplicationStore, overrides: dict) -> None:
    response = _create(_payload(**overrides))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
    assert applications.records == {}


def test_two_creates_receive_different_codes(applications: MemoryApplicationStore) -> None:
    first = _create()
    second = _create(_payload(fullName="Grace Hopper", email="grace@example.com"))
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["code"] != second.json()["code"]
    assert len(applications.records) == 2


def test_code_collision_retries(applications: MemoryApplicationStore, monkeypatch: pytest.MonkeyPatch) -> None:
    taken = "222222"
    applications.save(
        {
            "id": str(uuid.uuid4()),
            "code": taken,
            "expiresAt": 10_000_000_000.0,
        },
        APPLICATION_TTL_SECONDS,
        now=0,
    )
    drawn = iter(taken + "333333")

    def _choice(alphabet: str) -> str:
        assert alphabet == CODE_ALPHABET
        return next(drawn)

    monkeypatch.setattr("register_id.application.secrets.choice", _choice)
    response = _create()
    assert response.status_code == 201
    assert response.json()["code"] == "333333"
    assert applications.codes["333333"] != applications.codes[taken]


def test_code_collision_stops_after_eight(
    applications: MemoryApplicationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    applications.save(
        {"id": str(uuid.uuid4()), "code": "222222", "expiresAt": 10_000_000_000.0},
        APPLICATION_TTL_SECONDS,
        now=0,
    )
    calls = {"n": 0}

    def _choice(alphabet: str) -> str:
        del alphabet
        calls["n"] += 1
        return "2"

    monkeypatch.setattr("register_id.application.secrets.choice", _choice)
    response = _create()
    assert response.status_code == 503
    assert isinstance(response.json()["detail"], str)
    assert calls["n"] == 8 * 6
    assert len(applications.records) == 1


def test_redis_sets_both_keys_with_grace_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_store_key(monkeypatch)
    fake = FakeRedis()
    store = RedisApplicationStore(client=fake)
    monkeypatch.setattr(
        "register_id.api.get_application_store",
        lambda: store,
    )
    response = _create()
    assert response.status_code == 201
    code = response.json()["code"]
    code_key = f"register-id:application-code:{code}"
    guid = fake.values[code_key]
    record_key = f"register-id:application:{guid}"
    assert fake.ttls[code_key] == APPLICATION_TTL_SECONDS + 60
    assert fake.ttls[record_key] == APPLICATION_TTL_SECONDS + 60
    stored = store.load(guid)
    assert stored is not None
    assert stored["id"] == guid
    assert stored["code"] == code
    assert stored["email"] == "ada@example.com"
    assert "id" not in response.json()


def test_redis_skips_a_taken_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_store_key(monkeypatch)
    fake = FakeRedis()
    taken = "222222"
    fake.values[f"register-id:application-code:{taken}"] = "already-stored"
    fake.ttls[f"register-id:application-code:{taken}"] = APPLICATION_TTL_SECONDS
    store = RedisApplicationStore(client=fake)
    monkeypatch.setattr(
        "register_id.api.get_application_store",
        lambda: store,
    )
    drawn = iter(taken + "4AE27L")

    def _choice(alphabet: str) -> str:
        assert alphabet == CODE_ALPHABET
        return next(drawn)

    monkeypatch.setattr("register_id.application.secrets.choice", _choice)
    response = _create()
    assert response.status_code == 201
    assert response.json()["code"] == "4AE27L"
    assert fake.values[f"register-id:application-code:{taken}"] == "already-stored"
    guid = fake.values["register-id:application-code:4AE27L"]
    stored = store.load(guid)
    assert stored is not None
    assert stored["code"] == "4AE27L"
    assert set("4AE27L") <= set(CODE_ALPHABET)
    assert set("4AE27L").isdisjoint("01OI")


def test_redis_connection_error_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_store_key(monkeypatch)
    secret = "ada@example.com"
    store = RedisApplicationStore(client=UnavailableRedis())
    with pytest.raises(ApplicationStoreError, match="cannot reach Redis") as raised:
        store.save(
            {"id": "guid", "code": "234567", "email": secret, "expiresAt": 1.0},
            APPLICATION_TTL_SECONDS,
        )
    assert secret not in str(raised.value)
    assert all(secret not in json.dumps(row) for row in in_memory_records().values())

    monkeypatch.setattr("register_id.api.get_application_store", lambda: store)
    response = _create()
    assert response.status_code == 503
    assert isinstance(response.json()["detail"], str)
    assert secret not in response.json()["detail"]


def test_get_application_store_reads_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("APPLICATION_STORE_KEY", raising=False)
    assert isinstance(get_application_store(), MemoryApplicationStore)

    _set_store_key(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://:secret@127.0.0.1:6390/0")
    selected = get_application_store()
    assert isinstance(selected, RedisApplicationStore)
    assert not isinstance(selected, MemoryApplicationStore)


def test_redis_save_stores_ciphertext_and_load_returns_demographics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_store_key(monkeypatch)
    fake = FakeRedis()
    store = RedisApplicationStore(client=fake)
    record = {
        "id": "guid-ada",
        "code": "234567",
        "fullName": "Ada Lovelace",
        "gender": "female",
        "dateOfBirth": "1815-12-10",
        "email": "ada@example.com",
        "researchOptIn": True,
        "reason": "no-camera",
        "consent": _consent(),
        "createdAt": 1.0,
        "expiresAt": 2.0,
    }
    assert store.save(record, ttl_seconds=30, now=1.0)
    raw = fake.values["register-id:application:guid-ada"]
    assert "ada@example.com" not in raw
    assert "Ada Lovelace" not in raw
    assert "1815-12-10" not in raw
    assert "female" not in raw
    assert "researchOptIn" not in raw
    assert "Store a face template" not in raw
    assert fake.values["register-id:application-code:234567"] == "guid-ada"

    loaded = store.load("guid-ada")
    assert loaded is not None
    assert loaded["email"] == "ada@example.com"
    assert loaded["fullName"] == "Ada Lovelace"
    assert loaded["dateOfBirth"] == "1815-12-10"
    assert loaded["gender"] == "female"
    assert loaded["researchOptIn"] is True
    assert loaded["consent"] == _consent()


def test_missing_or_invalid_store_key_does_not_write_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_email = "ada@example.com"
    secret_name = "Ada Lovelace"
    secret_dob = "1815-12-10"
    record = {
        "id": "guid-ada",
        "code": "234567",
        "fullName": secret_name,
        "gender": "female",
        "dateOfBirth": secret_dob,
        "email": secret_email,
        "researchOptIn": True,
        "consent": {"accepted": True, "purpose": "Store a face template"},
        "expiresAt": 1.0,
    }

    monkeypatch.delenv("APPLICATION_STORE_KEY", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6391/15")
    fake = FakeRedis()
    with pytest.raises(ApplicationStoreError, match="APPLICATION_STORE_KEY"):
        RedisApplicationStore(client=fake).save(record, ttl_seconds=30)
    assert fake.values == {}
    blob = json.dumps(fake.values)
    assert secret_email not in blob
    assert secret_name not in blob
    assert secret_dob not in blob
    with pytest.raises(ApplicationStoreError, match="APPLICATION_STORE_KEY"):
        get_application_store()
    assert all(secret_email not in json.dumps(row) for row in in_memory_records().values())

    bad_key = "not-a-fernet-key"
    monkeypatch.setenv("APPLICATION_STORE_KEY", bad_key)
    with pytest.raises(ApplicationStoreError, match="valid Fernet key") as raised:
        RedisApplicationStore(client=fake).save(record, ttl_seconds=30)
    assert bad_key not in str(raised.value)
    assert secret_email not in str(raised.value)
    assert fake.values == {}


def test_creating_an_application_does_not_write_idrepo(
    applications: MemoryApplicationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _add_identity(self: IDRepoClient, *args: object, **kwargs: object) -> bool:
        del self, args, kwargs
        calls.append("add_identity")
        return True

    def _store_identity(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("_store_identity")

    monkeypatch.setattr(IDRepoClient, "add_identity", _add_identity)
    monkeypatch.setattr("register_id.api._store_identity", _store_identity)

    response = _create()
    assert response.status_code == 201
    assert calls == []
    assert len(applications.records) == 1

    idrepo = IDRepoClient(base_url="http://127.0.0.1:9", enable_inprocess_fallback=True)
    assert idrepo.get_identity("draft-without-uin") is None
