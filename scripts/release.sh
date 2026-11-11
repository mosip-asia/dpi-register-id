#!/usr/bin/env bash
# ==============================================================================
# Release and Promotion Helper for python-project-starter
#
# Three branches / environments:
#   dev   <- default working branch; release tags v* are cut here
#   stg   <- staging environment; updated via PR (dev -> stg) or promote
#   main  <- production environment; updated via PR (stg -> main) or promote
#
# Usage:
#   bash scripts/release.sh vX.Y.Z
#       Runs pre-flight checks, tags origin/dev as vX.Y.Z, pushes tag, triggers
#       CI (test -> build & push Docker image to GHCR), and creates GitHub release.
#
#   bash scripts/release.sh pr stg
#       Creates a Pull Request from 'dev' into 'stg' to trigger Staging deployment.
#
#   bash scripts/release.sh pr main
#       Creates a Pull Request from 'stg' into 'main' to trigger Production deployment.
#
#   bash scripts/release.sh promote stg [vX.Y.Z]
#       Fast-forwards branch 'stg' directly to a release tag and pushes it.
#
#   bash scripts/release.sh promote main [vX.Y.Z]
#       Fast-forwards branch 'main' directly to the release tag and pushes it.
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
NC="\033[0m"

log_info() { echo -e "${BLUE}${BOLD}[INFO]${NC} $*"; }
log_ok() { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}${BOLD}[ERROR]${NC} $*" >&2; }

retry() {
  local attempts="$1" delay="$2" n=1
  shift 2
  until "$@"; do
    if ((n >= attempts)); then
      return 1
    fi
    log_warn "Attempt ${n}/${attempts} failed: $*. Retrying in ${delay}s..."
    n=$((n + 1))
    sleep "$delay"
  done
}

confirm() {
  local answer
  read -r -p "$1 [y/N]: " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]]
}

banner() {
  echo ""
  echo -e "${BOLD}======================================================================${NC}"
  echo -e "${BOLD}  $*${NC}"
  echo -e "${BOLD}======================================================================${NC}"
}

SCRIPT_PATH="${BASH_SOURCE[0]}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd -P)"
cd "$ROOT_DIR"

# Docker Compose path separator for multi-file overlays
export COMPOSE_PATH_SEPARATOR=:

SEMVER='^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'
REPO_SLUG="$(git remote get-url origin 2>/dev/null | sed -E 's#\.git$##; s#^.*github\.com[:/]##' || echo "")"
ACTIONS_URL="https://github.com/${REPO_SLUG}/actions"

# Source repository-specific release checks if present
if [[ -f "${ROOT_DIR}/scripts/release-checks.sh" ]]; then
  # shellcheck source=scripts/release-checks.sh
  source "${ROOT_DIR}/scripts/release-checks.sh"
else
  run_release_checks() {
    log_info "No custom release-checks.sh found; running basic tests..."
    if command -v uv >/dev/null 2>&1; then
      uv run pytest -q
    fi
  }
fi

describe_env() {
  case "$1" in
    dev) echo "Development (dev branch)" ;;
    stg | staging) echo "Staging (staging environment)" ;;
    main | production) echo "Production (production environment)" ;;
  esac
}

usage() {
  sed -n '2,26p' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//'
}

# release_tags [ref]: release tags (vX.Y.Z), oldest first; only reachable from ref if provided
release_tags() {
  if [[ -n "${1:-}" ]]; then
    git tag --merged "$1" --list 'v*'
  else
    git tag --list 'v*'
  fi | { grep -E "$SEMVER" || true; } | sort -V
}

