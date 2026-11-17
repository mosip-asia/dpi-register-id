"""Keycloak provisioning client tests. HTTP is mocked; no live server is used."""

import importlib
import inspect
import logging
from typing import Any

import pytest
import requests

import register_id.keycloak as keycloak
from register_id.models import CredentialResponse

CITIZEN_PASSWORD = "citizen-only-secret"
ADMIN_PASSWORD = "admin-only-secret"
ADMIN_TOKEN = "admin-token-do-not-log"
UIN = "1234567890"
EMAIL = "ada@example.com"
FULL_NAME = "Ada Lovelace"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        text: str = "",
        json_error: bool = False,
    ):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("not json")
        if self._payload is None:
            return {}
        return self._payload


def make_client(**overrides: str) -> keycloak.KeycloakBridgeClient:
    settings = {
        "base_url": "http://keycloak.test/auth",
        "admin_user": "kc-admin",
        "admin_pass": ADMIN_PASSWORD,
        "realm": "mosip",
    }
    settings.update(overrides)
    return keycloak.KeycloakBridgeClient(**settings)


def user_record(
    uin_attribute: Any = None,
    *,
    include_attributes: bool = True,
    user_id: str = "user-1",
    username: str = "ada",
) -> dict[str, Any]:
    record: dict[str, Any] = {"id": user_id, "username": username}
    if include_attributes:
        attributes: dict[str, Any] = {}
        if uin_attribute is not None:
            attributes["uin"] = uin_attribute
        record["attributes"] = attributes
    return record


def install_create(monkeypatch: pytest.MonkeyPatch, status: int, exc: Exception | None = None):
    def post(url: str, data: dict | None = None, json: dict | None = None, headers=None, timeout=None):
        if url.endswith("/protocol/openid-connect/token"):
            echoed = f"{ADMIN_PASSWORD} {ADMIN_TOKEN} {CITIZEN_PASSWORD}"
            return FakeResponse(200, {"access_token": ADMIN_TOKEN}, text=echoed)
        if url.endswith("/users"):
            if exc is not None:
                raise exc
            return FakeResponse(status, text=f"create failed {CITIZEN_PASSWORD} {ADMIN_TOKEN}")
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(keycloak.requests, "post", post)
    return post


def test_provision_result_is_boolean_compatible():
    created = keycloak.ProvisionResult(True, True, "created")
    failed = keycloak.ProvisionResult(False, False, "admin token unavailable")

    assert bool(created) is True
    assert bool(failed) is False
    assert created.ok is True and created.created is True and created.detail == "created"
    assert failed.ok is False and failed.created is False

    accepted = CredentialResponse(status="SUCCESS", uin=UIN, keycloakProvisioned=created)
    rejected = CredentialResponse(status="SUCCESS", uin=UIN, keycloakProvisioned=failed)
    assert accepted.keycloakProvisioned is True
    assert rejected.keycloakProvisioned is False


def test_create_sends_password_only_as_credential_and_omits_biometrics(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def post(url: str, data=None, json=None, headers=None, timeout=None):
        calls.append((url, {"data": data, "json": json, "headers": headers}))
        if url.endswith("/protocol/openid-connect/token"):
            return FakeResponse(200, {"access_token": ADMIN_TOKEN})
        return FakeResponse(201)

    monkeypatch.setattr(keycloak.requests, "post", post)
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)

    assert result.ok is True
    assert result.created is True
    assert result.detail == "created"
    assert bool(result) is True

    token_call = calls[0][1]
    assert token_call["data"]["password"] == ADMIN_PASSWORD
    assert CITIZEN_PASSWORD not in str(token_call["data"])

    create_call = calls[1][1]
    payload = create_call["json"]
    assert payload["username"] == "ada"
    assert payload["firstName"] == "Ada"
    assert payload["lastName"] == "Lovelace"
    assert payload["attributes"] == {"uin": [UIN]}
    assert "individualBiometrics" not in payload["attributes"]
    assert "individualBiometrics" not in str(payload)
    assert payload["credentials"] == [
        {"type": "password", "value": CITIZEN_PASSWORD, "temporary": False}
    ]
    assert create_call["headers"]["Authorization"] == f"Bearer {ADMIN_TOKEN}"
    leaked = [
        key
        for key, value in _scalar_items(payload)
        if value == CITIZEN_PASSWORD and key != "value"
    ]
    assert leaked == []


