#!/usr/bin/env bash
# Full stack in Docker: app, Redis, and whatever the MOSIP overlay adds.
#
# The image does not see files on disk until this script is run again.
#
# Usage: bash scripts/web-docker.sh
# Restart the whole stack: run the script again.
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_web-common.sh"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed." >&2
  exit 1
fi

free_app_port
echo "Building and starting the compose stack..."
docker compose up -d --build
echo ""
echo "Enrollment page: http://localhost:${APP_PORT}"
echo "Use localhost, not a LAN IP, or the browser will block the webcam."
