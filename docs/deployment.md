# CI/CD, Deployment & Traefik Overlay

This document describes local Docker Compose, the optional Traefik overlay, and the Helm chart. Docker Compose is for local development. Staging and production are the Helm chart. The Sandbox Kit owns ingress.

---

## 1. Branching & Promotion Lifecycle

```
[feature/xxx] ---> [dev] (tag vX.Y.Z -> CI builds & pushes to GHCR)
                    │
                    ▼ (PR merge)
                  [stg] (CD deploys to Staging)
                    │
                    ▼ (PR merge)
                  [main] (CD deploys to Production)
```

1. **Development (`dev`)**:
   - Default working branch. Pushes directly to `dev` do not deploy.
   - Run tests locally with `bash scripts/check.sh`.
2. **Release to GHCR (`v*`)**:
   - Cut release: `bash scripts/release.sh vX.Y.Z`.
   - Pushing the tag triggers `.github/workflows/ci.yml`, running tests and pushing images (`vX.Y.Z`, `vX.Y`, `latest`) to GitHub Container Registry (`ghcr.io`).
3. **Staging Promotion (`stg`)**:
   - Open PR: `bash scripts/release.sh pr stg` (or `gh pr create --base stg --head dev`).
   - Merging into `stg` automatically deploys to the Staging server.
4. **Production Promotion (`main`)**:
   - Open PR: `bash scripts/release.sh pr main` (or `gh pr create --base main --head stg`).
   - Merging into `main` automatically deploys to the Production server.

---

## 2. GitHub Environments & Credentials

Configure two environments in GitHub (**Settings > Environments**): `staging` and `production`. Both execute the exact same deployment job in `.github/workflows/cd.yml`.

| Variable / Secret | Type | Description |
|---|---|---|
| `NETBIRD_KEY` or `NETBIRD_SETUP_KEY` | Secret | NetBird mesh VPN setup key for runner access |
| `SSH_PRIVATE_KEY` | Secret | SSH private key to authenticate against deployment server |
| `SERVER_HOST` | Variable | Target server IP or NetBird mesh hostname |
| `SERVER_USER` | Variable | Target server SSH user |
| `SERVER_PROJECT_DIR` | Variable | Target directory on host (e.g. `/opt/register-id`) |
| `NETBIRD_MANAGEMENT_URL` | Variable | *(Optional)* Self-hosted NetBird management URL |

---

## 3. Traefik Reverse Proxy Overlay

Docker Compose is for local development. Staging and production are the Helm chart in [`helm/register-id`](../helm/register-id). The Sandbox Kit owns ingress for those environments. [`docker-compose.traefik.yml`](../docker-compose.traefik.yml) remains an optional local overlay. It does not deploy staging or production.

### Local Development
In local `.env`:
```ini
COMPOSE_FILE=docker-compose.yml
FASTAPI_PORT=8000
```
Application maps directly to `http://localhost:8000`.

### Optional local Traefik overlay
On a local Compose stack only:
```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
APP_HOSTNAME_DOMAIN=api-stg.ait.ac.th
```
Docker Compose layers [`docker-compose.traefik.yml`](../docker-compose.traefik.yml), connects the container to the external `traefik_public` network, and registers routing and SSL with Traefik. Staging and production do not use this overlay.

---

## 4. Sandbox Kit (Helm)

The Sandbox Kit installs only Helm charts and pins every image by digest. Chart sources are in [`helm/register-id`](../helm/register-id). Docker Compose is for local development. Staging and production are this Helm chart. The Kit owns ingress.

The public host is one label under the environment domain: `register.<domain>`. CI still pushes `ghcr.io/mosip-asia/dpi-register-id` and writes `ghcr.io/mosip-asia/dpi-register-id@sha256:…` in the job summary and the `image-digest` artifact. The Kit cannot pull that package anonymously. Mirror the image to Docker Hub or another registry the Kit can pull, then set `image.registry`, `image.repository`, and `image.digest` to the mirrored digest. The workflow does not change GHCR package visibility.

`/health` is the liveness probe. `/ready` checks Redis and that configuration is loaded. It does not call IDRepo. The process logs to stdout and runs as uid 1000. MOSIP calls use an authmanager client id and secret. Keycloak admin calls use only a realm service account (`KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET`). `KEYCLOAK_PUBLIC_URL` is the browser host and `KEYCLOAK_INTERNAL_URL` is the in-cluster host.

## 5. Fail-Forward Policy & Rollback

- **Smoke Testing**: Every deployment executes `scripts/smoke-test.sh` verifying `/health`, index route, and Django checks before declaring success.
- **Persistent Baseline (`.deploy_success`)**: The deployed commit SHA is saved in `.deploy_success` only after tests pass.
- **Zero-Touch Rollback**: If deployment or smoke tests fail, the workflow immediately checks out the previous verified SHA from `.deploy_success` and redeploys it, restoring the host to a stable baseline.
