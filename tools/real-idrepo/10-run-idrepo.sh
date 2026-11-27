#!/usr/bin/env bash
# Step 10: start the real MOSIP ID Repository (identity service) next to register-id, 2 GB memory limit.
#
# MOSIP's application-default.properties outranks any extra properties file, so every line of
# config/local.properties is passed as a -D option (system properties always win).
# Secrets stay in idrepo.env and are resolved by Spring from the container environment.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -W)"
envfile="$here/idrepo.env"

overrides=()
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*) continue ;; esac
  overrides+=("-D$line")
done < "$here/config/local.properties"

docker rm -f idrepo-real >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name idrepo-real --network register-id_default --memory 2g -p 8090:8090 \
  --env-file "$envfile" \
  -v "$here/jars:/home/mosip/additional_jars:ro" -v "$here/config:/config:ro" \
  --entrypoint java mosipid/id-repository-identity-service:1.2.0.1 \
  -Xms512m -Xmx1g -Dloader.path=/home/mosip/additional_jars/ \
  -Dspring.cloud.config.enabled=false \
  -Dspring.config.name=application,id-repository \
  -Dspring.config.additional-location=file:/config/ \
  -Dspring.profiles.active=default \
  "${overrides[@]}" \
  -jar /home/mosip/id-repository-identity-service.jar
