#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

HEALTH_DB="$(mktemp "${TMPDIR:-/tmp}/proxypool-health.XXXXXX.sqlite")"
cleanup() {
  rm -f "$HEALTH_DB" "$HEALTH_DB-shm" "$HEALTH_DB-wal"
}
trap cleanup EXIT

export DB_TYPE=sqlite
export SQLITE_DB_PATH="$HEALTH_DB"

echo "[1/6] Python compile"
python3 -m compileall -q config.py database.py dashboard proxy_monitor proxy_importer proxy_server tests

echo "[2/6] JavaScript syntax"
if command -v node >/dev/null 2>&1; then
  node --check dashboard/static/js/base.js
  node --check dashboard/static/js/inventory.js
  node --check dashboard/static/js/shell.js
  node --check dashboard/static/js/login.js
else
  echo "node not found; skipping JavaScript syntax checks"
fi

echo "[3/6] Fresh database and application startup"
python3 - <<'PY'
from sqlalchemy import inspect

from dashboard import create_app
from database import db

app = create_app()
app.config["TESTING"] = True
required = {"proxies", "users", "tokens", "monitor_sessions", "monitor_tested"}
actual = set(inspect(db.engine).get_table_names())
missing = required - actual
assert not missing, f"missing tables: {sorted(missing)}"
with app.test_client() as client:
    response = client.get("/login")
    assert response.status_code == 200, response.status_code
print("fresh database startup OK")
PY

echo "[4/6] Configuration selection"
python3 - <<'PY'
from config import config

url = config.get_database_url()
print("DB_TYPE", config.DB_TYPE)
print("DATABASE_URL", url)
assert config.DB_TYPE.lower() == "sqlite"
assert url.startswith("sqlite:///")
PY

echo "[5/6] Validation helper smoke"
python3 - <<'PY'
from proxy_monitor.utils.validation import is_ip, protocol_candidates

assert is_ip("1.1.1.1")
assert not is_ip("example.com")
socks5_first = protocol_candidates("socks5")[0]
assert socks5_first.get("scheme") == "socks5h"
assert socks5_first.get("remote_dns") is True
print("validation helpers OK")
PY

echo "[6/6] Automated tests"
bash ./scripts/test.sh

echo "[OK] Health check passed"
