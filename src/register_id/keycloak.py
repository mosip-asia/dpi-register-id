"""
Keycloak IAM provisioning client for register_id.

Synchronizes enrolled citizens into Keycloak with a UIN attribute and the
credential the citizen chose. This client does not decide biometric validity,
so it never writes attributes.individualBiometrics.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080/auth").rstrip("/")
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN_USER", "admin")
# Compose supplies this from .env. An empty value fails closed; there is no
# built-in admin password and no default citizen password.
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mosip")


@dataclass
class ProvisionResult(int):
    """Outcome of provision_citizen.

    Stored as 0 or 1 so CredentialResponse.keycloakProvisioned can take the
    object unchanged. Truth tests follow ok.
    """

    ok: bool
    created: bool
    detail: str

    def __new__(cls, ok: bool, created: bool, detail: str):
        return int.__new__(cls, 1 if ok else 0)

    def __bool__(self) -> bool:
        return self.ok


class KeycloakBridgeClient:
    """
    Manages OAuth2 token exchange and user provisioning with Keycloak IAM.
    """

    def __init__(
        self,
        base_url: str = KEYCLOAK_URL,
        admin_user: str = KEYCLOAK_ADMIN_USER,
        admin_pass: str = KEYCLOAK_ADMIN_PASSWORD,
        realm: str = KEYCLOAK_REALM,
    ):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.realm = realm

    def get_admin_token(self) -> str | None:
        """
        Requests a master-realm admin token with the password grant.

        The token and the admin password are never logged.
        """
        if not self.base_url or not self.admin_user or not self.admin_pass:
            logger.warning("Keycloak admin token unavailable: configuration incomplete.")
            return None

        token_url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        try:
            res = requests.post(
                token_url,
                data={
                    "client_id": "admin-cli",
                    "username": self.admin_user,
                    "password": self.admin_pass,
                    "grant_type": "password",
                },
                timeout=3,
            )
        except requests.RequestException:
            logger.warning("Keycloak server unreachable at %s", token_url)
            return None

        if res.status_code != 200:
            logger.warning("Keycloak admin token failed with status %s", res.status_code)
            return None

        try:
            body = res.json()
        except ValueError:
            logger.warning("Keycloak admin token response was not JSON.")
            return None

        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            logger.warning("Keycloak admin token response did not include an access token.")
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
        Creates a citizen user, or resets the password when the same UIN already exists.

        password is the credential the citizen chose. There is no default.
        It is sent only in a Keycloak credential payload and is never logged.
        """
        if not self.base_url or not self.realm:
            return ProvisionResult(False, False, "keycloak is not configured")

        admin_token = self.get_admin_token()
        if not admin_token:
            return ProvisionResult(False, False, "admin token unavailable")

        username = email.split("@")[0] if "@" in email else uin.replace("-", "")
        payload = _user_payload(uin, full_name, email, username, password)
        users_url = f"{self.base_url}/admin/realms/{self.realm}/users"
        headers = _auth_headers(admin_token)

        try:
            res = requests.post(users_url, json=payload, headers=headers, timeout=5)
        except requests.RequestException:
            logger.error("Keycloak user creation request failed")
            return ProvisionResult(False, False, "network error")

        if res.status_code == 201:
            logger.info("Citizen %s created in Keycloak realm %s", uin, self.realm)
            return ProvisionResult(True, True, "created")

        if res.status_code == 409:
            return self._reset_password_if_same_uin(
                users_url=users_url,
                headers=headers,
                username=username,
                uin=uin,
                password=password,
            )

        logger.warning("Keycloak user creation returned status %s", res.status_code)
        return ProvisionResult(False, False, f"keycloak status {res.status_code}")

    def _reset_password_if_same_uin(
        self,
        users_url: str,
        headers: dict[str, str],
        username: str,
        uin: str,
        password: str,
    ) -> ProvisionResult:
        try:
            res = requests.get(
                users_url,
                params={"username": username, "exact": "true"},
                headers=headers,
                timeout=5,
            )
        except requests.RequestException:
            logger.error("Keycloak user lookup request failed")
            return ProvisionResult(False, False, "network error")

        if res.status_code != 200:
            logger.warning("Keycloak user lookup returned status %s", res.status_code)
            return ProvisionResult(False, False, "user lookup failed")

        try:
            body = res.json()
        except ValueError:
            logger.warning("Keycloak user lookup response was not JSON.")
            return ProvisionResult(False, False, "user lookup failed")

        user = _exact_user(body, username)
        if user is None:
            return ProvisionResult(False, False, "existing user not found")

        uin_state = _uin_state(user, uin)
        if uin_state == "missing":
            return ProvisionResult(False, False, "existing user uin missing")
        if uin_state != "match":
            return ProvisionResult(False, False, "existing user uin mismatch")

        user_id = user.get("id")
        if not user_id:
            return ProvisionResult(False, False, "existing user id missing")

        reset_url = f"{users_url}/{user_id}/reset-password"
        try:
            reset = requests.put(
                reset_url,
                json={"type": "password", "value": password, "temporary": False},
                headers=headers,
                timeout=5,
            )
        except requests.RequestException:
            logger.error("Keycloak password reset request failed")
            return ProvisionResult(False, False, "network error")

        if reset.status_code in (200, 204):
            logger.info("Citizen %s password set in Keycloak realm %s", uin, self.realm)
            return ProvisionResult(True, False, "password reset")

        logger.warning("Keycloak password reset returned status %s", reset.status_code)
        return ProvisionResult(False, False, "password reset failed")

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
            res = requests.get(
                users_url,
                params={"q": f"uin:{uin}"},
                headers=headers,
                timeout=5,
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
            updated = requests.put(
                f"{users_url}/{user_id}",
                json=payload,
                headers=headers,
                timeout=5,
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
        _keycloak_client = KeycloakBridgeClient()
    return _keycloak_client
