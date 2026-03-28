#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/scripts/run_uv_tool.sh" semgrep --config "$ROOT_DIR/semgrep/ai_slop_rules.yml" "$@"
