#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[skip] Not inside a Git repository"
  exit 0
fi

bad_patterns=(
  '*.pyc' '__pycache__/*' '*/__pycache__/*' '*.log' '*.pid' '*.db' '*.sqlite' '*.sqlite3'
  'progress/*.json' '.monitors.json' '.servers.json' '.server_config.json' '.runtime/*'
  '.monitors.json.lock' '.servers.json.lock' 'dashboard/.monitors.json' 'dashboard/.servers.json'
  'PHASE*_NOTES.md' 'patch.py' 'patch.sh'
)

mapfile -t bad_paths < <(
  for pattern in "${bad_patterns[@]}"; do git ls-files -- "$pattern"; done | sort -u
)
if ((${#bad_paths[@]} > 0)); then
  echo "[FAIL] Generated, runtime, database, or obsolete files are tracked by Git:"
  printf '  - %s\n' "${bad_paths[@]}"
  exit 1
fi

if [[ -e dashboard/static/css/compat.css ]] && git ls-files --error-unmatch dashboard/static/css/compat.css >/dev/null 2>&1; then
  echo "[FAIL] The retired compatibility stylesheet is still tracked."
  echo "Run: bash scripts/apply_phase10_cleanup.sh"
  exit 1
fi

mapfile -t bad_modes < <(
  git ls-files -s | awk '$1 == "100755" {print $4}' |
    grep -Ev '^(scripts/[^/]+\.(sh|py)|dashboard/app\.py|proxy_importer/app\.py|proxy_monitor/app\.py|proxy_server/app\.py|migrate\.py)$' || true
)
if ((${#bad_modes[@]} > 0)); then
  echo "[FAIL] Non-entrypoint files have executable Git mode:"
  printf '  - %s\n' "${bad_modes[@]}"
  echo "Run: bash scripts/apply_phase10_cleanup.sh"
  exit 1
fi

if grep -RInE --exclude-dir=.git --exclude='*.log' --exclude='*.sqlite' --exclude='*.db' \
  '^(<<<<<<<|=======|>>>>>>>)' . >/tmp/proxypool-conflicts.$$; then
  echo "[FAIL] Merge-conflict markers found:"
  cat /tmp/proxypool-conflicts.$$
  rm -f /tmp/proxypool-conflicts.$$
  exit 1
fi
rm -f /tmp/proxypool-conflicts.$$

if grep -RIn 'style=' dashboard/templates >/tmp/proxypool-inline-styles.$$; then
  echo "[FAIL] Inline style attributes remain in dashboard templates:"
  cat /tmp/proxypool-inline-styles.$$
  rm -f /tmp/proxypool-inline-styles.$$
  exit 1
fi
rm -f /tmp/proxypool-inline-styles.$$

base_lines=$(wc -l < dashboard/static/js/base.js)
if ((base_lines > 650)); then
  echo "[FAIL] dashboard/static/js/base.js has grown to ${base_lines} lines; keep page logic modular."
  exit 1
fi

if [[ ! -f dashboard/static/img/favicon.svg ]]; then
  echo "[FAIL] dashboard/static/img/favicon.svg is missing"
  exit 1
fi

if [[ ! -f dashboard/static/img/favicon.ico ]]; then
  echo "[FAIL] dashboard/static/img/favicon.ico is missing"
  exit 1
fi

if grep -q 'app.run(host="0.0.0.0"' dashboard/app.py; then
  echo "[FAIL] Dashboard development server is hard-coded to a public bind."
  exit 1
fi

echo "[OK] Repository hygiene check passed"
