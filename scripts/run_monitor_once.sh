#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export DB_TYPE="${DB_TYPE:-sqlite}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-proxies.db}"

STATUS="${STATUS:-untested,soft,dead,revived,semi-revived}"
PROTOCOL="${PROTOCOL:-}"
THREADS="${THREADS:-50}"
TIMEOUT="${TIMEOUT:-5}"
PROBES="${PROBES:-2}"
GEO="${GEO:-false}"

cmd=(python3 proxy_monitor/app.py --run-mode once --status "$STATUS" --threads "$THREADS" --timeout "$TIMEOUT" --probes "$PROBES" --geo "$GEO")
if [[ -n "$PROTOCOL" ]]; then
  cmd+=(--protocol "$PROTOCOL")
fi

printf '[RUN]'
printf ' %q' "${cmd[@]}"
printf '
'
exec "${cmd[@]}"
