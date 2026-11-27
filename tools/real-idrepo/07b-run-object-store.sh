#!/usr/bin/env bash
# Step 7b: an S3-compatible object store where the ID Repository keeps biometric documents (CBEFF).
# MOSIP uses MinIO, but MinIO no longer publishes images on Docker Hub, so this runs SeaweedFS's
# S3 gateway (chrislusf/seaweedfs), which speaks the same S3 API. Needed only for enrolments with a face.
# The access/secret key come from idrepo.env (IDREPO_S3_ACCESS_KEY / IDREPO_S3_SECRET_KEY); they are written
# to objectstore-s3.json (local only, contains the secret) which SeaweedFS reads as its S3 identities.
set -euo pipefail
cd "$(dirname "$0")"
here="$(pwd -W)"
access=$(grep '^IDREPO_S3_ACCESS_KEY=' idrepo.env | cut -d= -f2-)
secret=$(grep '^IDREPO_S3_SECRET_KEY=' idrepo.env | cut -d= -f2-)
cat > objectstore-s3.json <<EOF
{"identities": [{"name": "idrepo",
  "credentials": [{"accessKey": "$access", "secretKey": "$secret"}],
  "actions": ["Admin", "Read", "List", "Tagging", "Write"]}]}
EOF
docker rm -f objectstore >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name objectstore --network register-id_default --memory 512m \
  -v mosip-local-objectstore:/data -v "$here/objectstore-s3.json:/etc/seaweedfs/s3.json:ro" \
  chrislusf/seaweedfs:3.80 server -dir=/data -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json