# ------------------------------------------------------------------------------
# release vX.Y.Z: tag the tip of origin/dev
# ------------------------------------------------------------------------------
release() {
  local version="$1"
  if [[ ! "$version" =~ $SEMVER ]]; then
    log_err "Invalid version tag '${version}'."
    log_err "Use Semantic Versioning with a leading 'v' (e.g. v0.1.0, v1.0.0, v1.0.0-rc1)."
    exit 1
  fi

  log_info "Running local pre-flight checks..."
  if [[ -n "$(git status --porcelain)" ]]; then
    log_err "Working tree is dirty. Please commit, stash, or discard local changes first:"
    git status -s
    exit 1
  fi

  log_info "Fetching latest branches and tags from origin..."
  retry 3 5 git fetch -q --tags origin
  local dev_commit
  dev_commit="$(git rev-parse origin/dev)"

  # Check if tag already exists
  if git rev-parse -q --verify "refs/tags/${version}" >/dev/null; then
    local tag_commit
    tag_commit="$(git rev-parse "refs/tags/${version}^{commit}")"
    if [[ "$tag_commit" != "$dev_commit" ]]; then
      log_err "Tag '${version}' already exists and points to ${tag_commit:0:7}, not origin/dev (${dev_commit:0:7})."
      log_err "Tags are immutable. Please pick a new version (e.g. patch bump)."
      exit 1
    fi
    log_warn "Tag '${version}' already points to origin/dev (${dev_commit:0:7}). Continuing with push..."
  else
    # Run verification suite
    banner "RUNNING PRE-RELEASE VERIFICATION SUITE"
    if ! run_release_checks; then
      log_err "Release checks failed. Aborting release."
      exit 1
    fi

    banner "CUTTING RELEASE ${GREEN}${version}${NC} FROM ${BOLD}origin/dev${NC}"
    echo -e "${BOLD}Target Commit:${NC} ${dev_commit:0:7}"
    git --no-pager log -n 5 --oneline "$dev_commit"
    echo ""

    if ! confirm "Create and tag release ${version}?"; then
      log_warn "Aborted by user."
      exit 0
    fi

    log_info "Creating annotated tag ${version}..."
    git tag -a "$version" -m "Release ${version}" "$dev_commit"
  fi

  # Push tag
  log_info "Pushing tag ${version} to origin..."
  if ! retry 3 5 git push origin "refs/tags/${version}"; then
    log_err "Pushing tag failed. Run this command again to retry."
    exit 1
  fi

  # Create GitHub release if gh CLI is available and authenticated
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    log_info "Creating GitHub Release via gh CLI..."
    if ! gh release view "$version" >/dev/null 2>&1; then
      gh release create "$version" --title "Release ${version}" --generate-notes || log_warn "Could not create GitHub release via CLI."
    fi
  fi

  banner "${GREEN}🎉 Release ${version} created and tag pushed!${NC}"
  echo -e "CI/CD Actions: ${BLUE}${ACTIONS_URL}${NC}"
  echo -e "Docker image build & push to GHCR has been triggered by tag ${version}."
  echo ""
  echo -e "${BOLD}Promotion & Deployment Steps:${NC}"
  echo -e "1. Deploy to Staging (stg):"
  echo -e "   Create and merge a Pull Request from 'dev' to 'stg':"
  echo -e "     ${BOLD}bash scripts/release.sh pr stg${NC}"
  echo -e "   (Or direct fast-forward: ${BOLD}bash scripts/release.sh promote stg ${version}${NC})"
  echo ""
  echo -e "2. Deploy to Production (main):"
  echo -e "   Once verified on Staging, create and merge a Pull Request from 'stg' to 'main':"
  echo -e "     ${BOLD}bash scripts/release.sh pr main${NC}"
  echo -e "   (Or direct fast-forward: ${BOLD}bash scripts/release.sh promote main ${version}${NC})"
  echo ""
}

