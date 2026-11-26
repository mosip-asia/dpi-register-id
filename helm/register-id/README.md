# register-id

Helm chart for the Sandbox Kit. The Kit installs this chart and owns Ingress. Docker Compose is for local development. Staging and production are this chart.

The field-by-field list, the Keycloak clients, and the post-deploy checks are in the [deployment manual](../../docs/deployment-manual.md).

```bash
helm install register-id ./helm/register-id \
  --set image.registry=<mirror registry> \
  --set image.repository=<mirror repository> \
  --set image.digest=sha256:<mirrored digest> \
  --set publicHost.domain=sandbox.example.net \
  --set mosip.idrepoBaseUrl=http://id-repository \
  --set keycloak.url=https://iam.sandbox.example.net/auth \
  --set keycloak.internalUrl=http://keycloak.keycloak/auth \
  --set keycloak.adminClientId=register-id \
  --set keycloak.idrepoClientId=idrepo-client \
  --set keycloak.realm=mosip \
  --set keycloak.oidcClientId=register-id \
  --set keycloak.redirectUri=https://register.sandbox.example.net/api/login/callback \
  --set projectName=register-id \
  --set environment=dev \
  --set buildVersion=0.1.0 \
  --set logLevel=INFO \
  --set debug=false \
  --set allowedHosts=register.sandbox.example.net \
  --set fastapiWorkers=1 \
  --set cookieSecure=true \
  --set operatorRole=reader \
  --set mosip.idgeneratorBaseUrl=http://idgenerator.kernel \
  --set mosip.inprocessFallback=false \
  --set mosip.enrollSuccessLimit=100 \
  --set mosip.httpTimeout=10 \
  --set mosip.httpRetries=2 \
  --set mosip.httpBackoffSeconds=0.5 \
  --set email.provider=off \
  --set email.from=off \
  --set smtp.host=off \
  --set smtp.port=587 \
  --set smtp.user=off \
  --set smtp.starttls=true \
  --set existingSecret=register-id
```

Every application setting from `.env` is required. `helm template` fails when one is empty. `off` for `email.provider`, `email.from`, `smtp.host`, and `smtp.user` is rendered as an empty string so mail stays off.

Required values: `projectName`, `environment`, `buildVersion`, `logLevel`, `debug`, `allowedHosts`, `fastapiWorkers`, `cookieSecure`, `operatorRole`, `mosip.idrepoBaseUrl`, `mosip.idgeneratorBaseUrl`, `mosip.inprocessFallback`, `mosip.enrollSuccessLimit`, `mosip.httpTimeout`, `mosip.httpRetries`, `mosip.httpBackoffSeconds`, `keycloak.url`, `keycloak.internalUrl`, `keycloak.realm`, `keycloak.idrepoClientId`, `keycloak.adminClientId`, `keycloak.oidcClientId`, `keycloak.redirectUri`, `email.provider`, `email.from`, `smtp.host`, `smtp.port`, `smtp.user`, `smtp.starttls`, `existingSecret`, `image.digest`.

`publicHost.domain` is the environment domain. The chart records `register.<domain>` on the Service annotation `register-id.mosip.io/host` and does not render an Ingress. A host such as `register.id.<domain>` is two labels below that domain, which the Kit does not route.

`extraEnv` and `extraEnvVars` are both applied. `securityContext` is a pod securityContext merged onto `podSecurityContext` (Kit keys win on duplicates). `containerSecurityContext` is unchanged.

`existingSecret` must define `REDIS_URL`, `APPLICATION_STORE_KEY`, `DJANGO_SECRET_KEY`, `IDREPO_CLIENT_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`, `KEYCLOAK_OIDC_CLIENT_SECRET`, `REGISTER_ID_OPERATOR_TOKEN`, `EMAIL_PASSWORD`, and `SMTP_PASSWORD`. Each name is a `secretKeyRef`, so a missing key keeps the pod from starting. The value may be empty when that feature is off. The chart does not embed those values. `keycloak.idrepoClientId` is the IDRepo client id. The matching secret stays in that Secret.

The container runs as uid/gid 1000, reads configuration from the environment, logs to stdout, and serves `/health` (liveness) and `/ready` (Redis and loaded configuration). `/ready` does not call IDRepo.

This chart does not generate `KEYCLOAK_ADMIN_CLIENT_SECRET`. The Kit supplies it in `existingSecret`. The confidential client uses `client_credentials` and only the realm-management roles `manage-users` and `view-users`. Those roles are not created by this repository. Set `keycloak.internalUrl` to the in-cluster Keycloak service and `keycloak.url` to `https://iam.<domain>/auth`.

The Kit deploy sets `image.digest` to the mirrored digest and does not pull GHCR anonymously. CI still pushes `ghcr.io/mosip-asia/dpi-register-id`. Copy that image to Docker Hub or another registry the Kit can pull, then set `image.registry`, `image.repository`, and `image.digest` to the mirrored copy.
