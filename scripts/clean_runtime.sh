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
Usage: ./scripts/clean_runtime.sh [--include-state] [--include-db]

Safely removes generated runtime/cache files:
  - __pycache__ directories
  - *.pyc files
  - *.log / *.pid files

Optional:
  --include-state  also removes .monitors.json/.servers.json/progress/*.json
  --include-db     also removes local SQLite DB/backups (*.db, *.sqlite, backup SQL)

Default mode does NOT remove DB or dashboard/server runtime state.
HELP
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

echo "[clean] Removing Python caches"
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

echo "[clean] Removing logs and pid files"
find . -maxdepth 3 -type f \( -name '*.log' -o -name '*.pid' \) -delete

if [[ "$include_state" == true ]]; then
  echo "[clean] Removing runtime state files"
  rm -f .monitors.json .servers.json .server_config.json dashboard/.monitors.json dashboard/.servers.json
  rm -f progress/*.json 2>/dev/null || true
fi

if [[ "$include_db" == true ]]; then
  echo "[clean] Removing local DB/backups"
  rm -f *.db *.sqlite *.sqlite3 proxies_backup_*.sql proxies_backup_*.sqlite proxies_backup_before_import_*.sqlite
fi

echo "[OK] Runtime cleanup complete"
