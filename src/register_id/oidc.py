"""
Keycloak authorization-code login with PKCE (S256).

The gateway does not mint an access token and does not put a biometric
result into a jwtToken field. The browser is sent to the configured realm.
The callback exchanges the authorization code with the matching PKCE
verifier and stores a server session keyed by a session id. That record
holds the subject, an optional uin, and the session TTL. Keycloak's
access token is read for claims during the exchange and is not written
to the login store. HTTP responses never include that token.

Pending verifiers and sessions use one small process-local dict when
REDIS_URL is unset, which is enough for a single process and for tests.
When REDIS_URL is set, those same keys are stored in Redis so a process
restart can still finish the code exchange:

- ``register-id:oidc:state:{state}`` — PKCE code_verifier
- ``register-id:oidc:session:{session_id}`` — server session (subject,
  optional uin). Expiry is the key TTL.

A configured Redis that cannot be reached fails the call. The in-memory
dict is not a fallback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import requests

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "register_id_session"
_STATE_TTL_SECONDS = 600
_DEFAULT_SESSION_TTL_SECONDS = 3600
_REDIS_KEY_PREFIX = "register-id:oidc:"


class OidcError(Exception):
    """Base error for citizen OIDC login."""


class OidcConfigError(OidcError):
    """Required Keycloak OIDC settings are missing."""


class OidcStoreError(OidcError):
    """The configured login-state store could not be reached."""


class OidcRequestError(OidcError):
    """The callback did not match a pending login."""


class OidcExchangeError(OidcError):
    """Keycloak did not complete the authorization-code exchange."""


@dataclass(frozen=True)
class SessionResult:
    session_id: str
    subject: str
    uin: str | None
    max_age: int


class _MemoryBackend:
    """Process-local dict of key -> (value, monotonic expiry)."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires = time.monotonic() + ttl_seconds
        with self._lock:
            self._items[key] = (value, expires)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._take(key, delete=False)

    def pop(self, key: str) -> str | None:
        with self._lock:
            return self._take(key, delete=True)

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def _take(self, key: str, *, delete: bool) -> str | None:
        item = self._items.get(key)
        if item is None:
            return None
        value, expires = item
        if expires <= time.monotonic():
            self._items.pop(key, None)
            return None
        if delete:
            self._items.pop(key, None)
        return value


