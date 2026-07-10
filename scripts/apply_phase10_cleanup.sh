#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

rm -f dashboard/static/css/compat.css

is_entrypoint() {
  case "$1" in
    scripts/*.sh|scripts/create_admin.py|dashboard/app.py|proxy_importer/app.py|proxy_monitor/app.py|proxy_server/app.py|migrate.py)
      return 0 ;;
    *) return 1 ;;
  esac
}

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  while IFS= read -r -d '' path; do
    [[ -e "$path" ]] || continue
    if is_entrypoint "$path"; then
      chmod 0755 "$path"
      git update-index --chmod=+x -- "$path" 2>/dev/null || true
    else
      chmod 0644 "$path"
      git update-index --chmod=-x -- "$path" 2>/dev/null || true
    fi
  done < <(git ls-files -z)
else
  find . -type f -not -path './.git/*' -exec chmod 0644 {} +
  find scripts -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +
  chmod 0755 scripts/create_admin.py dashboard/app.py proxy_importer/app.py proxy_monitor/app.py proxy_server/app.py migrate.py
fi

echo "[OK] Removed the compatibility stylesheet and normalized executable modes."
