# Deployment manual

Staging and production run the Helm chart in [`helm/register-id`](../helm/register-id). The Sandbox Kit installs that chart and owns ingress. Docker Compose is local development only.

The public host is one label under the environment domain: `register.<domain>`. `register.id.<domain>` is two labels under that domain, and the Kit does not route it.

## What Register ID needs from the environment

The process does not ship with MOSIP, Keycloak, or Redis. Those have to exist before the pod can enrol anyone.

### MOSIP services

| Service | What this process calls | Kit value |
|---|---|---|
| IDRepo | `POST /idrepository/v1/identity/` and the read, patch, and delete routes under `/idrepository/v1/identity` | `mosip.idrepoBaseUrl`, for example `http://id-repository` |
| Kernel idgenerator | `GET /v1/idgenerator/uin` | `mosip.idgeneratorBaseUrl`, for example `http://idgenerator.kernel` |
| Keycloak | Token, admin, and browser login on realm `mosip` | `keycloak.url`, `keycloak.internalUrl`, `keycloak.realm` |

`keycloak.url` is the browser host, `https://iam.<domain>/auth`. `keycloak.internalUrl` is the in-cluster host, for example `http://keycloak.keycloak/auth`. Set both. They should differ. The chart writes `keycloak.url` into `KEYCLOAK_URL` and `KEYCLOAK_PUBLIC_URL`.

On a Kit deploy set `mosip.inprocessFallback` to `false`. That flag is the local mock. With it on, a failed MOSIP call can be answered by the in-process mock.

### Keycloak clients and roles

This chart does not create clients, roles, or secrets. The Kit creates them in the application realm (`keycloak.realm`, normally `mosip`).

**IDRepo client.** Confidential client, `client_credentials` only. `keycloak.idrepoClientId` is the client id. `IDREPO_CLIENT_SECRET` is the matching key in `existingSecret`. The process posts that pair to `{KEYCLOAK_INTERNAL_URL}/realms/{realm}/protocol/openid-connect/token` and sends the access token to IDRepo as `Cookie: Authorization=<token>`. Give the service account the MOSIP roles `REGISTRATION_PROCESSOR` and `ID_REPOSITORY`. IDRepo rejects a token that does not carry them.

**Admin client.** Confidential client, `client_credentials` only. `keycloak.adminClientId` is the client id. `KEYCLOAK_ADMIN_CLIENT_SECRET` is the matching key in `existingSecret`. Assign only the realm-management roles `manage-users` and `view-users`. The process uses this account to create the citizen user after enrolment. It does not use the master realm or a password grant.

**Login client.** This is the browser client, `keycloak.oidcClientId`. The flow is authorization code with PKCE (S256). The valid redirect URI is `keycloak.redirectUri`, which must be `https://register.<domain>/api/login/callback` and must match the client in Keycloak exactly. Leave `KEYCLOAK_OIDC_CLIENT_SECRET` empty for a public PKCE client. A non-empty secret makes the token exchange send that secret.

Desk officers do not use a separate Keycloak client. The desk reads `REGISTER_ID_OPERATOR_TOKEN`. `operatorRole` is `reader` or `custodian`. An empty token denies those routes.

### Redis

Redis holds drafts, login state, the enrolment rate limit, and the audit stream. `REDIS_URL` is a key in `existingSecret`. `/ready` pings that URL. It does not call IDRepo or Keycloak.

`APPLICATION_STORE_KEY` is the Fernet key for drafts in Redis. Generate one per environment:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### SMTP

Mail is optional. Enrolment still succeeds when mail is skipped or when delivery fails. To skip mail, set `email.provider`, `email.from`, `smtp.host`, and `smtp.user` to `off`. The chart renders `off` as an empty string, and an empty provider and host skip sending. To send mail, set a real host (or `email.provider` to `gmail`), a sender, `smtp.port` (usually `587`), `smtp.starttls`, and the password keys in the Secret.