@pytest.mark.parametrize("status", [200, 204, 400, 401, 403, 500])
def test_non_201_and_non_409_create_status_fails(monkeypatch, status):
    install_create(monkeypatch, status)
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.created is False
    assert result.detail == f"keycloak status {status}"
    assert bool(result) is False


def test_network_error_on_create_fails(monkeypatch):
    install_create(monkeypatch, 201, exc=requests.ConnectionError("down"))
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.created is False
    assert result.detail == "network error"


def test_missing_admin_password_does_not_call_keycloak(monkeypatch):
    def post(*args, **kwargs):
        raise AssertionError("token request must not run without an admin password")

    monkeypatch.setattr(keycloak.requests, "post", post)
    result = make_client(admin_pass="").provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.created is False
    assert result.detail == "admin token unavailable"
    assert bool(result) is False


def test_admin_password_default_is_not_hardcoded(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ADMIN_PASSWORD", raising=False)
    reloaded = importlib.reload(keycloak)
    assert reloaded.KEYCLOAK_ADMIN_PASSWORD == ""
    admin_pass_default = inspect.signature(reloaded.KeycloakBridgeClient.__init__).parameters[
        "admin_pass"
    ].default
    assert admin_pass_default == ""


@pytest.mark.parametrize(
    ("token_response", "detail"),
    [
        (FakeResponse(401, {"error": "invalid_grant"}, text=ADMIN_PASSWORD), "admin token unavailable"),
        (FakeResponse(200, {"token_type": "Bearer"}), "admin token unavailable"),
        (FakeResponse(200, json_error=True), "admin token unavailable"),
    ],
)
def test_missing_admin_token_fails(monkeypatch, token_response, detail):
    def post(url, data=None, json=None, headers=None, timeout=None):
        assert url.endswith("/protocol/openid-connect/token")
        return token_response

    monkeypatch.setattr(keycloak.requests, "post", post)
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.detail == detail


def test_token_network_error_fails(monkeypatch):
    def post(url, data=None, json=None, headers=None, timeout=None):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(keycloak.requests, "post", post)
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.detail == "admin token unavailable"


def test_409_same_uin_resets_password_and_is_not_created(monkeypatch):
    calls: list[str] = []

    def post(url, data=None, json=None, headers=None, timeout=None):
        calls.append(f"POST {url}")
        if url.endswith("/protocol/openid-connect/token"):
            assert data["password"] == ADMIN_PASSWORD
            assert CITIZEN_PASSWORD not in str(data)
            return FakeResponse(200, {"access_token": ADMIN_TOKEN})
        assert json["credentials"][0]["value"] == CITIZEN_PASSWORD
        return FakeResponse(409, text="User exists with same username")

    def get(url, params=None, headers=None, timeout=None):
        calls.append(f"GET {url}")
        assert params == {"username": "ada", "exact": "true"}
        assert CITIZEN_PASSWORD not in url
        assert CITIZEN_PASSWORD not in str(params)
        assert headers["Authorization"] == f"Bearer {ADMIN_TOKEN}"
        return FakeResponse(200, [user_record([UIN])])

    def put(url, json=None, headers=None, timeout=None):
        calls.append(f"PUT {url}")
        assert url.endswith("/users/user-1/reset-password")
        assert json == {"type": "password", "value": CITIZEN_PASSWORD, "temporary": False}
        assert CITIZEN_PASSWORD not in url
        assert headers["Authorization"] == f"Bearer {ADMIN_TOKEN}"
        return FakeResponse(204)

    monkeypatch.setattr(keycloak.requests, "post", post)
    monkeypatch.setattr(keycloak.requests, "get", get)
    monkeypatch.setattr(keycloak.requests, "put", put)

    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is True
    assert result.created is False
    assert result.detail == "password reset"
    assert bool(result) is True
    assert calls == [
        "POST http://keycloak.test/auth/realms/master/protocol/openid-connect/token",
        "POST http://keycloak.test/auth/admin/realms/mosip/users",
        "GET http://keycloak.test/auth/admin/realms/mosip/users",
        "PUT http://keycloak.test/auth/admin/realms/mosip/users/user-1/reset-password",
    ]


@pytest.mark.parametrize(
    ("record", "detail"),
    [
        (user_record(["9999999999"]), "existing user uin mismatch"),
        (user_record([UIN, "9999999999"]), "existing user uin mismatch"),
        (user_record(None), "existing user uin missing"),
        (user_record([]), "existing user uin missing"),
        (user_record([""]), "existing user uin missing"),
        (user_record(include_attributes=False), "existing user uin missing"),
    ],
)
def test_409_without_matching_uin_is_not_success(monkeypatch, record, detail):
    put_called = False

    def post(url, data=None, json=None, headers=None, timeout=None):
        if url.endswith("/protocol/openid-connect/token"):
            return FakeResponse(200, {"access_token": ADMIN_TOKEN})
        return FakeResponse(409)

    def get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, [record])

    def put(*args, **kwargs):
        nonlocal put_called
        put_called = True
        raise AssertionError("password must not be reset when the UIN does not match")

    monkeypatch.setattr(keycloak.requests, "post", post)
    monkeypatch.setattr(keycloak.requests, "get", get)
    monkeypatch.setattr(keycloak.requests, "put", put)

    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False
    assert result.created is False
    assert result.detail == detail
    assert put_called is False


