#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TEST_DB="$(mktemp "${TMPDIR:-/tmp}/proxypool-tests.XXXXXX.sqlite")"
cleanup() {
  rm -f "$TEST_DB" "$TEST_DB-shm" "$TEST_DB-wal"
}
trap cleanup EXIT

export DB_TYPE=sqlite
export SQLITE_DB_PATH="$TEST_DB"

python3 -m unittest discover -s tests -p 'test_*.py' -v