## Configuration reference

Helm has no defaults for application settings. An empty value fails `helm template`. The **Default** column is what the process does when the variable is absent outside this chart. `fixed` means the chart writes that value and there is no Helm key.

`off` on `email.provider`, `email.from`, `smtp.host`, and `smtp.user` is required as a chart value and becomes an empty environment variable.

| Name | What it is | Required? | Secret? | Example | Default |
|---|---|---|---|---|---|
| `PROJECT_NAME` / `projectName` | Process name | Yes | No | `register-id` | app: `register-id` |
| `ENVIRONMENT` / `environment` | `dev`, `stg`, or `prod` | Yes | No | `prod` | app: `dev` |
| `BUILD_VERSION` / `buildVersion` | Shown on `/health` | Yes | No | `0.1.0` | app: `0.1.0-dev` |
| `LOG_LEVEL` / `logLevel` | Python log level | Yes | No | `INFO` | app: `DEBUG` when `ENVIRONMENT` is `dev`, otherwise `INFO` |
| `FASTAPI_HOST` | Bind address inside the pod | Yes | No | `0.0.0.0` | fixed `0.0.0.0` |
| `FASTAPI_PORT` | Port inside the pod | Yes | No | `8000` | fixed `8000` |
| `FASTAPI_WORKERS` / `fastapiWorkers` | Uvicorn workers | Yes | No | `1` | app: `1` |
| `DEBUG` / `debug` | Django debug | Yes | No | `false` | app: on when `ENVIRONMENT` is `dev` |
| `ALLOWED_HOSTS` / `allowedHosts` | Django allowed hosts | Yes | No | `register.sandbox.example.net` | app: `*` in dev, otherwise localhost |
| `HOME` | Writable home on the read-only root | Yes | No | `/tmp` | fixed `/tmp` |
| `MOSIP_IDREPO_BASE_URL` / `mosip.idrepoBaseUrl` | IDRepo base URL | Yes | No | `http://id-repository` | app: `http://localhost:8081` |
| `MOSIP_IDGENERATOR_BASE_URL` / `mosip.idgeneratorBaseUrl` | Kernel idgenerator base URL | Yes | No | `http://idgenerator.kernel` | app: that host when fallback is off |
| `IDREPO_INPROCESS_FALLBACK` / `mosip.inprocessFallback` | Use the in-process mock after a remote failure | Yes | No | `false` | app: off when unset |
| `ENROLL_SUCCESS_LIMIT` / `mosip.enrollSuccessLimit` | Successful enrolments per ticket per hour, clamped to 1–10000 | Yes | No | `100` | app: `30` |
| `MOSIP_HTTP_TIMEOUT` / `mosip.httpTimeout` | HTTP timeout in seconds | Yes | No | `10` | app: `10` |
| `MOSIP_HTTP_RETRIES` / `mosip.httpRetries` | Extra attempts for idempotent calls | Yes | No | `2` | app: `2` |
| `MOSIP_HTTP_BACKOFF_SECONDS` / `mosip.httpBackoffSeconds` | Backoff between attempts | Yes | No | `0.5` | app: `0.2` |
| `KEYCLOAK_URL` / `keycloak.url` | Keycloak base URL written beside the public URL | Yes | No | `https://iam.sandbox.example.net/auth` | app: `http://localhost:8080/auth` |
| `KEYCLOAK_PUBLIC_URL` / `keycloak.url` | Browser Keycloak host | Yes | No | `https://iam.sandbox.example.net/auth` | none on the Kit path |
| `KEYCLOAK_INTERNAL_URL` / `keycloak.internalUrl` | In-cluster Keycloak host for tokens and admin calls | Yes | No | `http://keycloak.keycloak/auth` | none on the Kit path |
| `KEYCLOAK_REALM` / `keycloak.realm` | Application realm | Yes | No | `mosip` | app: `mosip` |
| `IDREPO_CLIENT_ID` / `keycloak.idrepoClientId` | IDRepo service-account client id | Yes | No | `idrepo-client` | none |
| `IDREPO_CLIENT_SECRET` | IDRepo service-account secret | Key must exist | Yes | from the Kit | none |
| `KEYCLOAK_ADMIN_CLIENT_ID` / `keycloak.adminClientId` | Admin service-account client id | Yes | No | `register-id-admin` | none |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | Admin service-account secret | Key must exist | Yes | from the Kit | none |
| `KEYCLOAK_OIDC_CLIENT_ID` / `keycloak.oidcClientId` | Browser login client id | Yes | No | `register-id` | none |
| `KEYCLOAK_OIDC_CLIENT_SECRET` | Login client secret. Empty keeps PKCE public | Key must exist | Yes | empty | empty means public client |
| `KEYCLOAK_OIDC_REDIRECT_URI` / `keycloak.redirectUri` | Browser callback | Yes | No | `https://register.sandbox.example.net/api/login/callback` | none |
| `REGISTER_ID_COOKIE_SECURE` / `cookieSecure` | `Secure` flag on the session cookie | Yes | No | `true` | app: off when `ENVIRONMENT` is `dev` |
| `REGISTER_ID_OPERATOR_TOKEN` | Desk bearer token. Empty denies the desk | Key must exist | Yes | long random string | empty denies the desk |
| `REGISTER_ID_OPERATOR_ROLE` / `operatorRole` | `reader` or `custodian` | Yes | No | `reader` | unset role is rejected |
| `REDIS_URL` | Redis URL for drafts, login, limits, and audit | Key must exist | Yes | `redis://:password@redis:6379/0` | `/ready` fails when missing and fallback is off |
| `APPLICATION_STORE_KEY` | Fernet key for drafts in Redis | Key must exist | Yes | output of the command above | none |
| `DJANGO_SECRET_KEY` | Django secret | Key must exist | Yes | long random string | app has an insecure built-in only when unset |
| `EMAIL_PROVIDER` / `email.provider` | `gmail` shortcut, or `off` to skip | Yes | No | `off` | empty skips mail |
| `EMAIL_FROM` / `email.from` | From address, or `off` | Yes | No | `registrar@example.net` | falls back to `SMTP_USER` |
| `EMAIL_PASSWORD` | Mail password. `SMTP_PASSWORD` is the alternate | Key must exist | Yes | app password | empty skips when no SMTP password either |
| `SMTP_HOST` / `smtp.host` | SMTP server, or `off` to skip | Yes | No | `smtp.example.net` | empty skips mail |
| `SMTP_PORT` / `smtp.port` | SMTP port | Yes | No | `587` | app: `587` when a host is set |
| `SMTP_USER` / `smtp.user` | SMTP username, or `off` | Yes | No | `registrar@example.net` | optional |
| `SMTP_PASSWORD` | SMTP password | Key must exist | Yes | from the Kit | optional |
| `SMTP_STARTTLS` / `smtp.starttls` | STARTTLS. `false`, `0`, `no`, or `off` disables it | Yes | No | `true` | app: on when unset |
| `image.registry` | Registry the Kit can pull | Yes | No | `docker.io` | chart file: `ghcr.io` |
| `image.repository` | Image repository | Yes | No | `mosip-asia/dpi-register-id` | chart file: `mosip-asia/dpi-register-id` |
| `image.digest` | Mirrored image digest. The tag is not used | Yes | No | `sha256:` plus 64 hex characters | none |
| `image.tag` | Unused while `image.digest` is set | No | No | `0.1.0` | chart file: `0.1.0` |
| `publicHost.hostname` | Left label of the public host | No | No | `register` | `register` |
| `publicHost.domain` | Environment domain | Yes for the host annotation | No | `sandbox.example.net` | none |
| `publicHost.host` | Full host. Overrides hostname and domain | No | No | `register.sandbox.example.net` | none |
| `existingSecret` | Secret name that holds the keys below | Yes | Name only | `register-id` | none |
| `COMPOSE_FILE` | Local Compose file list | Local only | No | `docker-compose.yml:docker-compose.mosip.yml` | local |
| `APP_HOSTNAME_DOMAIN` | Local Traefik host | Local only | No | `register.ait.ac.th` | local |
| `SOME_API_KEY` | Passed into Compose. The process does not read it | Local only | No | unused | local |
| `LOG_DIR`, `LOG_NAME`, `LOG_ROTATE_NAME` | File logs. The pod logs to stdout | Local only | No | `logs/` | local |
| `REDIS_PORT`, `REDIS_PASSWORD` | Host Redis for Compose. The pod uses `REDIS_URL` | Local only | `REDIS_PASSWORD` is a secret | `6379` | local |
| `MOSIP_IDREPO_PORT` | Host port of the local mock IDRepo | Local only | No | `8081` | local |
| `KEYCLOAK_PORT` | Host port of local Keycloak | Local only | No | `8080` | local |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local mock IDRepo database. The pod does not use them | Local only | `POSTGRES_PASSWORD` is a secret | `localhost` | local |

