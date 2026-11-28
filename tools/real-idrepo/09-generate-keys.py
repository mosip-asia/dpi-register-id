"""Step 9: generate keymanager master keys (what MOSIP's keys-generator job does).

Runs INSIDE the register-id-app container (see 09-generate-keys.sh), so the Keycloak token is issued for
http://keycloak:8080, the issuer keymanager trusts. Uses the ID Repository's own client
(mosip-idrepo-client, role REGISTRATION_PROCESSOR, allowed by mosip.role.keymanager.postgeneratemasterkeyobjecttype).

Order matters: ROOT first (it signs the others), then KERNEL and ID_REPO.
Prints no secrets. Safe to run again (force=false keeps existing keys).
"""

import datetime
import os
import sys

import requests

secret = os.environ["IDREPO_AUTH_SECRET"]
token = requests.post(
    "http://keycloak:8080/realms/mosip/protocol/openid-connect/token",
    data={"grant_type": "client_credentials", "client_id": "mosip-idrepo-client", "client_secret": secret},
    timeout=15,
).json()["access_token"]


def now():
    t = datetime.datetime.now(datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


ok = True
for app_id in ("ROOT", "KERNEL", "ID_REPO"):
    body = {
        "id": "string", "version": "1.0", "requesttime": now(), "metadata": {},
        "request": {"applicationId": app_id, "referenceId": "", "force": False,
                    "commonName": f"Local {app_id}", "organizationUnit": "register-id local",
                    "organization": "local", "location": "local", "state": "local", "country": "TH"},
    }
    r = requests.post("http://keymanager:8088/v1/keymanager/generateMasterKey/CERTIFICATE",
                      json=body, cookies={"Authorization": token}, timeout=60)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    errors = data.get("errors") or []
    status = (data.get("response") or {}).get("status")
    if r.ok and not errors:
        print(f"{app_id}: {status or 'key ready'}")
    else:
        ok = False
        print(f"{app_id}: HTTP {r.status_code} {errors[:1] or r.text[:200]}")
sys.exit(0 if ok else 1)
