#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f database.py || ! -d dashboard || ! -d proxy_monitor ]]; then
  echo "[FAIL] Run this script from the SecPath ProxyPool repository overlay." >&2
  exit 1
fi

backup_dir=".local-backup/foundation-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"

# These duplicate files are obsolete, but retain a local copy in case an old
# process wrote state there that still needs manual inspection.
for path in dashboard/.monitors.json dashboard/.servers.json; do
  if [[ -f "$path" ]]; then
    cp -a "$path" "$backup_dir/$(basename "$path")"
  fi
done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[git] Stop tracking local runtime data while preserving root files"
  git rm --cached --ignore-unmatch \
    proxies.db .monitors.json .servers.json .server_config.json
  git rm --cached --ignore-unmatch progress/*.json 2>/dev/null || true

  echo "[git] Remove obsolete notes, temporary patches, and duplicate state"
  git rm -f --ignore-unmatch PHASE*_NOTES.md patch.py patch.sh
  git rm -f --ignore-unmatch dashboard/.monitors.json dashboard/.servers.json
else
  echo "[warn] Git metadata not found; removing obsolete files from the working tree only"
  rm -f PHASE*_NOTES.md patch.py patch.sh
  rm -f dashboard/.monitors.json dashboard/.servers.json
fi

bash scripts/clean_runtime.sh

# Remove the directory only when it contains no local progress state.
rmdir progress 2>/dev/null || true

echo
if find "$backup_dir" -mindepth 1 -print -quit | grep -q .; then
  echo "[info] Duplicate dashboard runtime state was copied to: $backup_dir"
else
  rmdir "$backup_dir" 2>/dev/null || true
  rmdir .local-backup 2>/dev/null || true
fi

echo "[OK] Foundation cleanup applied. No deployment or commit was performed."
echo "Next: bash scripts/health_check.sh"
echo "Then: bash scripts/repo_hygiene_check.sh"