def test_409_string_uin_attribute_matches(monkeypatch):
    def post(url, data=None, json=None, headers=None, timeout=None):
        if url.endswith("/protocol/openid-connect/token"):
            return FakeResponse(200, {"access_token": ADMIN_TOKEN})
        return FakeResponse(409)

    def get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, [user_record(f"  {UIN}  ")])

    def put(url, json=None, headers=None, timeout=None):
        assert json["value"] == CITIZEN_PASSWORD
        return FakeResponse(204)

    monkeypatch.setattr(keycloak.requests, "post", post)
    monkeypatch.setattr(keycloak.requests, "get", get)
    monkeypatch.setattr(keycloak.requests, "put", put)

    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is True
    assert result.created is False


def test_409_lookup_or_reset_failure_is_not_success(monkeypatch):
    cases = [
        ("lookup-status", FakeResponse(500, text=CITIZEN_PASSWORD), None, "user lookup failed"),
        ("lookup-empty", FakeResponse(200, []), None, "existing user not found"),
        ("lookup-error", requests.ConnectionError("down"), None, "network error"),
        ("reset-status", FakeResponse(200, [user_record([UIN])]), FakeResponse(400, text=CITIZEN_PASSWORD), "password reset failed"),
        ("reset-error", FakeResponse(200, [user_record([UIN])]), requests.Timeout("slow"), "network error"),
    ]

    for name, lookup, reset, detail in cases:
        def post(url, data=None, json=None, headers=None, timeout=None):
            if url.endswith("/protocol/openid-connect/token"):
                return FakeResponse(200, {"access_token": ADMIN_TOKEN})
            return FakeResponse(409)

        def get(url, params=None, headers=None, timeout=None):
            if isinstance(lookup, Exception):
                raise lookup
            return lookup

        def put(url, json=None, headers=None, timeout=None):
            if isinstance(reset, Exception):
                raise reset
            return reset

        monkeypatch.setattr(keycloak.requests, "post", post)
        monkeypatch.setattr(keycloak.requests, "get", get)
        monkeypatch.setattr(keycloak.requests, "put", put)
        result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
        assert result.ok is False, name
        assert result.created is False, name
        assert result.detail == detail, name


def test_secrets_are_not_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="register_id.keycloak")

    def post(url, data=None, json=None, headers=None, timeout=None):
        if url.endswith("/protocol/openid-connect/token"):
            return FakeResponse(200, {"access_token": ADMIN_TOKEN}, text=ADMIN_TOKEN)
        return FakeResponse(500, text=f"{CITIZEN_PASSWORD} {ADMIN_TOKEN} {ADMIN_PASSWORD}")

    monkeypatch.setattr(keycloak.requests, "post", post)
    result = make_client().provision_citizen(UIN, FULL_NAME, EMAIL, CITIZEN_PASSWORD)
    assert result.ok is False

    logged = caplog.text
    assert CITIZEN_PASSWORD not in logged
    assert ADMIN_PASSWORD not in logged
    assert ADMIN_TOKEN not in logged


def _scalar_items(value: Any, key: str = ""):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _scalar_items(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_items(child, key)
    else:
        yield key, value
