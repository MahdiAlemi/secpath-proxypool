#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export DB_TYPE="${DB_TYPE:-sqlite}"
export SQLITE_DB_PATH="${SQLITE_DB_PATH:-proxies.db}"

python3 -m pip install -r requirements.txt
python3 -c "from database import init_db; init_db()"

echo "[OK] Development setup complete"
echo "DB_TYPE=$DB_TYPE"
echo "SQLITE_DB_PATH=$SQLITE_DB_PATH"
echo "Run: ./scripts/run_dashboard.sh"
