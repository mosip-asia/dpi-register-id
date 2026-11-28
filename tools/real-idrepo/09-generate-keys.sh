#!/usr/bin/env bash
# Step 9: generate keymanager master keys (ROOT, KERNEL, ID_REPO). See 09-generate-keys.py.
set -euo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"
MSYS_NO_PATHCONV=1 docker cp "$here/09-generate-keys.py" register-id-app:/tmp/generate_keys.py >/dev/null
MSYS_NO_PATHCONV=1 docker exec --env-file idrepo.env register-id-app python3 /tmp/generate_keys.py
