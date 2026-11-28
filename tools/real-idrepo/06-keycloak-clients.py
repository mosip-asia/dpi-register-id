"""Step 6: Keycloak clients for the real ID Repository (local realm `mosip`).

1. register-id's own IDRepo client (IDREPO_CLIENT_ID in register-id .env) gets an audience mapper.
   MOSIP's auth adapter crashes on a token without `aud`.
2. `mosip-idrepo-client` is created: the ID Repository's OWN service account. IDRepo uses it
   (client_credentials) for calls it makes to keymanager, masterdata, and others.
   Its secret is IDREPO_AUTH_SECRET from idrepo.env.

Usage (from the register-id folder):
    uv run python tools/real-idrepo/06-keycloak-clients.py .env tools/real-idrepo/idrepo.env
Prints no secrets. Safe to run again.
"""

import base64
import json
import sys

import requests
from dotenv import dotenv_values

app_env = dotenv_values(sys.argv[1])
idrepo_env = dotenv_values(sys.argv[2])
base = "http://localhost:8080"
realm = (app_env.get("KEYCLOAK_REALM") or "mosip").strip('"')

admin = requests.post(
    f"{base}/realms/master/protocol/openid-connect/token",
    data={"grant_type": "password", "client_id": "admin-cli",
          "username": app_env["KEYCLOAK_ADMIN_USER"], "password": app_env["KEYCLOAK_ADMIN_PASSWORD"]},
    timeout=10,
).json()["access_token"]
H = {"Authorization": f"Bearer {admin}"}
R = f"{base}/admin/realms/{realm}"


def find_client(client_id):
    found = requests.get(f"{R}/clients", params={"clientId": client_id}, headers=H, timeout=10).json()
    return found[0] if found else None


def ensure_client(client_id, secret):
    client = find_client(client_id)
    if client is None:
        r = requests.post(f"{R}/clients", headers=H, timeout=10, json={
            "clientId": client_id, "enabled": True, "protocol": "openid-connect",
            "publicClient": False, "serviceAccountsEnabled": True,
            "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
            "clientAuthenticatorType": "client-secret", "secret": secret,
        })
        print(f"created client {client_id}: HTTP {r.status_code}")
        client = find_client(client_id)
    else:
        client["secret"] = secret
        requests.put(f"{R}/clients/{client['id']}", headers=H, json=client, timeout=10)
        print(f"client {client_id} exists; secret updated")
    # MOSIP services cache their own token and renew it on a timer of minutes. With Keycloak's default
    # 5-minute token, IDRepo's token expires between renewals and its calls to keymanager fail
    # ("user authentication failed for the provided token", IDR-IDC-004). Give service tokens 1 day.
    client = find_client(client_id)
    client.setdefault("attributes", {})["access.token.lifespan"] = "86400"
    requests.put(f"{R}/clients/{client['id']}", headers=H, json=client, timeout=10)
    print(f"client {client_id}: access token lifespan 1 day")
    return client


def ensure_audience(client):
    url = f"{R}/clients/{client['id']}/protocol-mappers/models"
    name = f"{client['clientId']}-audience"
    if name in [m["name"] for m in requests.get(url, headers=H, timeout=10).json()]:
        print(f"audience mapper already on {client['clientId']}")
        return
    r = requests.post(url, headers=H, timeout=10, json={
        "name": name, "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": client["clientId"],
                   "id.token.claim": "false", "access.token.claim": "true"},
    })
    print(f"audience mapper on {client['clientId']}: HTTP {r.status_code}")


def ensure_realm_roles(client, roles):
    sa = requests.get(f"{R}/clients/{client['id']}/service-account-user", headers=H, timeout=10).json()
    wanted = []
    for name in roles:
        role = requests.get(f"{R}/roles/{name}", headers=H, timeout=10)
        if role.status_code == 404:
            requests.post(f"{R}/roles", headers=H, json={"name": name}, timeout=10)
            role = requests.get(f"{R}/roles/{name}", headers=H, timeout=10)
        wanted.append(role.json())
    requests.post(f"{R}/users/{sa['id']}/role-mappings/realm", headers=H, json=wanted, timeout=10)
    print(f"realm roles on {client['clientId']}: {', '.join(roles)}")


def show_token(client_id, secret):
    tok = requests.post(f"{base}/realms/{realm}/protocol/openid-connect/token", timeout=10,
                        data={"grant_type": "client_credentials", "client_id": client_id,
                              "client_secret": secret}).json()
    part = tok["access_token"].split(".")[1]
    part += "=" * (-len(part) % 4)
    claims = json.loads(base64.urlsafe_b64decode(part))
    print(f"  {client_id} token aud={claims.get('aud')} roles={claims.get('realm_access', {}).get('roles')}")


# 1. register-id's client: only add the audience
rid_client_id = (app_env.get("IDREPO_CLIENT_ID") or "register-id-idrepo").strip('"')
rid_client = find_client(rid_client_id)
ensure_audience(rid_client)
show_token(rid_client_id, (app_env.get("IDREPO_CLIENT_SECRET") or "").strip('"'))

# 2. The ID Repository's own service account
own_secret = idrepo_env["IDREPO_AUTH_SECRET"]
own = ensure_client("mosip-idrepo-client", own_secret)
ensure_audience(own)
ensure_realm_roles(own, ["ID_REPOSITORY", "REGISTRATION_PROCESSOR"])
show_token("mosip-idrepo-client", own_secret)
