#!/usr/bin/env bash
# Shared setup for the web run scripts. Source this file; do not execute it.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Source this file from another script. Do not run it directly." >&2
  exit 1
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
  else
    echo "Missing .env and .env.example." >&2
    exit 1
  fi
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

APP_PORT="${FASTAPI_PORT:-8000}"
APP_HOST="${FASTAPI_HOST:-0.0.0.0}"

compose_has() {
  docker compose config --services | grep -qx "$1"
}

# Stop a previous listener so re-running a script restarts the server.
free_app_port() {
  local pids
  pids="$(lsof -nP -iTCP:"${APP_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Stopping process already listening on port ${APP_PORT}: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 0.5
  pids="$(lsof -nP -iTCP:"${APP_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
}

# Redis, Postgres, the mock IDRepo, and Keycloak. Skip any service the
# active COMPOSE_FILE does not define. Leave the app container stopped so
# it does not keep port 8000 while a local server is running.
start_backing_services() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed. Backing services were not started." >&2
    exit 1
  fi

  local want=(redis postgres keycloak idrepo)
  local start=()
  local name
  for name in "${want[@]}"; do
    if compose_has "$name"; then
      start+=("$name")
    fi
  done

  if compose_has app; then
    docker compose stop app >/dev/null
  fi

  if [[ ${#start[@]} -eq 0 ]]; then
    echo "No backing services are defined in the current COMPOSE_FILE."
    return 0
  fi

  echo "Starting backing services: ${start[*]}"
  docker compose up -d "${start[@]}"
}

print_page_url() {
  echo ""
  echo "Enrollment page: http://localhost:${APP_PORT}"
  echo "Use localhost, not a LAN IP, or the browser will block the webcam."
  echo "Stop with Ctrl+C. Run this script again to restart."
  echo ""
}
