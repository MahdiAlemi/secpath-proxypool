#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[skip] Not inside a git repository"
  exit 0
fi

bad_patterns=(
  '*.pyc'
  '__pycache__/*'
  '*.log'
  '*.pid'
  '*.db'
  '*.sqlite'
  '*.sqlite3'
  'progress/*.json'
  '.monitors.json'
  '.servers.json'
  '.server_config.json'
  'dashboard/.monitors.json'
  'dashboard/.servers.json'
)

found=false
for pattern in "${bad_patterns[@]}"; do
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if [[ "$found" == false ]]; then
      echo "[WARN] Runtime/cache artifacts are tracked by git:"
      found=true
    fi
    echo "  - $path"
  done < <(git ls-files -- "$pattern")
done

if [[ "$found" == true ]]; then
  cat <<'HELP'

Recommended cleanup (keeps local files, removes them from future commits):
  git rm --cached -r __pycache__ dashboard/__pycache__ proxy_importer/__pycache__ proxy_monitor/__pycache__ proxy_server/__pycache__ tests/__pycache__ 2>/dev/null || true
  git rm --cached -r progress 2>/dev/null || true
  git rm --cached proxies.db .monitors.json .servers.json .server_config.json dashboard/.monitors.json dashboard/.servers.json 2>/dev/null || true
  git add .gitignore scripts/clean_runtime.sh scripts/repo_hygiene_check.sh PHASE11_REPO_HYGIENE_NOTES.md
  git commit -m "Phase 11: Improve repository hygiene"
HELP
  exit 1
fi

echo "[OK] Repository hygiene check passed"