`existingSecret` must contain every secret key in the table, including the ones whose value is empty: `REDIS_URL`, `APPLICATION_STORE_KEY`, `DJANGO_SECRET_KEY`, `IDREPO_CLIENT_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`, `KEYCLOAK_OIDC_CLIENT_SECRET`, `REGISTER_ID_OPERATOR_TOKEN`, `EMAIL_PASSWORD`, `SMTP_PASSWORD`. A missing key keeps the pod from starting.

## Deploy with Helm (Kit)

CI publishes `ghcr.io/mosip-asia/dpi-register-id` and prints `ghcr.io/mosip-asia/dpi-register-id@sha256:…` in the job summary. The Kit does not pull that package anonymously. Mirror the image to a registry the Kit can pull, then set `image.registry`, `image.repository`, and `image.digest` to that copy.

```bash
helm install register-id ./helm/register-id \
  --set image.registry=<mirror registry> \
  --set image.repository=<mirror repository> \
  --set image.digest=sha256:<mirrored digest> \
  --set publicHost.domain=sandbox.example.net \
  --set projectName=register-id \
  --set environment=prod \
  --set buildVersion=0.1.0 \
  --set logLevel=INFO \
  --set debug=false \
  --set allowedHosts=register.sandbox.example.net \
  --set fastapiWorkers=1 \
  --set cookieSecure=true \
  --set operatorRole=reader \
  --set mosip.idrepoBaseUrl=http://id-repository \
  --set mosip.idgeneratorBaseUrl=http://idgenerator.kernel \
  --set mosip.inprocessFallback=false \
  --set mosip.enrollSuccessLimit=100 \
  --set mosip.httpTimeout=10 \
  --set mosip.httpRetries=2 \
  --set mosip.httpBackoffSeconds=0.5 \
  --set keycloak.url=https://iam.sandbox.example.net/auth \
  --set keycloak.internalUrl=http://keycloak.keycloak/auth \
  --set keycloak.realm=mosip \
  --set keycloak.idrepoClientId=idrepo-client \
  --set keycloak.adminClientId=register-id-admin \
  --set keycloak.oidcClientId=register-id \
  --set keycloak.redirectUri=https://register.sandbox.example.net/api/login/callback \
  --set email.provider=off \
  --set email.from=off \
  --set smtp.host=off \
  --set smtp.port=587 \
  --set smtp.user=off \
  --set smtp.starttls=true \
  --set existingSecret=register-id
```

