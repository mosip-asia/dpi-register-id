"""
Keycloak IAM provisioning client for register_id.

Synchronizes enrolled citizens into Keycloak with a UIN attribute and the
credential the citizen chose. This client does not decide biometric validity,
so it never writes attributes.individualBiometrics.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from register_id.idrepo_client import (
    _http_attempts,
    _http_backoff,
    _http_timeout,
    inprocess_fallback_enabled,
)

logger = logging.getLogger(__name__)

def _configured(name: str, default: str) -> str:
    """Blank environment values keep the local default. Compose passes empty strings."""
    value = os.getenv(name, "").strip()
    return (value or default).rstrip("/")


KEYCLOAK_URL = _configured("KEYCLOAK_URL", "http://localhost:8080/auth")
# Browser redirects use the public host. Admin API calls use the in-cluster host.
# KEYCLOAK_URL fills a missing host only while local in-process fallback is on.


def _scoped_keycloak_url(name: str) -> str:
    specific = _configured(name, "")
    if specific:
        return specific
    if inprocess_fallback_enabled():
        return KEYCLOAK_URL
    return ""


KEYCLOAK_PUBLIC_URL = _scoped_keycloak_url("KEYCLOAK_PUBLIC_URL")
KEYCLOAK_INTERNAL_URL = _scoped_keycloak_url("KEYCLOAK_INTERNAL_URL")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mosip")


def _keycloak_call(method: str, url: str, *, idempotent: bool = False, **kwargs):
    """POST and PUT run once. Idempotent GETs use the shared MOSIP retry budget."""
    attempts = _http_attempts(idempotent)
    delay = _http_backoff()
    kwargs["timeout"] = _http_timeout()
    call = getattr(requests, method)
    for attempt in range(attempts):
        try:
            return call(url, **kwargs)
        except requests.RequestException:
            if attempt + 1 >= attempts:
                raise
            if delay:
                time.sleep(delay)
                delay = min(delay * 2, 5.0)


@dataclass
class ProvisionResult(int):
    """Outcome of provision_citizen.

    Stored as 0 or 1 so CredentialResponse.keycloakProvisioned can take the
    object unchanged. Truth tests follow ok.
    """

    ok: bool
    created: bool
    detail: str
    retryable: bool = False

    def __new__(cls, ok: bool, created: bool, detail: str, retryable: bool = False):
        return int.__new__(cls, 1 if ok else 0)

    def __bool__(self) -> bool:
        return self.ok


class KeycloakBridgeClient:
    """
    Manages OAuth2 token exchange and user provisioning with Keycloak IAM.
    """

    def __init__(
        self,
        base_url: str = KEYCLOAK_INTERNAL_URL,
        admin_user: str = "",
        admin_pass: str = "",
        realm: str = KEYCLOAK_REALM,
        client_id: str = "",
        client_secret: str = "",
    ):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self._token_unreachable = False

    def get_admin_token(self) -> str | None:
        """
        Token for the Keycloak admin API.

        Only a confidential client on KEYCLOAK_REALM is accepted. The master
        password grant is not used. The token and the secret are never logged.
        The client needs realm-management manage-users and view-users, and the
        secret is supplied per deployment.
        """
        if not (self.client_id and self.client_secret):
            self._token_unreachable = False
            logger.warning("Keycloak service-account token unavailable: configuration incomplete.")
            return None
        return self._client_credentials_token()

    def _client_credentials_token(self) -> str | None:
        """Confidential-client token on the application realm, not master admin-cli."""
        if not self.base_url or not self.realm:
            logger.warning("Keycloak service-account token unavailable: configuration incomplete.")
            return None
        token_url = f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"
        self._token_unreachable = False
        try:
            res = _keycloak_call(
                "post",
                token_url,
                idempotent=False,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            )
        except requests.RequestException:
            self._token_unreachable = True
            logger.warning("Keycloak server unreachable at %s", token_url)
            return None
        if res.status_code != 200:
            logger.warning("Keycloak service-account token failed with status %s", res.status_code)
            return None
        try:
            body = res.json()
        except ValueError:
            logger.warning("Keycloak service-account token response was not JSON.")
            return None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            logger.warning("Keycloak service-account token response did not include an access token.")
            return None
        return str(token)

    def provision_citizen(
        self,
        uin: str,
        full_name: str,
        email: str,
        password: str,
    ) -> ProvisionResult:
        """
        Creates a citizen user. A Keycloak 409 means that account already exists.
        The password is not reset.

        password is the credential the citizen chose. There is no default.
        It is sent only in a Keycloak credential payload and is never logged.
        """
        if not self.base_url or not self.realm:
            return ProvisionResult(False, False, "keycloak is not configured")

        admin_token = self.get_admin_token()
        if not admin_token:
            return ProvisionResult(
                False,
                False,
                "admin token unavailable",
                retryable=self._token_unreachable,
            )

        username = uin
        payload = _user_payload(uin, full_name, email, username, password)
        users_url = f"{self.base_url}/admin/realms/{self.realm}/users"
        headers = _auth_headers(admin_token)

        try:
            res = _keycloak_call(
                "post",
                users_url,
                idempotent=False,
                json=payload,
                headers=headers,
            )
        except requests.RequestException:
            logger.error("Keycloak user creation request failed")
            return ProvisionResult(False, False, "network error", retryable=True)

        if res.status_code == 201:
            logger.info("Citizen %s created in Keycloak realm %s", uin, self.realm)
            return ProvisionResult(True, True, "created")

        if res.status_code == 409:
            logger.info("Citizen %s already exists in Keycloak realm %s", uin, self.realm)
            return ProvisionResult(False, False, "account already exists")

        logger.warning("Keycloak user creation returned status %s", res.status_code)
        return ProvisionResult(False, False, f"keycloak status {res.status_code}")

    def set_login_enabled(self, uin: str, email: str, enabled: bool) -> ProvisionResult:
        """
        Enable or disable the realm user whose uin attribute matches.

        No realm user is a completed disable: there is no login to turn off.
        A missing admin token or a network error is not success.
        """
        if not self.base_url or not self.realm:
            return ProvisionResult(False, False, "keycloak is not configured")
        admin_token = self.get_admin_token()
        if not admin_token:
            return ProvisionResult(False, False, "admin token unavailable")

        del email
        users_url = f"{self.base_url}/admin/realms/{self.realm}/users"
        headers = _auth_headers(admin_token)
        try:
            res = _keycloak_call(
                "get",
                users_url,
                idempotent=True,
                params={"q": f"uin:{uin}"},
                headers=headers,
            )
        except requests.RequestException:
            logger.error("Keycloak user lookup request failed")
            return ProvisionResult(False, False, "network error")
        if res.status_code != 200:
            return ProvisionResult(False, False, "user lookup failed")
        try:
            body = res.json()
        except ValueError:
            return ProvisionResult(False, False, "user lookup failed")
        matches = [
            user
            for user in body
            if isinstance(user, dict) and _uin_state(user, uin) == "match"
        ] if isinstance(body, list) else []
        if len(matches) > 1:
            return ProvisionResult(False, False, "multiple realm users")
        if not matches:
            if enabled:
                return ProvisionResult(False, False, "no realm user")
            return ProvisionResult(True, False, "no realm user")
        user = matches[0]
        user_id = user.get("id")
        if not user_id:
            return ProvisionResult(False, False, "existing user id missing")
        # PUT replaces the user. Send the current representation with enabled
        # changed so the uin attribute is not cleared. Never send credentials.
        payload = {key: value for key, value in user.items() if key != "credentials"}
        payload["enabled"] = enabled
        try:
            updated = _keycloak_call(
                "put",
                f"{users_url}/{user_id}",
                idempotent=False,
                json=payload,
                headers=headers,
            )
        except requests.RequestException:
            logger.error("Keycloak enabled update failed")
            return ProvisionResult(False, False, "network error")
        if updated.status_code in (200, 204):
            return ProvisionResult(True, False, "enabled updated")
        return ProvisionResult(False, False, f"keycloak status {updated.status_code}")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _user_payload(
    uin: str,
    full_name: str,
    email: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    name_parts = full_name.strip().split()
    first_name = name_parts[0] if name_parts else "Citizen"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Citizen"
    return {
        "username": username,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "enabled": True,
        "attributes": {"uin": [uin]},
        "credentials": [
            {
                "type": "password",
                "value": password,
                "temporary": False,
            }
        ],
    }


def _exact_user(body: Any, username: str) -> dict[str, Any] | None:
    if not isinstance(body, list):
        return None
    wanted = username.casefold()
    matches = [
        user
        for user in body
        if isinstance(user, dict) and str(user.get("username", "")).casefold() == wanted
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _uin_state(user: dict[str, Any], uin: str) -> str:
    attributes = user.get("attributes")
    if not isinstance(attributes, dict) or "uin" not in attributes:
        return "missing"
    raw = attributes.get("uin")
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        return "missing"
    cleaned = [str(item).strip() for item in values if item is not None and str(item).strip()]
    if not cleaned:
        return "missing"
    if all(value == uin for value in cleaned):
        return "match"
    return "mismatch"


_keycloak_client: KeycloakBridgeClient | None = None


def get_keycloak_client() -> KeycloakBridgeClient:
    global _keycloak_client
    if _keycloak_client is None:
        _keycloak_client = KeycloakBridgeClient(
            client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", ""),
            client_secret=os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        )
    return _keycloak_client
