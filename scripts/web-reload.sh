#!/usr/bin/env bash
# Local web server with auto-reload. Python and template edits apply on save.
#
# Usage: bash scripts/web-reload.sh
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
exec uv run uvicorn project.web:app --host "${APP_HOST}" --port "${APP_PORT}" --reload
