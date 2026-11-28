#!/usr/bin/env bash
# Step 7: start MOSIP's BioSDK server with the open-source mock SDK, 1 GB memory limit.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -W)"
docker rm -f biosdk-service >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name biosdk-service --network register-id_default --memory 1g \
  -v "$here/biosdk-jars:/home/mosip/additional_jars:ro" \
  --entrypoint java mosipid/biosdk-server:1.2.0.1 \
  -Xms256m -Xmx768m -Dloader.path=/home/mosip/additional_jars/ \
  -Dspring.cloud.config.enabled=false \
  -Dbiosdk_bioapi_impl=io.mosip.mock.sdk.impl.SampleSDKV2 \
  -jar /home/mosip/biosdk-services.jar
