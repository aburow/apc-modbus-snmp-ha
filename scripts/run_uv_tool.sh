#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/.tools/uv-cache"

export UV_CACHE_DIR="$ROOT_DIR/.tools/uv-cache"
export UV_PROJECT_ENVIRONMENT="$ROOT_DIR/.tools/uv-lint"
exec "$ROOT_DIR/.tools/bin/uv" run "$@"
