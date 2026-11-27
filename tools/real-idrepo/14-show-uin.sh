#!/usr/bin/env bash
# Step 14: look up ONE registration number (UIN) directly in the REAL MOSIP ID Repository.
# Usage: bash 14-show-uin.sh 2062936597
# It asks the real IDRepo (not register-id's mock) through register-id's own client, so a hit proves
# the record lives in the real IDRepo. Shows demographics, whether a face (CBEFF) is stored, and how
# many face-match vectors verify will use. Prints no face image.
set -uo pipefail
uin="${1:?usage: bash 14-show-uin.sh <UIN>}"
MSYS_NO_PATHCONV=1 docker exec -i register-id-app python3 - "$uin" <<'PY'
import sys
from register_id.cbeff import descriptors_from_cbeff
from register_id.idrepo_client import IDRepoClient

uin = sys.argv[1]
real = IDRepoClient(base_url="http://idrepo-real:8090", enable_inprocess_fallback=False)
mock = IDRepoClient(base_url="http://idrepo:8080", enable_inprocess_fallback=False)

record = real.get_identity(uin, include_biometrics=True)
if not record:
    print(f"REAL IDRepo: UIN {uin} NOT found")
else:
    cbeff = record.get("cbeff_xml") or ""
    print(f"REAL IDRepo: UIN {uin} FOUND")
    print(f"  name        : {record.get('full_name')}")
    print(f"  email       : {record.get('email')}")
    print(f"  face (CBEFF): {'stored, ' + str(len(cbeff)) + ' characters' if cbeff else 'none'}")
    print(f"  face vectors: {len(descriptors_from_cbeff(cbeff))} (what verify compares against)")

print(f"MOCK IDRepo : UIN {uin} {'found' if mock.get_identity(uin) else 'not found'}")
PY
