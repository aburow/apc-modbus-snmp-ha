#!/usr/bin/env bash
set -euo pipefail

CODEQL_BIN="${CODEQL_BIN:-}"
CODEQL_HOME="${CODEQL_HOME:-$(pwd)/.tools/codeql-home}"
CODEQL_QUERIES="${CODEQL_QUERIES:-codeql/python-queries:codeql-suites/python-security-and-quality.qls}"

if [ -z "$CODEQL_BIN" ]; then
  if command -v codeql >/dev/null 2>&1; then
    CODEQL_BIN="$(command -v codeql)"
  elif [ -x ".tools/codeql/codeql/codeql" ]; then
    CODEQL_BIN="$(pwd)/.tools/codeql/codeql/codeql"
  fi
fi

if [ -z "$CODEQL_BIN" ]; then
  echo "CodeQL is not installed. Install it or unpack it into .tools/codeql/codeql/"
  exit 1
fi

mkdir -p "$CODEQL_HOME/home" "$CODEQL_HOME/packages"
export HOME="$CODEQL_HOME/home"
export CODEQL_PACKAGES="$CODEQL_HOME/packages"

if [ -d .git ]; then
  TMP_SOURCE_ROOT="$(mktemp -d /tmp/apc-modbus-ha-codeql-src.XXXXXX)"
  trap 'rm -rf "$TMP_SOURCE_ROOT"' EXIT
  for path in custom_components tests; do
    if [ -e "$path" ]; then
      cp -R "$path" "$TMP_SOURCE_ROOT"/
    fi
  done
  rm -rf .codeql-db codeql-results.sarif
  "$CODEQL_BIN" pack download codeql/python-queries
  "$CODEQL_BIN" database create .codeql-db --source-root "$TMP_SOURCE_ROOT" --language=python --overwrite
  "$CODEQL_BIN" database analyze .codeql-db "$CODEQL_QUERIES" --format=sarif-latest --output=codeql-results.sarif
else
  echo "Run from the repository root"
  exit 1
fi