# ------------------------------------------------------------------------------
# promote stg|main [vX.Y.Z]: fast-forward the branch to a release tag
# ------------------------------------------------------------------------------
promote() {
  local target="${1:-}" version="${2:-}"
  if [[ "$target" != "stg" && "$target" != "main" ]]; then
    log_err "Usage: bash scripts/release.sh promote stg|main [vX.Y.Z]"
    exit 2
  fi
  if [[ -n "$version" && ! "$version" =~ $SEMVER ]]; then
    log_err "Invalid version tag '${version}'."
    exit 1
  fi

  log_info "Fetching latest branches and tags from origin..."
  retry 3 5 git fetch -q --tags origin

  local src tag
  if [[ "$target" == "stg" ]]; then
    tag="${version:-$(release_tags origin/dev | tail -n 1)}"
    if [[ -z "$tag" ]]; then
      log_err "There is no release tag on dev yet: run bash scripts/release.sh vX.Y.Z first."
      exit 1
    fi
    if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
      log_err "Tag '${tag}' is not found on origin. Release it first with bash scripts/release.sh ${tag}"
      exit 1
    fi
    src="$(git rev-parse "${tag}^{commit}")"
    if ! git merge-base --is-ancestor "$src" origin/dev; then
      log_err "Tag '${tag}' (${src:0:7}) is not on 'dev': only releases cut from dev are promoted."
      exit 1
    fi
  else
    # Promoting to main (production)
    if ! git rev-parse -q --verify origin/stg >/dev/null 2>&1; then
      log_err "Branch 'stg' does not exist on origin: promote to stg first."
      exit 1
    fi
    src="$(git rev-parse origin/stg)"
    if [[ -n "$version" ]]; then
      if ! git tag --points-at "$src" | grep -qxF "$version"; then
        log_err "'stg' (${src:0:7}) is not at ${version}: promote ${version} to stg and test it there first."
        exit 1
      fi
      tag="$version"
    else
      tag="$(git tag --points-at "$src" --list 'v*' | { grep -E "$SEMVER" || true; } | sort -V | tail -n 1)"
    fi
    if [[ -z "$tag" ]]; then
      log_err "'stg' (${src:0:7}) is not at a release tag: only a released and staging-tested commit goes to production."
      exit 1
    fi
  fi

  local current=""
  if git rev-parse -q --verify "origin/${target}" >/dev/null 2>&1; then
    current="$(git rev-parse "origin/${target}")"
    if [[ "$current" == "$src" ]]; then
      log_ok "'${target}' is already at ${tag} (${src:0:7}): nothing to do."
      exit 0
    fi
    if ! git merge-base --is-ancestor "$current" "$src"; then
      log_err "'${target}' (${current:0:7}) is not an ancestor of ${tag} (${src:0:7}): promotion must be a fast-forward."
      log_err "Never force-push '${target}'. Fix the branch ancestry first."
      exit 1
    fi
  fi

  banner "PROMOTE ${GREEN}${tag}${NC}${BOLD} to '${target}'"
  if [[ -n "$current" ]]; then
    echo -e "Commits advancing '${target}' (from ${current:0:7}):"
    git --no-pager log --oneline "${current}..${src}"
  else
    echo -e "'${target}' does not exist on origin yet: will be created at ${tag}."
    git --no-pager log --oneline -n 5 "$src"
  fi
  echo -e "${BOLD}Promoting Tag:${NC} ${tag} (${src:0:7})"
  echo -e "${BOLD}Target Environment:${NC} $(describe_env "$target")"
  echo ""
  if [[ "$target" == "main" ]]; then
    log_warn "⚠️  ATTENTION: This promotes and deploys to PRODUCTION (main)!"
  fi

  if ! confirm "Promote ${tag} to '${target}'?"; then
    log_warn "Promotion aborted; nothing was pushed."
    exit 0
  fi

  log_info "Pushing ${tag} to '${target}' on origin..."
  if ! retry 3 5 git push -q origin "${src}:refs/heads/${target}"; then
    log_err "Pushing '${target}' failed. Run the command again to retry."
    exit 1
  fi

  banner "${GREEN}🎉 ${tag} promoted to '${target}' successfully!${NC}"
  echo -e "Watch Actions/Deployment: ${BLUE}${ACTIONS_URL}${NC}"
  if [[ "$target" == "stg" ]]; then
    echo -e "After verifying on Staging: ${BOLD}bash scripts/release.sh pr main${NC} (or ${BOLD}promote main${NC})"
  fi
  echo ""
}

# ------------------------------------------------------------------------------
# pr stg|main: create a Pull Request to promote code
#   pr stg  -> opens PR dev into stg (merging deploys to Staging)
#   pr main -> opens PR stg into main (merging deploys to Production)
# ------------------------------------------------------------------------------
create_pr() {
  local target="${1:-}"
  if [[ "$target" != "stg" && "$target" != "main" ]]; then
    log_err "Usage: bash scripts/release.sh pr stg|main"
    exit 2
  fi

  local base head title
  if [[ "$target" == "stg" ]]; then
    base="stg"
    head="dev"
    title="Promote dev to Staging"
  else
    base="main"
    head="stg"
    title="Promote Staging to Production (main)"
  fi

  banner "CREATE PULL REQUEST: ${head} -> ${base}"
  echo -e "Merging this PR will trigger automated deployment to: $(describe_env "$base")"
  echo ""

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    log_info "Creating Pull Request via gh CLI..."
    gh pr create --base "$base" --head "$head" --title "$title" --body "Automated promotion PR from \`${head}\` into \`${base}\`." || {
      log_warn "Failed to create PR automatically with gh CLI."
      echo -e "You can create it manually at: https://github.com/${REPO_SLUG}/compare/${base}...${head}"
    }
  else
    log_info "GitHub CLI (gh) not authenticated or not installed."
    echo -e "Open the following link to create the Pull Request:"
    echo -e "  ${BLUE}https://github.com/${REPO_SLUG}/compare/${base}...${head}?expand=1${NC}"
  fi
}

# ------------------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------------------
case "${1:-}" in
  promote)
    shift
    promote "$@"
    ;;
  pr)
    shift
    create_pr "$@"
    ;;
  -h | --help)
    usage
    ;;
  "")
    usage
    echo ""
    read -r -p "Version to release (e.g. v0.1.0), or Enter to cancel: " ANSWER
    if [[ -z "$ANSWER" ]]; then
      exit 0
    fi
    release "$ANSWER"
    ;;
  *)
    release "$1"
    ;;
esac
