#!/usr/bin/env bash
# Local checks before pushing: data guard, tests, and django integrity check.
#
# Usage: bash scripts/check.sh
# Exit codes: 0 every check passed, otherwise the exit code of the first failure.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

step() { echo ""; echo "== $*"; }

step "data guard"
bash scripts/check-data-guard.sh

step "pytest"
if command -v uv >/dev/null 2>&1; then
  uv run pytest -q
elif command -v pytest >/dev/null 2>&1; then
  pytest -q
fi

step "django check"
if command -v uv >/dev/null 2>&1 && [ -f "django_manage.py" ]; then
  uv run django_manage.py check
fi

echo ""
echo "✅ check: all checks passed!"
