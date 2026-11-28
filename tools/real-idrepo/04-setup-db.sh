#!/usr/bin/env bash
# Step 4: create the MOSIP databases in register-id's Postgres, using MOSIP's own scripts:
#   mosip_idrepo, mosip_idmap (ID Repository), mosip_master (masterdata), mosip_keymgr (keymanager).
# Then fill the 1000 UIN salts (MOSIP's salt-generator job) and, if seed/identity_schema.sql exists
# (from 03-identity-schema.py), load the identity schema into masterdata.
# An existing database is skipped, so re-running is safe.
set -euo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"
PG=register-id-postgres
PW=$(grep '^IDREPO_DB_PASSWORD=' idrepo.env | cut -d= -f2-)

MSYS_NO_PATHCONV=1 docker exec "$PG" mkdir -p /tmp/db
MSYS_NO_PATHCONV=1 docker cp "$here/db_scripts/." "$PG:/tmp/db"
for d in mosip_idrepo mosip_idmap mosip_master mosip_keymgr; do
  echo "== $d"
  if [ ! -d "db_scripts/$d" ]; then echo "   no scripts downloaded, skipping"; continue; fi
  if MSYS_NO_PATHCONV=1 docker exec "$PG" psql -U postgres -At -c "select 1 from pg_database where datname='$d'" | grep -q 1; then
    echo "   already exists, skipping create"
  else
    MSYS_NO_PATHCONV=1 docker exec -w "/tmp/db/$d" "$PG" sh -c "
      psql -q -U postgres -v ON_ERROR_STOP=1 -f role_dbuser.sql -v dbuserpwd=\"'$PW'\" &&
      psql -q -U postgres -v ON_ERROR_STOP=1 -f db.sql &&
      psql -q -U postgres -v ON_ERROR_STOP=1 -f ddl.sql &&
      psql -q -U postgres -v ON_ERROR_STOP=1 -f grants.sql" >/dev/null
    if [ "$d" = mosip_keymgr ]; then
      # keymanager's DML: key policies (validity per application id). Other DBs' seed data is not needed here.
      MSYS_NO_PATHCONV=1 docker exec -w "/tmp/db/$d" "$PG" psql -q -U postgres -v ON_ERROR_STOP=1 -f dml.sql >/dev/null
    fi
    echo "   created"
  fi
done

echo "== UIN salts (ids 0-999, as mosip.kernel.salt-generator.start/end-sequence)"
for pair in mosip_idrepo:idrepo mosip_idmap:idmap; do
  d=${pair%%:*}; s=${pair##*:}
  for t in uin_hash_salt uin_encrypt_salt; do
    MSYS_NO_PATHCONV=1 docker exec "$PG" psql -q -U postgres -d "$d" -c \
      "insert into $s.$t (id, salt, cr_by, cr_dtimes)
       select g, substr(md5(random()::text || clock_timestamp()::text), 1, 32), 'local-salt-setup', now()
       from generate_series(0,999) g on conflict (id) do nothing;"
    echo "   $d.$t: $(MSYS_NO_PATHCONV=1 docker exec "$PG" psql -U postgres -d "$d" -At -c "select count(*) from $s.$t") rows"
  done
done

if [ -f seed/identity_schema.sql ]; then
  echo "== Identity schema into mosip_master"
  MSYS_NO_PATHCONV=1 docker cp "$here/seed/identity_schema.sql" "$PG:/tmp/identity_schema.sql"
  MSYS_NO_PATHCONV=1 docker exec "$PG" psql -q -U postgres -d mosip_master -v ON_ERROR_STOP=1 -f /tmp/identity_schema.sql
  echo "   rows: $(MSYS_NO_PATHCONV=1 docker exec "$PG" psql -U postgres -d mosip_master -At -c "select count(*) from master.identity_schema")"
fi
