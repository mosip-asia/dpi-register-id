# CI/CD notes and legacy host deploy

Install and configure Register ID from the [deployment manual](deployment-manual.md). That is the Sandbox Kit path: Helm, MOSIP, Keycloak, and Redis. This file keeps the release steps, the local Traefik overlay, and the old SSH/NetBird host deploy.

**Do not follow sections 2 or 5 for a Kit environment.** Those sections are the legacy path that SSHed to a server over NetBird and rolled the host back with `.deploy_success`. The Kit installs [`helm/register-id`](../helm/register-id) and owns ingress.

---

## 1. Branching & Promotion Lifecycle

```
[feature/xxx] ---> [dev] (tag vX.Y.Z -> CI builds & pushes to GHCR)
                    │
                    ▼ (PR merge, legacy host deploy)
                  [stg]
                    │
                    ▼ (PR merge, legacy host deploy)
                  [main]
```

1. **Development (`dev`)**:
   - Default working branch. Pushes directly to `dev` do not deploy.
   - Run tests locally with `bash scripts/check.sh`.
2. **Release to GHCR (`v*`)**:
   - Cut release: `bash scripts/release.sh vX.Y.Z`.
   - Pushing the tag triggers `.github/workflows/ci.yml`, running tests and pushing images (`vX.Y.Z`, `vX.Y`, `latest`) to GitHub Container Registry (`ghcr.io`).
3. **Staging Promotion (`stg`)** — legacy host deploy:
   - Open PR: `bash scripts/release.sh pr stg` (or `gh pr create --base stg --head dev`).
   - Merging into `stg` runs the legacy workflow, which SSHes to a server. A Kit environment does not use that path. Install the Helm chart from the [deployment manual](deployment-manual.md).
4. **Production Promotion (`main`)** — legacy host deploy:
   - Open PR: `bash scripts/release.sh pr main` (or `gh pr create --base main --head stg`).
   - Merging into `main` runs the same legacy workflow. A Kit environment does not use that path.

---

## 2. GitHub Environments & Credentials (legacy)

**Legacy.** This is the SSH/NetBird host deploy. The Sandbox Kit does not use these secrets. Configure the chart with the [deployment manual](deployment-manual.md).

The old workflow expected two GitHub environments, `staging` and `production`, and ran `.github/workflows/cd.yml` for both.

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

Follow the [deployment manual](deployment-manual.md) for values, secrets, and checks. The short version: the Sandbox Kit installs only Helm charts and pins every image by digest. Chart sources are in [`helm/register-id`](../helm/register-id). Docker Compose is for local development. The Kit owns ingress.

The public host is one label under the environment domain: `register.<domain>`. CI still pushes `ghcr.io/mosip-asia/dpi-register-id` and writes `ghcr.io/mosip-asia/dpi-register-id@sha256:…` in the job summary and the `image-digest` artifact. The Kit cannot pull that package anonymously. Mirror the image to Docker Hub or another registry the Kit can pull, then set `image.registry`, `image.repository`, and `image.digest` to the mirrored digest. The workflow does not change GHCR package visibility.

`/health` is the liveness probe. `/ready` checks Redis and that configuration is loaded. It does not call IDRepo. The process logs to stdout and runs as uid 1000. IDRepo calls use a Keycloak `client_credentials` token (`IDREPO_CLIENT_ID` / `IDREPO_CLIENT_SECRET`) sent as `Cookie: Authorization`. Keycloak admin calls use only a realm service account (`KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET`). `KEYCLOAK_PUBLIC_URL` is the browser host and `KEYCLOAK_INTERNAL_URL` is the in-cluster host.

## 5. Fail-Forward Policy & Rollback (legacy)

**Legacy.** This rollback applies to the SSH host deploy, not to a Kit install. The Kit rolls a release back by installing the previous image digest.

- **Smoke Testing**: The legacy host workflow runs `scripts/smoke-test.sh`, which checks `/health`, the index route, and Django before declaring success.
- **Persistent Baseline (`.deploy_success`)**: The deployed commit SHA is saved in `.deploy_success` only after tests pass.
- **Zero-Touch Rollback**: If deployment or smoke tests fail, the workflow immediately checks out the previous verified SHA from `.deploy_success` and redeploys it, restoring the host to a stable baseline.
