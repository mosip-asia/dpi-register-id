#!/usr/bin/env bash
# Local web server. Template and Python edits apply after a restart.
#
# Starts Redis, Postgres, mock IDRepo, and Keycloak when the compose file
# defines them, then runs the app on the host.
#
# Usage: bash scripts/web-local.sh
# Restart: run the script again (it frees the app port first).
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_web-common.sh"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed." >&2
  exit 1
fi

start_backing_services
free_app_port
print_page_url
exec uv run register-id web start
