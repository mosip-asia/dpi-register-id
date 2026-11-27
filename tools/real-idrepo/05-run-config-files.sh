#!/usr/bin/env bash
# Step 5: a tiny web server that hands out the JSON/XSD files the ID Repository downloads at
# startup (in the Kit, the MOSIP config server does this). Uses the register-id image's Python.
set -euo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"
docker rm -f config-files >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name config-files --network register-id_default --memory 128m \
  -v "$here/config:/srv:ro" -w /srv --entrypoint python3 register-id:dev -m http.server 8000
