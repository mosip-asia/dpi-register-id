"""Keycloak authorization-code + PKCE login. HTTP to the token endpoint is mocked."""

import base64
import hashlib
import json
import logging
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from project.web import app
from register_id import oidc
from register_id.oidc import SESSION_COOKIE_NAME

client = TestClient(app)

ACCESS_TOKEN = "keycloak-access-token-do-not-leak"
AUTH_CODE = "keycloak-auth-code-do-not-leak"
CLIENT_SECRET = "keycloak-client-secret-do-not-leak"


@pytest.fixture(autouse=True)
def _isolated_oidc(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak.test/auth")
    monkeypatch.setenv("KEYCLOAK_REALM", "mosip")
    monkeypatch.setenv("KEYCLOAK_OIDC_CLIENT_ID", "register-id-public")
    monkeypatch.setenv("KEYCLOAK_OIDC_REDIRECT_URI", "http://localhost:8000/api/login/callback")
    monkeypatch.delenv("KEYCLOAK_OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("REGISTER_ID_COOKIE_SECURE", raising=False)
    oidc.reset_store()
    client.cookies.clear()


def _jwt(payload: dict) -> str:
    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(payload)}.sig"


class _TokenResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _start_query() -> dict[str, str]:
    response = client.get("/api/login/start", follow_redirects=False)
    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    assert parsed.scheme == "http"
    assert parsed.netloc == "keycloak.test"
    assert parsed.path == "/auth/realms/mosip/protocol/openid-connect/auth"
    query = parse_qs(parsed.query)
    return {key: values[0] for key, values in query.items()}


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _assert_no_secrets(response, *secrets: str) -> None:
    blob = response.text + response.headers.get("set-cookie", "") + response.headers.get("location", "")
    assert "jwtToken" not in blob
    for secret in secrets:
        assert secret not in blob


def _callback(query: dict[str, str], payload: dict, *, secret: str | None = None):
    captured: dict = {}

    def fake_post(url, data=None, timeout=None, allow_redirects=None):
        captured["url"] = url
        captured["data"] = dict(data or {})
        captured["timeout"] = timeout
        captured["allow_redirects"] = allow_redirects
        return _TokenResponse(200, payload)

    with patch("register_id.oidc.requests.post", side_effect=fake_post) as post:
        response = client.get(
            "/api/login/callback",
            params={"code": AUTH_CODE, "state": query["state"]},
        )
    assert post.call_count == 1
    assert captured["url"] == "http://keycloak.test/auth/realms/mosip/protocol/openid-connect/token"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == AUTH_CODE
    assert captured["data"]["redirect_uri"] == "http://localhost:8000/api/login/callback"
    assert captured["data"]["client_id"] == "register-id-public"
    assert _s256(captured["data"]["code_verifier"]) == query["code_challenge"]
    if secret is None:
        assert "client_secret" not in captured["data"]
    else:
        assert captured["data"]["client_secret"] == secret
    captured["response"] = response
    return captured


def test_login_routes_are_registered():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/login/start" in paths
    assert "/api/login/callback" in paths
    assert "/api/login/session" in paths
    assert "/api/login/logout" in paths


def test_start_redirects_with_pkce_and_does_not_call_keycloak():
    with patch("register_id.oidc.requests.post") as post:
        first = _start_query()
        second = _start_query()
    post.assert_not_called()
    assert first["response_type"] == "code"
    assert first["client_id"] == "register-id-public"
    assert first["redirect_uri"] == "http://localhost:8000/api/login/callback"
    assert first["scope"] == "openid"
    assert first["code_challenge_method"] == "S256"
    assert first["state"]
    assert first["code_challenge"]
    assert "code_verifier" not in first
    assert first["state"] != second["state"]
    assert first["code_challenge"] != second["code_challenge"]
    assert 43 <= len(first["code_challenge"]) <= 128


def test_start_requires_client_id(monkeypatch):
    monkeypatch.delenv("KEYCLOAK_OIDC_CLIENT_ID", raising=False)
    with pytest.raises(oidc.OidcConfigError, match="KEYCLOAK_OIDC_CLIENT_ID"):
        oidc.begin_authorization()
    response = client.get("/api/login/start", follow_redirects=False)
    assert response.status_code == 400
    assert "KEYCLOAK_OIDC_CLIENT_ID" in response.json()["detail"]


def test_start_requires_redirect_uri(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_OIDC_REDIRECT_URI", "  ")
    with pytest.raises(oidc.OidcConfigError, match="KEYCLOAK_OIDC_REDIRECT_URI"):
        oidc.begin_authorization()
    response = client.get("/api/login/start", follow_redirects=False)
    assert response.status_code == 400
    assert "KEYCLOAK_OIDC_REDIRECT_URI" in response.json()["detail"]


def test_callback_sets_httponly_session_and_hides_the_access_token():
    query = _start_query()
    id_token = _jwt({"sub": "citizen-sub", "uin": "111122223333"})
    captured = _callback(
        query,
        {
            "access_token": ACCESS_TOKEN,
            "id_token": id_token,
            "token_type": "Bearer",
            "expires_in": 120,
        },
    )
    response = captured["response"]
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "subject": "citizen-sub", "uin": "111122223333"}
    _assert_no_secrets(response, ACCESS_TOKEN, AUTH_CODE, id_token, captured["data"]["code_verifier"])

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[SESSION_COOKIE_NAME]
    assert morsel.value
    assert morsel.value != ACCESS_TOKEN
    assert morsel["httponly"] is True
    assert morsel["secure"] == ""
    assert morsel["path"] == "/"
    assert morsel["samesite"] == "lax"

    stored = json.loads(oidc._STORE.get(f"session:{morsel.value}"))
    assert stored["access_token"] == ACCESS_TOKEN
    assert stored["subject"] == "citizen-sub"

    session = client.get("/api/login/session")
    assert session.status_code == 200
    assert session.json() == {"subject": "citizen-sub", "uin": "111122223333"}
    _assert_no_secrets(session, ACCESS_TOKEN, id_token)

    with patch("register_id.oidc.requests.post") as post:
        replay = client.get(
            "/api/login/callback",
            params={"code": AUTH_CODE, "state": query["state"]},
        )
    post.assert_not_called()
    assert replay.status_code == 400
    assert AUTH_CODE not in replay.text


def test_session_omits_uin_when_the_claim_is_absent():
    query = _start_query()
    captured = _callback(
        query,
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub"}), "expires_in": 90},
    )
    assert captured["response"].status_code == 200
    session = client.get("/api/login/session")
    assert session.status_code == 200
    assert session.json() == {"subject": "citizen-sub"}
    assert "jwtToken" not in session.json()


def test_callback_sends_client_secret_only_when_configured(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    query = _start_query()
    assert CLIENT_SECRET not in client.get("/api/login/start", follow_redirects=False).headers.get("location", "")
    query = _start_query()
    captured = _callback(
        query,
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub"}), "expires_in": 90},
        secret=CLIENT_SECRET,
    )
    _assert_no_secrets(captured["response"], CLIENT_SECRET, ACCESS_TOKEN)


def test_cookie_secure_follows_flag_and_environment(monkeypatch):
    monkeypatch.setenv("REGISTER_ID_COOKIE_SECURE", "true")
    query = _start_query()
    captured = _callback(
        query,
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub"}), "expires_in": 90},
    )
    cookie = SimpleCookie()
    cookie.load(captured["response"].headers["set-cookie"])
    assert cookie[SESSION_COOKIE_NAME]["secure"] is True

    client.cookies.clear()
    oidc.reset_store()
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.delenv("REGISTER_ID_COOKIE_SECURE", raising=False)
    captured = _callback(
        _start_query(),
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub"}), "expires_in": 90},
    )
    cookie = SimpleCookie()
    cookie.load(captured["response"].headers["set-cookie"])
    assert cookie[SESSION_COOKIE_NAME]["secure"] is True


def test_logout_deletes_server_session_and_cookie():
    query = _start_query()
    captured = _callback(
        query,
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub", "uin": "42"}), "expires_in": 90},
    )
    cookie = SimpleCookie()
    cookie.load(captured["response"].headers["set-cookie"])
    session_id = cookie[SESSION_COOKIE_NAME].value

    logout = client.post("/api/login/logout")
    assert logout.status_code == 200
    assert logout.json() == {"status": "logged_out"}
    _assert_no_secrets(logout, ACCESS_TOKEN)
    cleared = SimpleCookie()
    cleared.load(logout.headers["set-cookie"])
    assert cleared[SESSION_COOKIE_NAME]["max-age"] == "0"
    assert oidc._STORE.get(f"session:{session_id}") is None

    session = client.get("/api/login/session")
    assert session.status_code == 401
    assert "jwtToken" not in session.json()


def test_session_without_cookie_is_unauthorized():
    response = client.get("/api/login/session")
    assert response.status_code == 401


def test_callback_does_not_log_code_or_token(caplog):
    query = _start_query()
    id_token = _jwt({"sub": "citizen-sub"})
    with caplog.at_level(logging.DEBUG, logger="register_id.oidc"):
        captured = _callback(
            query,
            {"access_token": ACCESS_TOKEN, "id_token": id_token, "expires_in": 90},
        )
    assert captured["response"].status_code == 200
    assert AUTH_CODE not in caplog.text
    assert ACCESS_TOKEN not in caplog.text
    assert id_token not in caplog.text
    assert captured["data"]["code_verifier"] not in caplog.text


def test_unknown_state_does_not_exchange():
    with patch("register_id.oidc.requests.post") as post:
        response = client.get("/api/login/callback", params={"code": AUTH_CODE, "state": "missing"})
    post.assert_not_called()
    assert response.status_code == 400
    assert AUTH_CODE not in response.text


def test_token_endpoint_failure_hides_the_code():
    query = _start_query()

    def fake_post(url, data=None, timeout=None, allow_redirects=None):
        return _TokenResponse(401, {"error": "invalid_grant"})

    with patch("register_id.oidc.requests.post", side_effect=fake_post):
        response = client.get("/api/login/callback", params={"code": AUTH_CODE, "state": query["state"]})
    assert response.status_code == 502
    assert AUTH_CODE not in response.text
    assert "set-cookie" not in {name.lower() for name in response.headers}


def test_redis_is_used_when_configured_and_memory_is_not(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.store: dict[str, str] = {}

        def setex(self, key, ttl, value):
            self.store[key] = value

        def get(self, key):
            return self.store.get(key)

        def delete(self, key):
            self.store.pop(key, None)

        def close(self):
            return None

    fake = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://redis.internal:6379/0")
    monkeypatch.setattr(oidc, "_redis_client", lambda: fake)

    query = _start_query()
    assert oidc._STORE._memory._items == {}
    state_key = f"register-id:oidc:state:{query['state']}"
    assert state_key in fake.store
    verifier = fake.store[state_key]
    assert _s256(verifier) == query["code_challenge"]

    captured = _callback(
        query,
        {"access_token": ACCESS_TOKEN, "id_token": _jwt({"sub": "citizen-sub", "uin": "9"}), "expires_in": 90},
    )
    assert captured["data"]["code_verifier"] == verifier
    assert state_key not in fake.store
    assert oidc._STORE._memory._items == {}
    session_keys = [key for key in fake.store if key.startswith("register-id:oidc:session:")]
    assert len(session_keys) == 1
    assert ACCESS_TOKEN in fake.store[session_keys[0]]
    _assert_no_secrets(captured["response"], ACCESS_TOKEN, verifier)


def test_redis_outage_fails_start_without_memory_fallback(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    with pytest.raises(oidc.OidcStoreError, match="Redis"):
        oidc.begin_authorization()
    assert oidc._STORE._memory._items == {}
    response = client.get("/api/login/start", follow_redirects=False)
    assert response.status_code == 503
    assert "location" not in response.headers
    assert "Redis" in response.json()["detail"]
    assert oidc._STORE._memory._items == {}
