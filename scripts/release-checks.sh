# shellcheck shell=bash
# ==============================================================================
# Repository release checks, sourced by scripts/release.sh.
# Defines run_release_checks; runs from repo root before cutting a release.
# ==============================================================================

run_release_checks() {
  log_info "Running the sensitive data guard..."
  if ! bash scripts/check-data-guard.sh; then
    log_err "The data guard refused the tree (spreadsheets, database dumps, CRLF or large files)."
    return 1
  fi

  log_info "Running tests via pytest..."
  if command -v uv >/dev/null 2>&1; then
    if ! uv run pytest -q; then
      log_err "Unit tests failed under 'uv run pytest'."
      return 1
    fi
  elif command -v pytest >/dev/null 2>&1; then
    if ! pytest -q; then
      log_err "Unit tests failed under 'pytest'."
      return 1
    fi
  else
    log_warn "pytest not found on PATH; skipping unit test verification."
  fi

  log_info "Verifying Django system configuration..."
  if command -v uv >/dev/null 2>&1 && [[ -f "django_manage.py" ]]; then
    if ! uv run django_manage.py check --fail-level ERROR; then
      log_err "Django configuration check failed."
      return 1
    fi
  fi

  log_ok "All release checks passed."
  return 0
}