The chart does not render an Ingress. It sets the Service annotation `register-id.mosip.io/host` to `register.<domain>`. The Kit routes that host. The container runs as uid 1000, with a read-only root filesystem, and logs to stdout. Liveness is `GET /health`. Readiness is `GET /ready`.

Create the Secret before install. Keys only. Values stay in the Kit.

```text
REDIS_URL
APPLICATION_STORE_KEY
DJANGO_SECRET_KEY
IDREPO_CLIENT_SECRET
KEYCLOAK_ADMIN_CLIENT_SECRET
KEYCLOAK_OIDC_CLIENT_SECRET
REGISTER_ID_OPERATOR_TOKEN
EMAIL_PASSWORD
SMTP_PASSWORD
```

## Local development with Docker Compose

**Local only.** This stack is not staging or production. It runs Redis, a mock IDRepo, PostgreSQL for that mock, and a local Keycloak. The mock answers both IDRepo and the UIN generator.

```bash
cp .env.example .env
docker compose up -d --build
```

`.env.example` sets `COMPOSE_FILE=docker-compose.yml:docker-compose.mosip.yml` and `IDREPO_INPROCESS_FALLBACK=true`.

| Local URL | What it is |
|---|---|
| `http://localhost:8000` | Register ID |
| `http://localhost:8081` | Mock IDRepo and UIN generator |
| `http://localhost:8080` | Local Keycloak |

