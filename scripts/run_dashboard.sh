#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export DB_TYPE="${DB_TYPE:-sqlite}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-proxies.db}"

python3 dashboard/app.py
