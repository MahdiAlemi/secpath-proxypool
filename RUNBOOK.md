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

## 14. Phase 3 proxy server core verification

After applying the proxy server core overlay:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard proxy_server tests
node --check dashboard/static/js/base.js
ruff check proxy_server dashboard/routes/server.py dashboard/utils/process.py tests/test_proxy_server_core.py
git diff --check
git status --short
```

### Listener exposure rule

The safe default is:

```text
127.0.0.1
```

A bind on `0.0.0.0`, `::`, a LAN address, or another non-loopback address requires listener authentication. The dashboard contains a separate **Public no-auth** override, but enabling it intentionally creates an open proxy for every reachable client and is not recommended.

### Runtime files

Active server profiles use protected files under:

```text
.runtime/servers/
```

Do not copy, publish, or commit those files. Listener credentials are not included in the child process command line. Stopping or deleting the profile removes its runtime profile file.

### Local protocol checks

For a loopback HTTP listener on port `8080`:

```bash
curl -v -x http://127.0.0.1:8080 http://example.com/
curl -v -x http://127.0.0.1:8080 https://example.com/
```

For an authenticated HTTP listener:

```bash
curl -v -x http://USER:PASSWORD@127.0.0.1:8080 https://example.com/
```

For SOCKS5 with proxy-side DNS:

```bash
curl -v --proxy socks5h://127.0.0.1:1080 https://example.com/
```

These commands generate traffic and may update upstream health counters unless the server profile is configured as read-only. They are local operator checks, not deployment steps.

## UI foundation verification

After applying the UI overlay, verify template composition and browser assets with:

```bash
bash scripts/health_check.sh
python3 -m unittest -v tests.test_ui_foundation
node --check dashboard/static/js/base.js
node --check dashboard/static/js/shell.js
node --check dashboard/static/js/login.js
```

This phase does not require a database migration, service restart, or deployment.

## Phase 5 Inventory verification

After applying the Inventory overlay, run:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests
node --check dashboard/static/js/base.js
node --check dashboard/static/js/inventory.js
node --check dashboard/static/js/shell.js
node --check dashboard/static/js/login.js
python3 -m unittest -v tests.test_inventory_ui
git diff --check
git status --short
```

The tests verify scoped proxy details, credential redaction, bounded selection deletion, grouped export filters, dedicated Inventory assets, and the compact page structure.

### Local visual review

Start the dashboard only when a local visual review is required:

```bash
bash scripts/run_dashboard.sh
```

Open `http://127.0.0.1:5003/index?tab=proxies` and check the table, filters, drawer, selection bar, and narrow viewport layout. This is a local operator check; applying the overlay does not start, restart, or deploy the application.

## Phase 6 Sources and Import verification

After applying the Sources overlay, run:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests database.py
node --check dashboard/static/js/base.js
node --check dashboard/static/js/inventory.js
node --check dashboard/static/js/sources.js
node --check dashboard/static/js/shell.js
node --check dashboard/static/js/login.js
python3 -m unittest -v tests.test_sources_ui
git diff --check
git status --short
```

The dedicated tests use a disposable SQLite database. They verify non-mutating preview, credential redaction, saved-source CRUD, disabled-source enforcement, partial grouped imports, sanitized history, and automatic creation of the `import_sources` and `import_runs` tables.

### Local visual review

Start the development dashboard only for a local review:

```bash
bash scripts/run_dashboard.sh
```

Open `http://127.0.0.1:5003/index?tab=import` and check all three input modes, preflight metrics, saved-source editing, recent history, dark mode, and a narrow viewport. Applying the overlay does not start or restart the application and is not a deployment.

The first application startup after this phase creates two additive tables. Existing Proxy records are not modified. Database backups can contain saved source URLs or grouped configurations and must remain protected.

## 17. Phase 7 validation workspace verification

After applying the Validation overlay:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests
node --check dashboard/static/js/base.js
node --check dashboard/static/js/validation.js
python3 -m unittest -v tests.test_validation_ui
git diff --check
git status --short
```

For a local visual review, start the development dashboard and open `http://127.0.0.1:5003/index?tab=monitor`. Verify profile search/state filtering, selected-profile details, candidate preview, Start/Pause/Resume/Stop controls, recent results, logs, dark mode, and a narrow viewport. This is a local review only; do not deploy or restart production services.

## 18. Phase 8 Serving Center verification

After applying the Serving overlay:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests
node --check dashboard/static/js/base.js
node --check dashboard/static/js/serving.js
node --check dashboard/static/js/shell.js
python3 -m unittest -v tests.test_serving_ui
git diff --check
git status --short
```

The dedicated tests use a disposable SQLite database. They verify the modular Serving assets, credential-redacted detail responses, scoped candidate preflight, bounded log access, strict status/protocol validation, profile metadata normalization, and edit preview with preserved hidden credentials.

For a local visual review only:

```bash
bash scripts/run_dashboard.sh
```

Open `http://127.0.0.1:5003/index?tab=server`. Check profile search and filtering, endpoint copy, preflight refresh, runtime logs, Start/Stop, the four editor presets, protected network-listener warnings, dark mode, and a narrow viewport. Do not expose a listener publicly during visual review. Applying the overlay does not start, restart, or deploy any service.

## Phase 9 Insights, Operations, and Access verification

After applying the Phase 9 overlay, run:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
python3 -m compileall -q dashboard tests
node --check dashboard/static/js/base.js
node --check dashboard/static/js/insights.js
node --check dashboard/static/js/operations.js
node --check dashboard/static/js/access.js
node --check dashboard/static/js/shell.js
python3 -m unittest -v tests.test_insights_operations
git diff --check
git status --short
```

The dedicated tests use a disposable SQLite database. They verify decision-oriented statistics, redacted diagnostics, backup-name validation, runtime cleanup guards, orphan process detection, enriched user scope/session data, and final-administrator protection.

### Local visual review

Start the development dashboard only for local review:

```bash
bash scripts/run_dashboard.sh
```

Review these pages after signing in:

```text
http://127.0.0.1:5003/index?tab=stats
http://127.0.0.1:5003/index?tab=operations
http://127.0.0.1:5003/index?tab=users
```

Check light/dark mode, narrow-window layout, permission-gated Operations controls, backup listing, user editing, proxy-scope display, and the final-administrator safeguards. Do not restore a backup or run destructive maintenance solely for visual testing.
