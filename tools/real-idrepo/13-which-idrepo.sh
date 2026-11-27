#!/usr/bin/env bash
# Step 13: show which ID Repository register-id is using right now, and the newest records in each.
# Run it before and after an enrolment in the portal: the REAL count goes up only when the app is on the real one.
set -uo pipefail
PG=register-id-postgres
url=$(docker exec register-id-app sh -c 'echo $MOSIP_IDREPO_BASE_URL')
echo "register-id app -> MOSIP_IDREPO_BASE_URL=$url"
case "$url" in
  *idrepo-real*) echo "   = REAL MOSIP ID Repository (mosipid/id-repository-identity-service:1.2.0.1)" ;;
  *idrepo:8080*) echo "   = MOCK IDRepo (register-id's src/mock)" ;;
  *)             echo "   = something else" ;;
esac
echo
echo "== REAL IDRepo database (mosip_idrepo.idrepo.uin): data is stored encrypted, so no names are visible"
MSYS_NO_PATHCONV=1 docker exec "$PG" psql -U postgres -d mosip_idrepo -c \
  "select count(*) as records, max(cr_dtimes) as newest from idrepo.uin;" 2>/dev/null
MSYS_NO_PATHCONV=1 docker exec "$PG" psql -U postgres -d mosip_idrepo -c \
  "select reg_id, status_code, cr_dtimes, (select count(*) from idrepo.uin_biometric b where b.uin_ref_id = u.uin_ref_id) as face_docs
   from idrepo.uin u order by cr_dtimes desc limit 3;" 2>/dev/null
echo
echo "== Last real IDRepo log lines about register-id"
docker logs idrepo-real --since 10m 2>&1 | grep -o '"message":"[^"]*"' \
  | grep -i "offline verification done\|IDENTITY_CREATED\|addIdentity\|retrieveIdentity" | tail -4 | cut -c1-160
