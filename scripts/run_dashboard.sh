#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export DB_TYPE="${DB_TYPE:-sqlite}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-proxies.db}"
export DASHBOARD_HOST="${DASHBOARD_HOST:-127.0.0.1}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-5003}"
export DASHBOARD_ALLOW_PUBLIC="${DASHBOARD_ALLOW_PUBLIC:-false}"

echo "Starting ProxyPool dashboard on http://${DASHBOARD_HOST}:${DASHBOARD_PORT}"
python3 dashboard/app.py
