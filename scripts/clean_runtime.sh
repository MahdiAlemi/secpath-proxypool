#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

include_db=false
include_state=false

for arg in "$@"; do
  case "$arg" in
    --include-db) include_db=true ;;
    --include-state) include_state=true ;;
    -h|--help)
      cat <<'HELP'
Usage: bash scripts/clean_runtime.sh [--include-state] [--include-db]

Default cleanup removes project-generated Python caches, logs, and PID files.
It does not traverse virtual environments and does not remove the active DB or
monitor/server runtime state.

Optional:
  --include-state  remove monitor/server state and progress snapshots
  --include-db     remove local SQLite databases/backups (destructive)
HELP
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "[clean] Python caches"
rm -rf __pycache__
for root in dashboard proxy_importer proxy_monitor proxy_server tests; do
  [[ -e "$root" ]] || continue
  find "$root" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$root" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
done

echo "[clean] Logs and PID files"
find . -maxdepth 1 -type f \( -name '*.log' -o -name '*.pid' \) -delete
for root in dashboard proxy_importer proxy_monitor proxy_server progress tests; do
  [[ -d "$root" ]] || continue
  find "$root" -maxdepth 3 -type f \( -name '*.log' -o -name '*.pid' \) -delete
done

if [[ "$include_state" == true ]]; then
  echo "[clean] Runtime state"
  rm -f .monitors.json .servers.json .server_config.json
  rm -f dashboard/.monitors.json dashboard/.servers.json
  rm -f progress/*.json 2>/dev/null || true
  rm -rf .runtime
  rm -f .monitors.json.lock .servers.json.lock
fi

if [[ "$include_db" == true ]]; then
  echo "[clean] Local databases and backups"
  rm -f -- *.db *.sqlite *.sqlite3
  rm -f -- proxies_backup_*.sql proxies_backup_*.sqlite
  rm -f -- proxies_backup_before_import_*.sqlite
fi

echo "[OK] Runtime cleanup complete"
