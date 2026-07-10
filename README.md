# ProxyPool

ProxyPool is a local-first proxy inventory, validation, monitoring, and proxy-serving application built with Python, Flask, SQLAlchemy, and a browser dashboard.

The repository is being rebuilt in controlled overlays. Existing backend behavior is preserved unless a phase explicitly changes and tests it. Deployment is never part of an overlay unless it is separately and explicitly approved.

## Components

- `proxy_importer/`: imports and normalizes proxy sources.
- `proxy_monitor/`: validates proxy reachability and capabilities.
- `proxy_server/`: exposes local HTTP/SOCKS proxy listeners backed by the pool.
- `dashboard/`: Flask dashboard and JSON API.
- `database.py`: SQLAlchemy models and database lifecycle.
- `tests/`: automated regression tests.
- `scripts/`: local setup, health checks, cleanup, and overlay helpers.

## Local project path

```bash
cd /home/mahdi/projects/proxyPool
```

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
cp -n .env.example .env
```

Review `.env` before starting the application. Do not use example credentials or secrets outside a local development machine.

The local default database is SQLite:

```dotenv
DB_TYPE=sqlite
SQLITE_DB_PATH=proxies.db
```

An explicit SQLAlchemy URL takes precedence when set:

```dotenv
DATABASE_URL=sqlite:////absolute/path/to/proxies.sqlite
```

Start the dashboard:

```bash
bash scripts/run_dashboard.sh
```

The default dashboard address is:

```text
http://127.0.0.1:5003
```

## Verification

Run the complete local baseline check:

```bash
bash scripts/health_check.sh
```

Run tests only:

```bash
bash scripts/test.sh
```

Both commands use disposable SQLite databases and must not modify the working `proxies.db`.

Check repository hygiene:

```bash
bash scripts/repo_hygiene_check.sh
```

## Overlay workflow

Each approved change set is delivered as a ZIP overlay. From the repository root:

```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/<overlay>.zip -d .
```

When the overlay includes an apply script, run it next. For example:

```bash
bash scripts/apply_phase0_cleanup.sh
```

Then verify before committing:

```bash
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
git status --short
```

A ZIP archive can add or overwrite files but cannot remove tracked files. Cleanup overlays therefore include an explicit, reviewable apply script for deletions and `git rm --cached` operations.

## Runtime data

The following are local runtime data and must not be committed:

- `.env`
- `proxies.db` and database backups
- `.monitors.json`, `.servers.json`, `.server_config.json`
- `.runtime/` and registry lock files
- `progress/*.json`
- logs, PID files, caches, and generated archives

The cleanup script preserves the root database and current root runtime state while removing them from Git tracking.

## Database selection

SQLite is the supported local default. MySQL must be selected explicitly:

```dotenv
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=proxypool
DB_PASS=<strong-password>
DB_NAME=proxypool
```

Back up the active database before any destructive import, restore, or schema operation.

## Current engineering status

The original dashboard and backend have known correctness, security, lifecycle, and maintainability issues. The verified baseline and rebuild sequence are documented in [`docs/BASELINE_AUDIT.md`](docs/BASELINE_AUDIT.md). The dashboard will be replaced rather than incrementally restyled.

## Authentication and security baseline

The application no longer ships with a built-in default password. Prefer a database-backed administrator:

```bash
python3 scripts/create_admin.py --username admin --role admin
```

Set independent random values for `FLASK_SECRET_KEY` and `JWT_SECRET` in `.env`. The optional `DASHBOARD_PASSWORD` variable only enables a legacy environment-backed admin account for migration compatibility.

Browser mutations require CSRF tokens. General proxy APIs and exports redact upstream credentials. Credential-bearing export requires the `proxies.credentials` permission and `include_credentials=true`.

The complete local security baseline and remaining boundaries are documented in [`docs/SECURITY.md`](docs/SECURITY.md).


## Monitor lifecycle

Monitor processes now use atomic runtime claims, exact process-identity checks, cooperative cancellation, resumable paused sessions, and accurate progress persistence. Direct subprocess and systemd starts are mutually exclusive, so enabling a service no longer launches a duplicate monitor.

Operational states and recovery behavior are documented in [`docs/MONITOR_LIFECYCLE.md`](docs/MONITOR_LIFECYCLE.md).

## Proxy server core

Proxy listeners now default to loopback, reject unauthenticated non-loopback binds unless an explicit override is set, keep listener credentials out of process arguments, and use process-safe runtime claims. HTTP CONNECT, normal HTTP forwarding, SOCKS4/SOCKS4a, SOCKS5, upstream HTTPS TLS/SNI, bounded concurrency, retry exclusion, and sticky client affinity are covered by regression tests.

Operational behavior and protocol boundaries are documented in [`docs/PROXY_SERVER_CORE.md`](docs/PROXY_SERVER_CORE.md).

## New dashboard foundation

The dashboard now uses a responsive sidebar shell, a focused operational Cockpit, modular Jinja page templates, and a shared light/dark design system. See `docs/UI_FOUNDATION.md` for the phase boundary and migration structure.

## Inventory workspace

The proxy Inventory now uses a compact, responsive table with operational filters, explicit multi-selection, scoped bulk actions, and a detail drawer for progressive disclosure. Credential redaction and per-user proxy scope are enforced by the API rather than only by the browser. See [`docs/INVENTORY_UI.md`](docs/INVENTORY_UI.md).

## Sources and import workspace

Proxy ingestion now uses a preflight-first workspace for manual batches, public list URLs, and grouped protocol sources. Preview and execution share the same normalization engine, saved sources can be edited and rerun, and actual imports create a sanitized audit trail. See [`docs/SOURCES_UI.md`](docs/SOURCES_UI.md).
## Validation workspace

Validation profiles now use a dedicated, responsive workspace with searchable runtime states, live progress, recent credential-redacted outcomes, log inspection, and a non-mutating candidate preview before save. The monitor lifecycle remains process-safe and resumable. See [`docs/VALIDATION_UI.md`](docs/VALIDATION_UI.md).

## Serving workspace

Server profiles now use a dedicated Serving Center with searchable runtime state, credential-redacted profile details, copyable client endpoints, bounded log inspection, capability-aware candidate preflight, and a responsive profile editor. Listener security and process ownership remain enforced by the backend. See [`docs/SERVING_UI.md`](docs/SERVING_UI.md).

## Insights, Operations, and Access

The remaining administration surfaces now use dedicated responsive pages. Insights summarizes quality, freshness, latency, reliability, capability coverage, and network concentration. Operations provides security/runtime preflight, backups, password rotation, and guarded maintenance. Access manages database users, effective permissions, proxy scope, and API sessions while protecting the final active administrator. See [`docs/INSIGHTS_OPERATIONS_UI.md`](docs/INSIGHTS_OPERATIONS_UI.md).

## Phase 10 finalization

After applying the finalization overlay, run:

```bash
bash scripts/apply_phase10_cleanup.sh
bash scripts/health_check.sh
bash scripts/repo_hygiene_check.sh
```

The cleanup removes the retired UI compatibility stylesheet and normalizes executable modes. The health suite includes an end-to-end, network-free workflow test. See `docs/FINALIZATION.md`.

