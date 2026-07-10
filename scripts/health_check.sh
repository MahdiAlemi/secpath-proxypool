#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export DB_TYPE="${DB_TYPE:-sqlite}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-proxies.db}"

echo "[1/5] Python compile"
python3 -m compileall -q config.py database.py dashboard proxy_monitor proxy_importer proxy_server

echo "[2/5] JavaScript syntax"
if command -v node >/dev/null 2>&1; then
  node --check dashboard/static/js/base.js
else
  echo "node not found; skipping JS syntax check"
fi

echo "[3/5] Config/database URL"
python3 - <<'PY'
from config import config
print('DB_TYPE', config.DB_TYPE)
print('DATABASE_URL', config.get_database_url())
assert config.get_database_url().startswith(('sqlite:///', 'mysql+pymysql://'))
PY

echo "[4/5] Dashboard app import"
python3 - <<'PY'
from dashboard import create_app
app = create_app()
print('routes', len(app.url_map._rules))
PY

echo "[5/5] Validation helper smoke"
python3 - <<'PY'
from proxy_monitor.utils.validation import is_ip, protocol_candidates
assert is_ip('1.1.1.1')
assert not is_ip('example.com')
socks5_first = protocol_candidates('socks5')[0]
assert socks5_first.get('scheme') == 'socks5h'
assert socks5_first.get('remote_dns') is True
print('validation helpers OK')
PY

if [[ -d tests ]]; then
  echo "[extra] Unit tests"
  ./scripts/test.sh
fi

echo "[OK] Health check passed"
