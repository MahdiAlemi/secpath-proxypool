#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

require_clean=false
for arg in "$@"; do
  case "$arg" in
    --require-clean) require_clean=true ;;
    -h|--help)
      cat <<'HELP'
Usage: bash scripts/release_check.sh [--require-clean]

Runs the full local release-readiness suite without deploying, starting
services, or touching the working proxies.db.  --require-clean additionally
fails when the Git working tree has uncommitted changes.
HELP
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v ruff >/dev/null 2>&1; then
  echo "[FAIL] ruff is required. Install: python3 -m pip install -r requirements-dev.txt" >&2
  exit 1
fi

workdir="$(mktemp -d "${TMPDIR:-/tmp}/proxypool-release.XXXXXX")"
cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT

source_db="$workdir/source.sqlite"
target_db="$workdir/target.sqlite"
restore_db="$workdir/restored.sqlite"
backup_dir="$workdir/backups"

export DB_TYPE=sqlite
export SQLITE_DB_PATH="$source_db"
export FLASK_SECRET_KEY="release-check-flask-secret-not-for-runtime"
export JWT_SECRET="release-check-jwt-secret-not-for-runtime"

printf '%s\n' '[1/8] Project dependency consistency'
python3 - <<'PY'
import importlib.metadata as metadata
import re
from pathlib import Path

missing = []
for raw in Path('requirements.txt').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or line.startswith('-'):
        continue
    name = re.split(r'[<>=!~;[]', line, maxsplit=1)[0].strip()
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        missing.append(name)
if missing:
    raise SystemExit('Missing project dependencies: ' + ', '.join(missing))
print('Project dependencies are installed')
PY
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  python3 -m pip check
else
  echo '[warn] No active virtualenv; skipping global-environment pip check'
fi

printf '%s\n' '[2/8] Prepare disposable data'
SOURCE_DB="$source_db" python3 - <<'PY'
import json
import os
import sqlite3

connection = sqlite3.connect(os.environ['SOURCE_DB'])
try:
    connection.executescript(
        """
        CREATE TABLE proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol VARCHAR(10) NOT NULL,
            ip VARCHAR(45) NOT NULL,
            port INTEGER NOT NULL,
            username VARCHAR(255) NOT NULL DEFAULT '',
            password VARCHAR(255) NOT NULL DEFAULT '',
            status VARCHAR(20) DEFAULT 'untested',
            web_https_ok BOOLEAN DEFAULT 0,
            validation_summary JSON
        );
        CREATE UNIQUE INDEX idx_unique_proxy
        ON proxies(protocol, ip, port, username, password);
        """
    )
    connection.execute(
        "INSERT INTO proxies "
        "(protocol, ip, port, username, password, status, web_https_ok, validation_summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "http",
            "198.51.100.44",
            8080,
            "release-user",
            "release-secret",
            "alive",
            1,
            json.dumps({"source": "release-check"}),
        ),
    )
    connection.commit()
finally:
    connection.close()
print('Disposable source database prepared')
PY

printf '%s\n' '[3/8] Backup and restore round-trip'
python3 scripts/sqlite_backup.py backup --source "$source_db" --directory "$backup_dir"
backup_file="$(find "$backup_dir" -maxdepth 1 -type f -name 'proxies_backup_*.sqlite' -print -quit)"
test -n "$backup_file"
python3 scripts/sqlite_backup.py verify "$backup_file"
python3 scripts/sqlite_backup.py restore "$backup_file" --destination "$restore_db" --backup-directory "$backup_dir" --yes
RESTORE_DB="$restore_db" python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

path = Path(os.environ['RESTORE_DB'])
connection = sqlite3.connect(path)
try:
    row = connection.execute(
        "SELECT protocol, ip, port, username, password, validation_summary FROM proxies"
    ).fetchone()
finally:
    connection.close()
assert row[:5] == ("http", "198.51.100.44", 8080, "release-user", "release-secret"), row
assert "release-check" in (row[5] or ""), row
assert path.stat().st_mode & 0o777 == 0o600, oct(path.stat().st_mode & 0o777)
PY

printf '%s\n' '[4/8] Migration dry-run and disposable execution'
python3 migrate.py --source "$source_db" --target-url "sqlite:///$target_db"
python3 migrate.py --source "$source_db" --target-url "sqlite:///$target_db" --execute
TARGET_DB="$target_db" python3 - <<'PY'
import os
import sqlite3

connection = sqlite3.connect(os.environ['TARGET_DB'])
try:
    row = connection.execute(
        "SELECT protocol, ip, port, username, password, web_https_ok, validation_summary FROM proxies"
    ).fetchone()
finally:
    connection.close()
assert row[:5] == ("http", "198.51.100.44", 8080, "release-user", "release-secret"), row
assert row[5] == 1, row
assert "release-check" in (row[6] or ""), row
PY

printf '%s\n' '[5/8] Health and regression suite'
health_log="$workdir/health.log"
if ! bash scripts/health_check.sh >"$health_log" 2>&1; then
  cat "$health_log"
  exit 1
fi
tail -n 4 "$health_log"

printf '%s\n' '[6/8] Repository hygiene'
bash scripts/repo_hygiene_check.sh

printf '%s\n' '[7/8] Static analysis'
ruff check dashboard proxy_importer proxy_monitor proxy_server public_monitor tests scripts backup_utils.py migrate.py secpath_meta.py

printf '%s\n' '[8/8] Git consistency'
git diff --check
if [[ "$require_clean" == true ]] && [[ -n "$(git status --porcelain)" ]]; then
  echo "[FAIL] Git working tree is not clean" >&2
  git status --short
  exit 1
fi

echo "[OK] Release readiness passed. No deploy or service restart was performed."
