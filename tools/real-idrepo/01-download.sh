#!/usr/bin/env bash
# Step 1: download everything the real ID Repository and its neighbours need, from official MOSIP sources.
#   - Docker images (Docker Hub, mosipid/*, 1.2.0.1)
#   - Jars (Maven Central, io.mosip.*), which the images normally fetch from MOSIP "artifactory"
#   - Config (github.com/mosip/mosip-config, tag v1.2.0.1) and the files services download at startup
#   - Database scripts: id-repository (release-1.2.0.1), admin-services (release-1.2.0.1), keymanager (v1.2.0.1)
#   - Identity schema seed (github.com/mosip/mosip-data, tag v1.2.0.1)
set -euo pipefail
cd "$(dirname "$0")"
MAVEN=https://repo1.maven.org/maven2/io/mosip
RAW=https://raw.githubusercontent.com/mosip
CONFIG="$RAW/mosip-config/v1.2.0.1"

tree() {  # list files of a GitHub repo at a ref, filtered by a grep -E pattern
  curl -fsS "https://api.github.com/repos/mosip/$1/git/trees/$2?recursive=1" \
    | grep -o '"path": *"[^"]*"' | sed 's/"path": *"//; s/"$//' | grep -E "$3"
}

echo "== Docker images"
for image in id-repository-identity-service biosdk-server kernel-masterdata-service kernel-keymanager-service; do
  docker pull "mosipid/$image:1.2.0.1"
done

echo "== Jars"
mkdir -p jars biosdk-jars
curl -fsS -o jars/kernel-auth-adapter.jar          "$MAVEN/kernel/kernel-auth-adapter/1.2.0.1/kernel-auth-adapter-1.2.0.1.jar"
curl -fsS -o jars/kernel-ref-idobjectvalidator.jar "$MAVEN/kernel/kernel-ref-idobjectvalidator/1.2.0.1/kernel-ref-idobjectvalidator-1.2.0.1.jar"
curl -fsS -o jars/biosdk-client.jar                "$MAVEN/biosdk/biosdk-client/1.2.0.1/biosdk-client-1.2.0.1-jar-with-dependencies.jar"
curl -fsS -o biosdk-jars/mock-sdk.jar              "$MAVEN/mock/sdk/mock-sdk/1.2.0.1/mock-sdk-1.2.0.1-jar-with-dependencies.jar"

echo "== Config properties"
mkdir -p config/id-repository/default/1.1.2
for f in application-default.properties id-repository-default.properties kernel-default.properties; do
  curl -fsS -o "config/$f" "$CONFIG/$f"
done
# Two values are encrypted ({cipher}); only a MOSIP config server can decrypt them. Replace locally.
sed -i 's/^mosip.kernel.pdf_owner_password=.*/mosip.kernel.pdf_owner_password=local-test-only/' config/application-default.properties
sed -i 's#^mosip.service.end-points=.*#mosip.service.end-points=/**/actuator/**,/**/swagger-ui/**,/**/v3/api-docs/**#' config/kernel-default.properties

echo "== Files the services download at startup (.json .xsd .mvel .xml)"
tree mosip-config v1.2.0.1 '^[^/]+\.(json|xsd|mvel|xml)$' | while read -r f; do
  curl -fsS -o "config/$f" "$CONFIG/$f"
  cp "config/$f" "config/id-repository/default/1.1.2/$f"
done

echo "== Database scripts"
fetch_db() {  # repo ref path-regex
  tree "$1" "$2" "$3" | while read -r p; do mkdir -p "$(dirname "$p")"; curl -fsS -o "$p" "$RAW/$1/$2/$p"; done
}
fetch_db id-repository release-1.2.0.1 '^db_scripts/mosip_id(repo|map)/.*\.(sql|sh|properties)$'
fetch_db admin-services release-1.2.0.1 '^db_scripts/mosip_master/(ddl/.*|[^/]*)\.(sql|sh|properties)$'
fetch_db keymanager v1.2.0.1 '^db_scripts/mosip_keymgr/.*\.(sql|sh|properties|csv)$'

echo "== Identity schema seed"
mkdir -p seed
curl -fsS -o seed/identity_schema.xlsx "$RAW/mosip-data/v1.2.0.1/mosip_master/xlsx/identity_schema.xlsx"

echo "Done."
