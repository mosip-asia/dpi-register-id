"""
Keycloak IAM Provisioning Client for register_id.

Synchronizes newly enrolled citizens into Keycloak (mosip realm)
with UIN attributes and credentials for downstream eSignet OIDC login.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080/auth").rstrip("/")
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN_USER", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mosip")


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
        self.base_url = base_url
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.realm = realm

    def get_admin_token(self) -> str | None:
        """
        Requests master admin access token via client credentials/password grant.
        """
        import requests
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
            if res.status_code == 200:
                return res.json().get("access_token")
            logger.warning(f"Keycloak admin token failed (status {res.status_code}): {res.text}")
        except Exception as e:
            logger.debug(f"Keycloak server unreachable at {token_url}: {e}")
        return None

    def provision_citizen(
        self,
        uin: str,
        full_name: str,
        email: str,
        password: str,
    ) -> bool:
        """
        Creates or updates a citizen user in the target Keycloak realm.

        password is the credential the citizen chose. There is no default.
        """
        import requests
        admin_token = self.get_admin_token()
        if not admin_token:
            logger.warning("Skipping Keycloak user provisioning: admin token unavailable.")
            return False

        name_parts = full_name.strip().split()
        first_name = name_parts[0] if name_parts else "Citizen"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Citizen"
        username = email.split("@")[0] if "@" in email else uin.replace("-", "")

        user_payload: dict[str, Any] = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "attributes": {
                "uin": [uin],
                "individualBiometrics": ["VALID"],
            },
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": False,
                }
            ],
        }

        users_url = f"{self.base_url}/admin/realms/{self.realm}/users"
        headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        }

        try:
            res = requests.post(users_url, json=user_payload, headers=headers, timeout=5)
            if res.status_code in (201, 204, 409):
                logger.info(f"Citizen {uin} provisioned in Keycloak realm '{self.realm}'.")
                return True
            logger.warning(f"Keycloak user creation returned {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Failed to post user payload to Keycloak: {e}")
        return False


_keycloak_client: KeycloakBridgeClient | None = None


def get_keycloak_client() -> KeycloakBridgeClient:
    global _keycloak_client
    if _keycloak_client is None:
        _keycloak_client = KeycloakBridgeClient()
    return _keycloak_client
