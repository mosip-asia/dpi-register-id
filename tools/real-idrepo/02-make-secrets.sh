#!/usr/bin/env bash
# Step 2: create idrepo.env with random local test secrets (database password, client secret,
# salts, keystore password). Run once. The file stays on this laptop; do not commit or share it.
# Re-running adds only the values that are missing.
set -euo pipefail
cd "$(dirname "$0")"
touch idrepo.env
add() {  # name value
  grep -q "^$1=" idrepo.env || { echo "$1=$2" >> idrepo.env; echo "added $1"; }
}
add IDREPO_DB_PASSWORD   "$(openssl rand -hex 12)"
add IDREPO_AUTH_SECRET   "$(openssl rand -hex 16)"
add IDREPO_UIN_SALT      "$(openssl rand -hex 8)"
add IDREPO_S3_ACCESS_KEY local
add IDREPO_S3_SECRET_KEY "$(openssl rand -hex 12)"
add IDREPO_KEYSTORE_PIN  "$(openssl rand -hex 8)"
echo "idrepo.env ready"
