#!/usr/bin/env bash
# Rebuild and recreate only the web container. Redis, Postgres, IDRepo,
# and Keycloak are left running.
#
# Usage: bash scripts/web-docker-restart.sh
set -euo pipefail

# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/_web-common.sh"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed." >&2
  exit 1
fi

if ! compose_has app; then
  echo "The current COMPOSE_FILE has no app service." >&2
  exit 1
fi

free_app_port
echo "Rebuilding and restarting the app container..."
docker compose up -d --build app
echo ""
echo "Enrollment page: http://localhost:${APP_PORT}"
echo "Use localhost, not a LAN IP, or the browser will block the webcam."
