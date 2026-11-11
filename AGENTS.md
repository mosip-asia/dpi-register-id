# Repository Guidelines & Operational Invariants

This document defines the architectural patterns, operational invariants, and workflow standards for AI agents (Antigravity, Claude Code, Cursor, Codex) and human developers contributing to this repository and projects derived from it.

---

## 1. Branching, Release & Deployment Lifecycle

* **Default Branch (`dev`):**
  - All active feature branches branch off `dev` and merge back into `dev`.
  - Pushes directly to `dev` never trigger automated deployments. CI runs are manual (`workflow_dispatch`) by default.
* **Release & GHCR Workflow (`scripts/release.sh vX.Y.Z`):**
  - Releases are cut exclusively from `dev` using Semantic Versioning (`vX.Y.Z`).
  - Pushing the release tag `v*` triggers `.github/workflows/ci.yml`, which:
    1. Executes unit and integration tests via `uv run pytest`.
    2. Builds the multi-stage Docker `runner` image.
    3. Pushes tagged images (`vX.Y.Z`, `vX.Y`, `latest`) to GitHub Container Registry (`ghcr.io`).
    4. Publishes a GitHub Release with auto-generated release notes.
* **Environment Promotion via Pull Requests:**
  - **Staging (`stg` branch):** Promoted by opening and merging a PR from `dev` into `stg` (`bash scripts/release.sh pr stg`). Merging automatically triggers the CD workflow targeting the `staging` environment.
  - **Production (`main` branch):** Promoted by opening and merging a PR from `stg` into `main` (`bash scripts/release.sh pr main`). Merging automatically triggers the CD workflow targeting the `production` environment.
  - Nothing enters `stg` or `main` directly: no unreviewed direct pushes and never a force push.

---

## 2. CI/CD & Deployment Symmetry

* **Strict Environment Symmetry:**
  Both `staging` and `production` run the **exact same deployment job** in [`.github/workflows/cd.yml`](.github/workflows/cd.yml).
* **The 5 Deployment Variables / Secrets:**
  Each GitHub Environment (`staging` and `production`) must define exactly:
  1. `NETBIRD_KEY` or `NETBIRD_SETUP_KEY` (Secret): Setup key for NetBird VPN mesh connection.
  2. `SSH_PRIVATE_KEY` (Secret): SSH private key for host authentication.
  3. `SERVER_HOST` (Variable): Target server IP or NetBird mesh hostname.
  4. `SERVER_USER` (Variable): Target host SSH username.
  5. `SERVER_PROJECT_DIR` (Variable): Remote application directory on host.
* **No Silent Fallbacks in Deployment Workflows:**
  Avoid hardcoding fallback values for server hosts, users, or secrets. Missing credentials must fail immediately during the pre-flight check step ([`.github/actions/preflight-check`](.github/actions/preflight-check)).

---

## 3. Configuration & Docker Compose Invariants

* **Single Environment Template (`.env.example`):**
  - Do **not** reintroduce `local.env` or multiple `.env.*.example` files.
  - Local setup is always `cp .env.example .env`.
  - In remote environments, the server host stores its environment in `.env`.
* **No Default Fallback Variables in Compose:**
  - Variables in [`docker-compose.yml`](docker-compose.yml) must be explicitly supplied by `.env` (e.g. `${PROJECT_NAME}`, `${REDIS_PASSWORD}`, `${FASTAPI_PORT}`, `${REDIS_PORT}`).
  - Do not use inline fallbacks like `${PROJECT_NAME:-python-project-starter}` or `${REDIS_PASSWORD:-redispassword}`.
  - Services use explicit `environment:` mappings in `docker-compose.yml` instead of `env_file:` to clearly define container contracts and isolate container networking (e.g. `redis://:${REDIS_PASSWORD}@redis:6379/0`) from host `localhost`.
* **Traefik Reverse Proxy Overlay:**
  - In local development, the app maps ports directly to `http://localhost:8000` (`COMPOSE_FILE=docker-compose.yml`).
  - In deployed environments behind a shared Traefik gateway, enable the overlay in the server's `.env`:
    ```ini
    COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
    APP_HOSTNAME_DOMAIN=api-stg.ait.ac.th
    ```
  - [`docker-compose.traefik.yml`](docker-compose.traefik.yml) joins the external `traefik_public` network and dynamically registers ingress routing and SSL certificates with Let's Encrypt.

---

## 4. SSH Remote Script Execution Standard

* When executing multi-line shell scripts over SSH from GitHub Actions runners, **never** pass the script as a direct command string argument (`ssh host "$CMD"`).
* Always pass the command via an environment variable and pipe it into `stdin` using `<<< "$SSH_CMD"` to prevent quote escaping issues and client-side shell expansions:
  ```yaml
  env:
    SSH_CMD: ${{ inputs.cmd }}
  run: |
    ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
      "${{ inputs.server-user }}@${{ inputs.server-host }}" \
      "bash -se" <<< "$SSH_CMD"
  ```

---

## 5. Deployment Safeguards & "Fail Forward" Standard

* **Automated Smoke Testing:**
  - Every deployment must execute [`scripts/smoke-test.sh`](scripts/smoke-test.sh) before declaring success.
  - Verifies `/health` responds with `status: ok`, checks web UI routes, and validates Django system integrity. Never rely solely on container port reachability.
* **Persistent Host Baseline (`.deploy_success`):**
  - Remote deployment workflows record the deployed commit SHA in `.deploy_success` only *after* deployment and smoke tests succeed.
  - If deployment or smoke tests fail, the server immediately rolls back to the last verified commit in `.deploy_success`.
* **Fail Forward Policy:**
  - Release tags are immutable: never delete, move, or force-push Git tags.
  - If a release deployment fails, the server rolls back automatically. Fixes are merged into `dev` and released under the next sequential SemVer tag (e.g., `v0.1.0` fails → fix on `dev` → release `v0.1.1`).

---

## 6. Codebase Hygiene & Data Guard

* **Sensitive Data Guard (`scripts/check-data-guard.sh`):**
  - Never commit credentials, database dumps (`*.sql`, `*.dump`), spreadsheets (`*.xlsx`, `*.xls`), or real user PII to Git.
  - All staging and pre-release checks must pass `bash scripts/check-data-guard.sh`.
* **Python Tooling:**
  - Dependency management and virtual environments are managed exclusively via `uv` (`uv sync`, `uv run pytest`).