class _RedisBackend:
    """Same get/set/pop surface as the dict, backed by REDIS_URL."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._call(lambda: self._client.setex(self._redis_key(key), ttl_seconds, value))

    def get(self, key: str) -> str | None:
        value = self._call(lambda: self._client.get(self._redis_key(key)))
        return value if isinstance(value, str) else None

    def pop(self, key: str) -> str | None:
        redis_key = self._redis_key(key)

        def _pop() -> str | None:
            value = self._client.get(redis_key)
            if value is not None:
                self._client.delete(redis_key)
            return value if isinstance(value, str) else None

        return self._call(_pop)

    def delete(self, key: str) -> None:
        self._call(lambda: self._client.delete(self._redis_key(key)))

    @staticmethod
    def _redis_key(key: str) -> str:
        return f"{_REDIS_KEY_PREFIX}{key}"

    @staticmethod
    def _call(operation: Any) -> Any:
        try:
            return operation()
        except Exception as exc:
            if _is_store_outage(exc):
                raise OidcStoreError("Redis is configured but the OIDC login store is unavailable") from exc
            raise


class OidcStore:
    def __init__(self) -> None:
        self._memory = _MemoryBackend()

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        backend, client = self._open()
        try:
            backend.set(key, value, ttl_seconds)
        finally:
            _close_client(client)

    def get(self, key: str) -> str | None:
        backend, client = self._open()
        try:
            return backend.get(key)
        finally:
            _close_client(client)

    def pop(self, key: str) -> str | None:
        backend, client = self._open()
        try:
            return backend.pop(key)
        finally:
            _close_client(client)

    def delete(self, key: str) -> None:
        backend, client = self._open()
        try:
            backend.delete(key)
        finally:
            _close_client(client)

    def reset_memory(self) -> None:
        self._memory = _MemoryBackend()

    def _open(self) -> tuple[_MemoryBackend | _RedisBackend, Any | None]:
        client = _redis_client()
        if client is None:
            return self._memory, None
        return _RedisBackend(client), client


_STORE = OidcStore()


def reset_store() -> None:
    """Drop process-local login state. Used by tests."""
    _STORE.reset_memory()


def begin_authorization() -> str:
    """
    Build the realm authorization URL and persist state plus code_verifier.

    Raises OidcConfigError when the client id or redirect URI is missing.
    Raises OidcStoreError when Redis is configured and cannot store the verifier.
    """
    client_id = _required("KEYCLOAK_OIDC_CLIENT_ID")
    redirect_uri = _required("KEYCLOAK_OIDC_REDIRECT_URI")
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    _STORE.set(f"state:{state}", verifier, _STATE_TTL_SECONDS)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    realm = quote(_realm(), safe="")
    return f"{_keycloak_base()}/realms/{realm}/protocol/openid-connect/auth?{query}"


def establish_session(code: str, state: str) -> SessionResult:
    """
    Exchange an authorization code and store the signed-in subject under a new session id.

    The access token is required for the exchange and may supply claims.
    It is not stored and is not returned. The login store keeps subject,
    optional uin, and the session TTL taken from expires_in.
    """
    if not code or not state:
        raise OidcRequestError("Missing authorization code or state")
    verifier = _STORE.pop(f"state:{state}")
    if not verifier:
        raise OidcRequestError("Unknown or expired login state")

    payload = _exchange_code(code, verifier)
    subject, uin = _identity_claims(payload)
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OidcExchangeError("Sign-in could not be completed")

    record: dict[str, str] = {"subject": subject}
    if uin is not None:
        record["uin"] = uin
    session_id = secrets.token_urlsafe(32)
    max_age = _session_ttl(payload)
    _STORE.set(f"session:{session_id}", json.dumps(record, separators=(",", ":")), max_age)
    logger.info("OIDC session established")
    return SessionResult(session_id=session_id, subject=subject, uin=uin, max_age=max_age)


def load_session(session_id: str | None) -> dict[str, str] | None:
    """Return the subject and optional uin stored for a session id."""
    if not session_id:
        return None
    raw = _STORE.get(f"session:{session_id}")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        subject = data["subject"]
    except (json.JSONDecodeError, KeyError, TypeError):
        _STORE.delete(f"session:{session_id}")
        return None
    if not isinstance(data, dict) or not isinstance(subject, str) or not subject:
        return None
    view = {"subject": subject}
    uin = data.get("uin")
    if isinstance(uin, str) and uin:
        view["uin"] = uin
    return view


def destroy_session(session_id: str | None) -> None:
    if session_id:
        _STORE.delete(f"session:{session_id}")


def cookie_secure() -> bool:
    """
    Secure cookie flag.

    REGISTER_ID_COOKIE_SECURE overrides the default. When it is unset, the
    cookie is not Secure if ENVIRONMENT is dev, and is Secure otherwise.
    """
    raw = os.getenv("REGISTER_ID_COOKIE_SECURE")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("ENVIRONMENT", "dev").lower() != "dev"


def _exchange_code(code: str, verifier: str) -> dict[str, Any]:
    client_id = _required("KEYCLOAK_OIDC_CLIENT_ID")
    redirect_uri = _required("KEYCLOAK_OIDC_REDIRECT_URI")
    secret = os.getenv("KEYCLOAK_OIDC_CLIENT_SECRET", "").strip()
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if secret:
        form["client_secret"] = secret
    token_url = f"{_keycloak_base()}/realms/{quote(_realm(), safe='')}/protocol/openid-connect/token"
    try:
        response = requests.post(token_url, data=form, timeout=10, allow_redirects=False)
    except requests.RequestException as exc:
        logger.warning("Keycloak token endpoint unreachable")
        raise OidcExchangeError("Sign-in could not be completed") from exc
    if response.status_code != 200:
        logger.warning("Keycloak token endpoint returned status %s", response.status_code)
        raise OidcExchangeError("Sign-in could not be completed")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OidcExchangeError("Sign-in could not be completed") from exc
    if not isinstance(payload, dict):
        raise OidcExchangeError("Sign-in could not be completed")
    return payload


def _identity_claims(payload: dict[str, Any]) -> tuple[str, str | None]:
    id_claims = _jwt_claims(payload.get("id_token"))
    access_claims = _jwt_claims(payload.get("access_token"))
    subject = id_claims.get("sub")
    if not isinstance(subject, str) or not subject:
        subject = access_claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise OidcExchangeError("Sign-in could not be completed")
    uin = _uin_claim(id_claims)
    if uin is None:
        uin = _uin_claim(access_claims)
    return subject, uin


def _uin_claim(claims: dict[str, Any]) -> str | None:
    raw = claims.get("uin")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return None


def _jwt_claims(token: object) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") < 2:
        return {}
    segment = token.split(".", 2)[1]
    try:
        padded = segment + "=" * (-len(segment) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _session_ttl(payload: dict[str, Any]) -> int:
    raw = payload.get("expires_in", _DEFAULT_SESSION_TTL_SECONDS)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = _DEFAULT_SESSION_TTL_SECONDS
    if ttl < 60:
        return 60
    if ttl > 24 * 3600:
        return 24 * 3600
    return ttl


def _pkce_pair() -> tuple[str, str]:
    # 48 bytes is 64 unpadded urlsafe characters, inside the PKCE 43–128 range.
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise OidcConfigError(f"{name} is not configured")
    return value


def _keycloak_base() -> str:
    base = os.getenv("KEYCLOAK_URL", "http://localhost:8080/auth").strip().rstrip("/")
    if not base:
        raise OidcConfigError("KEYCLOAK_URL is not configured")
    return base


def _realm() -> str:
    realm = os.getenv("KEYCLOAK_REALM", "mosip").strip()
    return realm or "mosip"


def _redis_url() -> str | None:
    raw = os.getenv("REDIS_URL")
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _redis_client() -> Any | None:
    url = _redis_url()
    if url is None:
        return None
    try:
        import redis
    except ImportError as exc:
        raise OidcStoreError("Redis is configured but the OIDC login store is unavailable") from exc
    return redis.Redis.from_url(
        url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        decode_responses=True,
        retry_on_timeout=False,
    )


def _close_client(client: Any | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        logger.debug("OIDC Redis client close failed")


def _is_store_outage(exc: BaseException) -> bool:
    try:
        from redis.exceptions import RedisError
    except ImportError:
        return isinstance(exc, OSError)
    return isinstance(exc, (RedisError, OSError))
