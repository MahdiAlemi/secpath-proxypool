#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[skip] Not inside a Git repository"
  exit 0
fi

bad_patterns=(
  '*.pyc'
  '__pycache__/*'
  '*/__pycache__/*'
  '*.log'
  '*.pid'
  '*.db'
  '*.sqlite'
  '*.sqlite3'
  'progress/*.json'
  '.monitors.json'
  '.servers.json'
  '.server_config.json'
  '.runtime/*'
  '.monitors.json.lock'
  '.servers.json.lock'
  'dashboard/.monitors.json'
  'dashboard/.servers.json'
  'PHASE*_NOTES.md'
  'patch.py'
  'patch.sh'
)

mapfile -t bad_paths < <(
  for pattern in "${bad_patterns[@]}"; do
    git ls-files -- "$pattern"
  done | sort -u
)

if ((${#bad_paths[@]} > 0)); then
  echo "[FAIL] Generated, runtime, or obsolete files are tracked by Git:"
  printf '  - %s\n' "${bad_paths[@]}"
  echo
  echo "Run the cleanup apply script included in the foundation overlay:"
  echo "  bash scripts/apply_phase0_cleanup.sh"
  exit 1
fi

if git ls-files -s | awk '$1 == "100755" {print $4}' | grep -Ev '^(scripts/|dashboard/app.py$|proxy_importer/app.py$|proxy_monitor/app.py$|proxy_server/app.py$|migrate.py$)' >/tmp/proxypool-executable-files.$$; then
  echo "[WARN] Non-entrypoint source files still have executable Git mode:"
  sed 's/^/  - /' /tmp/proxypool-executable-files.$$
  rm -f /tmp/proxypool-executable-files.$$
else
  rm -f /tmp/proxypool-executable-files.$$
fi

echo "[OK] Repository hygiene check passed"
