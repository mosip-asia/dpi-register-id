#!/usr/bin/env bash
# Step 11: health check, then send one test identity from register-id's own client code to the
# REAL ID Repository (not the mock), and read it back. Prints the result; no secrets.
# The UIN comes from mosip_uin.py (MOSIP's UIN rules), because register-id's mock generator
# returns numbers the real ID Repository rejects.
set -uo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"
MSYS_NO_PATHCONV=1 docker cp "$here/mosip_uin.py" register-id-app:/tmp/mosip_uin.py >/dev/null

echo "== Health"
docker exec register-id-app python3 -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://idrepo-real:8090/idrepository/v1/identity/actuator/health', timeout=30)
    print(r.status, r.read()[:200].decode())
except Exception as e:
    print('NOT READY', getattr(e, 'code', ''), e.read()[:300].decode() if hasattr(e, 'read') else e)
"
echo "== Create one identity with register-id's IDRepoClient, then read it back"
MSYS_NO_PATHCONV=1 docker exec -w /tmp register-id-app python3 -c "
from mosip_uin import new_uin
from register_id.idrepo_client import IDRepoClient
c = IDRepoClient(base_url='http://idrepo-real:8090', enable_inprocess_fallback=False)
uin = new_uin()
ok = c.add_identity(uin=uin, full_name='Real Repo Test', email='real.repo@example.org',
    date_of_birth='1990-01-01', gender='Female', phone='9876543210', address_line1='L1',
    address_line2='L2', address_line3='L3', region='R', province='P', city='C', zone='Z',
    postal_code='10200', reference_identity_number='1234567890', status='draft')
print('uin:', uin)
print('saved:', ok, '| backend:', c.last_backend, '| error:', c.last_error)
if ok:
    back = c.get_identity(uin)
    print('read back:', 'found' if back else 'NOT found', '| name:', back.get('full_name') if back else None)
"
echo "== Last IDRepo messages"
docker logs idrepo-real --since 2m 2>&1 | grep -o '\"message\":\"[^\"]*\"' \
  | grep -v 'appears to have started\|accessToken\|^\"message\":\"\"' | tail -4 | cut -c1-300
