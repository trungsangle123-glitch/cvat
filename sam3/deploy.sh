#!/usr/bin/env bash
# Deploy the SAM 3 serverless function to the local Nuclio dashboard.
#
# Run this from WSL/Linux (nuctl's "local" platform is not supported on the
# Windows binary). Example:
#   NUCTL=~/bin/nuctl-1.16.3 bash sam3/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUCTL="${NUCTL:-nuctl}"

"$NUCTL" deploy \
    --project-name cvat \
    --path "$SCRIPT_DIR" \
    --file "$SCRIPT_DIR/function.yaml" \
    --platform local \
    --env CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk \
    --env CVAT_FUNCTIONS_REDIS_PORT=6666 \
    --platform-config '{"attributes": {"network": "cvat_cvat"}}'