An optional Traefik overlay is also local only. See the legacy note in [`deployment.md`](deployment.md). Do not point a Kit environment at these hostnames.

## Check it after deploy

1. Liveness. `GET /health` returns `{"status":"ok", ...}` with the environment and build version.
2. Readiness. `GET /ready` returns `{"status":"ok","checks":{"redis":"ok","config":"ok"}}`. `config` is ok when Redis, IDRepo, the IDRepo client, both Keycloak URLs, and the admin client are set. This check does not call IDRepo. `503` with `redis: down` or `config: incomplete` means the pod is up and the dependency is not.
3. Enrol one test person at `https://register.<domain>`. Finish the flow and keep the registration number (UIN) the page shows. The number comes from the kernel idgenerator. The portal does not accept a UIN you type in.
4. Read that person back. With `Authorization: Bearer <REGISTER_ID_OPERATOR_TOKEN>`, `GET /api/citizens/<uin>` returns the name and email and omits the face image. The same UIN should be the one IDRepo stored.

A mail failure does not fail this check. Enrolment can succeed with mail left off.

## Common problems

**401 from IDRepo, or enrol returns 502.** The IDRepo client id or secret is wrong, or the service account is missing `REGISTRATION_PROCESSOR` or `ID_REPOSITORY`. A Keycloak token rejection is logged as `Keycloak rejected the IDRepo client (401)`. An IDRepo rejection of a token Keycloak already issued is logged as `IDRepo remote enroll failed` and the citizen sees a generic failure with a reference. Compare `keycloak.idrepoClientId` and `IDREPO_CLIENT_SECRET` with the client in the `mosip` realm, then confirm those two roles on the service account.

**503, MOSIP not reachable.** The pod cannot open IDRepo, the idgenerator, or `keycloak.internalUrl`. `/ready` can still be ok, because it never calls those hosts. Check `mosip.idrepoBaseUrl`, `mosip.idgeneratorBaseUrl`, and `keycloak.internalUrl` from inside the cluster. A generator that returns no UIN is logged as `MOSIP idgenerator did not return a UIN` and enrol returns 503. Leave `mosip.inprocessFallback` at `false` on a Kit deploy so a failure stays a failure.

**Keycloak redirect errors.** The browser must use `keycloak.url` (`https://iam.<domain>/auth`). Token and admin calls must use `keycloak.internalUrl`. `keycloak.redirectUri` must be exactly the redirect URI on the login client, `https://register.<domain>/api/login/callback`. A mismatch fails the code exchange after the person returns from Keycloak. `cookieSecure` should be `true` on HTTPS. `allowedHosts` should include `register.<domain>`.
