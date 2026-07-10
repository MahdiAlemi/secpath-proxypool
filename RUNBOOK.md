# ProxyPool local runbook

This runbook covers local WSL operation only. It does not authorize or perform deployment.

## 1. Enter the project

```bash
cd /home/mahdi/projects/proxyPool
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
cd /home/mahdi/projects/proxyPool
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

## 11. Authentication bootstrap

There is no built-in default dashboard password. Create a database-backed administrator against the active database:

```bash
cd /home/mahdi/projects/proxyPool
source .venv/bin/activate
python3 scripts/create_admin.py --username admin --role admin
```

To intentionally replace that database user's password or role:

```bash
python3 scripts/create_admin.py --username admin --role admin --update
```

The command prompts for the password and does not place it in shell history or process arguments.

Set persistent secrets in `.env` before normal use:

```dotenv
FLASK_SECRET_KEY=<random-64-hex-value>
JWT_SECRET=<different-random-64-hex-value>
SESSION_COOKIE_SECURE=false
```

Generate values with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Use `SESSION_COOKIE_SECURE=true` only behind HTTPS. The local HTTP development address requires `false`.

## 12. Phase 1 verification

After applying the security overlay:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests scripts/create_admin.py
node --check dashboard/static/js/base.js
node --check dashboard/static/js/login.js
git diff --check
git status --short
```

Before opening the dashboard, confirm either a database user exists or `DASHBOARD_PASSWORD` is intentionally configured. No deploy, service restart, or remote change is part of these steps.


## 13. Phase 2 monitor lifecycle verification

After applying the monitor lifecycle overlay:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard proxy_monitor tests
node --check dashboard/static/js/base.js
ruff check dashboard/routes/monitor.py dashboard/config.py proxy_monitor tests/test_monitor_lifecycle.py
git diff --check
git status --short
```

The automated lifecycle tests use disposable runtime directories and test databases. They verify duplicate-start rejection, PID identity checks, graceful termination, partial-progress pause, and resume-to-completion.

### Local monitor behavior

- **Pause** cooperatively stops the current process and preserves session progress for Resume.
- **Resume** skips proxy IDs already completed in the paused session.
- **Stop** preserves the visible final snapshot, but the next Start creates a fresh session.
- **Remove Service** is separate from Stop and requires root privileges.

A profile configured with `create_service=yes` does not modify systemd merely because the overlay is applied. systemd is touched only when an authorized dashboard user explicitly starts or removes that service-backed profile.
