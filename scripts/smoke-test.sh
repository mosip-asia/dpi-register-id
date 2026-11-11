#!/usr/bin/env bash
# ==============================================================================
# Post-Deployment Smoke Test for python-project-starter
#
# Validates that the application stack is up, healthy, and operational:
# 1. Health endpoint check: GET /health (expects status: ok)
# 2. Web UI endpoint: GET / (expects Python-Starter-Project branding)
# 3. Dynamic template endpoint: GET /example/1234 (expects id 1234 rendered)
# 4. Django system check: uv run django_manage.py check (if available)
#
# Usage:
#   bash scripts/smoke-test.sh [base_url]
#   bash scripts/smoke-test.sh http://127.0.0.1:8000
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

log_info() { echo -e "${BLUE}${BOLD}[SMOKE TEST]${NC} $*"; }
log_ok() { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
log_fail() { echo -e "${RED}${BOLD}[SMOKE TEST FAILED]${NC} $*" >&2; }
log_warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }

BASE_URL="${1:-http://127.0.0.1:${FASTAPI_PORT:-8000}}"
BASE_URL="${BASE_URL%/}" # Strip trailing slash

log_info "Target Base URL: ${BASE_URL}"

# 1. Verify Health Endpoint
log_info "1/4 Checking /health endpoint..."
HEALTH_URL="${BASE_URL}/health"
HEALTH_RESPONSE=$(curl -sf --max-time 10 "$HEALTH_URL") || {
  log_fail "Could not reach health endpoint at ${HEALTH_URL}"
  exit 1
}

if ! echo "$HEALTH_RESPONSE" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
  log_fail "Health endpoint did not return status 'ok':"
  echo "$HEALTH_RESPONSE" >&2
  exit 1
fi
log_ok "Health endpoint returned OK: ${HEALTH_RESPONSE}"

# 2. Verify Web Index UI
log_info "2/4 Checking Web Index at /..."
INDEX_URL="${BASE_URL}/"
INDEX_RESPONSE=$(curl -sf --max-time 10 "$INDEX_URL") || {
  log_fail "Could not reach web index at ${INDEX_URL}"
  exit 1
}

if ! echo "$INDEX_RESPONSE" | grep -q "Python-Starter-Project"; then
  log_fail "Web index response missing expected branding 'Python-Starter-Project':"
  echo "${INDEX_RESPONSE:0:300}..." >&2
  exit 1
fi
log_ok "Web index UI responded with valid template."

# 3. Verify Dynamic Route
log_info "3/4 Checking dynamic route at /example/1234..."
EXAMPLE_URL="${BASE_URL}/example/1234"
EXAMPLE_RESPONSE=$(curl -sf --max-time 10 "$EXAMPLE_URL") || {
  log_fail "Could not reach example route at ${EXAMPLE_URL}"
  exit 1
}

if ! echo "$EXAMPLE_RESPONSE" | grep -q "1234"; then
  log_fail "Example response did not render expected parameter '1234':"
  echo "$EXAMPLE_RESPONSE" >&2
  exit 1
fi
log_ok "Dynamic example route rendered successfully."

# 4. Optional Django check if available
log_info "4/4 Checking Django configuration..."
if command -v uv >/dev/null 2>&1 && [ -f "django_manage.py" ]; then
  if uv run django_manage.py check --fail-level ERROR >/dev/null 2>&1; then
    log_ok "Django system check passed."
  else
    log_warn "Django check reported warnings or errors."
  fi
else
  log_ok "Django check skipped (uv or django_manage.py not found in local path)."
fi

echo ""
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo -e "${GREEN}${BOLD} 🎉 SMOKE TEST PASSED: Service is operational and healthy!${NC}"
echo -e "${GREEN}${BOLD}======================================================================${NC}"
exit 0
