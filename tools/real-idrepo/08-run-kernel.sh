#!/usr/bin/env bash
# Step 8: start one MOSIP kernel service (masterdata or keymanager) next to register-id.
# Usage: bash 08-run-kernel.sh masterdata|keymanager
# Settings: MOSIP config files from disk, plus every line of config/local.properties and
# config/local-kernel.properties as -D options (these always win over application-default).
set -euo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"

case "${1:-}" in
  masterdata)
    name=masterdata; image=mosipid/kernel-masterdata-service:1.2.0.1
    jar=/home/mosip/kernel-masterdata-service.jar; port=8086; mem=1536m; heap=900m
    config_names=application,kernel ;;
  keymanager)
    name=keymanager; image=mosipid/kernel-keymanager-service:1.2.0.1
    jar=/home/mosip/kernel-keymanager-service.jar; port=8088; mem=1536m; heap=900m
    config_names=application,kernel ;;
  *) echo "usage: bash 08-run-kernel.sh masterdata|keymanager" >&2; exit 2 ;;
esac

overrides=()
for f in config/local.properties config/local-kernel.properties; do
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    overrides+=("-D$line")
  done < "$f"
done
extra=()
[ -f "config/local-$name.properties" ] && while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"; case "$line" in ''|'#'*) continue ;; esac; extra+=("-D$line")
done < "config/local-$name.properties"

docker rm -f "$name" >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name "$name" --network register-id_default --memory "$mem" \
  --env-file idrepo.env \
  -v "$here/jars/kernel-auth-adapter.jar:/home/mosip/additional_jars/kernel-auth-adapter.jar:ro" \
  -v "$here/config:/config:ro" -v "$here/keystore:/keystore" \
  --entrypoint java "$image" \
  "-Xms256m" "-Xmx$heap" -Dloader.path=/home/mosip/additional_jars/ \
  -Dspring.cloud.config.enabled=false \
  "-Dspring.config.name=$config_names" \
  -Dspring.config.additional-location=file:/config/ \
  -Dspring.profiles.active=default \
  "-Dserver.port=$port" \
  "${overrides[@]}" "${extra[@]}" \
  -jar "$jar"
