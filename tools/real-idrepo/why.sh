#!/usr/bin/env bash
# Show the root cause of the last idrepo-real startup failure, without the long stack traces.
docker logs "${1:-idrepo-real}" 2>&1 | grep -o '"message":"[^"]*"' | grep -v "appears to have started a thread" | grep -i -E "exception|fail|error|refused|unable|cannot|started|nested" | sed 's/nested exception is/\n   -> /g' | tail -n 8
echo "STATUS: $(docker ps -a --filter name="${1:-idrepo-real}" --format '{{.Status}}')"
