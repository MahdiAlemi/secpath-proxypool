# ProxyPool local runbook

This runbook covers local WSL operation only. It does not authorize or perform deployment.

## 1. Enter the project

```bash
cd /home/mahdi/projects/proxypool
source .venv/bin/activate
```

## 2. Verify an overlay before running the application

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
git diff --check
git status --short
```

The test and health scripts use temporary SQLite files. They do not intentionally read from or write to `proxies.db`.

## 3. Start the dashboard locally

```bash
bash scripts/run_dashboard.sh
```

Open:

```text
http://127.0.0.1:5003
```

Stop it with `Ctrl+C`. Do not expose the development server directly to a public network.

## 4. Initialize or inspect SQLite

A fresh database is initialized automatically when the Flask application is created. Manual initialization remains available:

```bash
DB_TYPE=sqlite SQLITE_DB_PATH=proxies.db \
python3 -c "from database import init_db; init_db()"
```

Inspect table names without changing data:

```bash
sqlite3 proxies.db '.tables'
```

## 5. Back up SQLite safely

Stop processes that write to the database, then use SQLite's backup command:

```bash
mkdir -p backups
sqlite3 proxies.db ".backup 'backups/proxies_$(date +%Y%m%d_%H%M%S).sqlite'"
```

Do not rely on copying a live SQLite file while writers are active.

## 6. Runtime cleanup

Remove only caches, logs, and PID files:

```bash
bash scripts/clean_runtime.sh
```

Remove generated monitor/server state as well:

```bash
bash scripts/clean_runtime.sh --include-state
```

Remove local databases only when a verified backup exists and deletion is intentional:

```bash
bash scripts/clean_runtime.sh --include-db
```

## 7. Apply a ZIP overlay

```bash
cd /home/mahdi/projects/proxypool
unzip -o /mnt/c/Users/Mahdi/Downloads/<overlay>.zip -d .
```

Read any included apply script before running it:

```bash
sed -n '1,240p' scripts/apply_phase0_cleanup.sh
bash scripts/apply_phase0_cleanup.sh
```

Then run the verification commands in section 2. Commit only after local verification and review.

## 8. Diagnose startup failures

Confirm the selected database:

```bash
python3 - <<'PY'
from config import config
print(config.DB_TYPE)
print(config.get_database_url())
PY
```

Compile Python sources:

```bash
python3 -m compileall -q config.py database.py dashboard proxy_importer proxy_monitor proxy_server
```

Check JavaScript syntax when Node.js is installed:

```bash
node --check dashboard/static/js/base.js
```

Run tests with verbose output:

```bash
bash scripts/test.sh
```

## 9. Git safety

Before committing:

```bash
git status --short
git diff --stat
git diff --check
bash scripts/repo_hygiene_check.sh
```

Never commit `.env`, databases, runtime JSON, progress snapshots, logs, PID files, caches, or generated ZIP files.

## 10. Deployment boundary

No local script in the rebuild workflow should deploy, restart production services, edit reverse-proxy configuration, or modify a remote host. Deployment requires a separate explicit instruction and a separately reviewed procedure.
