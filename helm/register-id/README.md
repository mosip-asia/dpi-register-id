# register-id

Helm chart for the Sandbox Kit. The Kit installs this chart and owns Ingress. Docker Compose is for local development. Staging and production are this chart.

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
  --set keycloak.redirectUri=https://register.sandbox.example.net/api/login/callback \
  --set existingSecret=register-id
```

`publicHost.domain` is the environment domain. The chart records `register.<domain>` on the Service annotation `register-id.mosip.io/host` and does not render an Ingress. A host such as `register.id.<domain>` is two labels below that domain, which the Kit does not route.

`extraEnv` and `extraEnvVars` are both applied. `securityContext` is a pod securityContext merged onto `podSecurityContext` (Kit keys win on duplicates). `containerSecurityContext` is unchanged.

`existingSecret` must define `IDREPO_CLIENT_SECRET`, `KEYCLOAK_ADMIN_CLIENT_SECRET`, `REDIS_URL`, and the other secret keys listed in `values.yaml`. The chart does not embed those values. `keycloak.idrepoClientId` is the IDRepo client id. The matching secret stays in that Secret.

The container runs as uid/gid 1000, reads configuration from the environment, logs to stdout, and serves `/health` (liveness) and `/ready` (Redis and loaded configuration). `/ready` does not call IDRepo.

This chart does not generate `KEYCLOAK_ADMIN_CLIENT_SECRET`. The Kit supplies it in `existingSecret`. The confidential client uses `client_credentials` and only the realm-management roles `manage-users` and `view-users`. Those roles are not created by this repository. Set `keycloak.internalUrl` to the in-cluster Keycloak service and `keycloak.url` to `https://iam.<domain>/auth`.

The Kit deploy sets `image.digest` to the mirrored digest and does not pull GHCR anonymously. CI still pushes `ghcr.io/mosip-asia/dpi-register-id`. Copy that image to Docker Hub or another registry the Kit can pull, then set `image.registry`, `image.repository`, and `image.digest` to the mirrored copy. An empty `image.digest` renders `image.registry/image.repository:image.tag` (`ghcr.io/mosip-asia/dpi-register-id:0.1.0` with the chart defaults) for local renders only.
