# ProxyPool Control Center

ProxyPool is a local-first proxy inventory, validation, monitoring, and rotating proxy server dashboard.

Current focus: build a commercially viable proxy-quality pipeline where an `alive` proxy means it is highly likely to work in real-world use cases, not just respond to a weak TCP/HTTP check.

## What it does

- Imports HTTP / HTTPS / SOCKS4 / SOCKS5 proxies from URLs or files.
- Stores proxies in SQLite by default for local/dev use.
- Continuously validates proxies with real capability checks.
- Tracks lifecycle states: `untested`, `alive`, `soft`, `cooling`, `dead`, `revived`, `semi-revived`, `flaky`.
- Exposes a dashboard for inventory, monitoring, cleanup, server profiles, and stats.
- Runs local rotating proxy server profiles with use-case filters.

## Protocol quality model

Phase 8A made validation stricter:

- `web_http_ok`: proxy can load an HTTP endpoint.
- `web_https_ok`: proxy can load an HTTPS endpoint and return a real exit IP.
- `remote_dns_ok`: proxy supports proxy-side DNS where applicable (`socks5h`, `socks4a`).
- `telegram_ok`: proxy can reach Telegram API over HTTPS.
- `exit_ip`: detected public exit IP.

For production-like web browsing, prefer proxies with `web_https_ok=True`.
For Telegram, prefer `web_https_ok=True`, `remote_dns_ok=True`, and `telegram_ok=True`.

## Requirements

- Linux/WSL recommended.
- Python 3.10+.
- `pip`.
- Optional: MySQL for production, but SQLite is the default local database.

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick start – local SQLite

```bash
cd /home/mahdi/projects/proxyPool
./scripts/dev_setup.sh
./scripts/run_dashboard.sh
```

Open:

```text
http://localhost:5003
```

Default login is controlled by `dashboard/config.py` / environment settings. In the current dev fallback, use the existing admin credentials from previous phases.

## Manual local run

```bash
cd /home/mahdi/projects/proxyPool
export DB_TYPE=sqlite
export SQLITE_DB_PATH=proxies.db
python3 -c "from database import init_db; init_db()"
python3 dashboard/app.py
```

## Importing proxies

Use the dashboard Import tools, or run the importer if using its CLI/file workflow:

```bash
export DB_TYPE=sqlite
python3 proxy_importer/app.py --help
```

## Running a monitor once

Validate/revalidate proxies:

```bash
./scripts/run_monitor_once.sh
```

Common targeted examples:

```bash
# Re-scan legacy/reclassified rows after Normalize Legacy Statuses
export DB_TYPE=sqlite
python3 proxy_monitor/app.py --run-mode once --status dead,soft,revived,semi-revived --threads 50 --timeout 5 --probes 2 --geo false

# Check only SOCKS5 candidates
export DB_TYPE=sqlite
python3 proxy_monitor/app.py --run-mode once --protocol socks5 --status untested,soft,dead --threads 50 --timeout 5 --probes 2 --geo false
```

## Server profiles and use cases

Dashboard server profiles now include `Use Case Preset`:

- **Web Browsing (HTTPS)**: requires `web_https_ok`.
- **Telegram (HTTPS+DNS+TG)**: requires HTTPS, remote DNS, and Telegram reachability.
- **Scraping / HTTP**: does not require HTTPS capability.
- **Custom**: manually control flags.

CLI equivalent example:

```bash
export DB_TYPE=sqlite
python3 proxy_server/app.py   --protocol http   --bind 0.0.0.0   --listen_port 8080   --candidate_statuses alive   --require_web_https   --rotate better_cost
```

Test the local proxy server:

```bash
curl -x http://127.0.0.1:8080 https://api.ipify.org
```

## Health check

```bash
./scripts/health_check.sh
```

Repository hygiene check:

```bash
./scripts/repo_hygiene_check.sh
```

Cleanup generated runtime/cache files:

```bash
./scripts/clean_runtime.sh
```

This checks Python syntax, DB selection, dashboard imports, and key validation helpers.

## SQLite vs MySQL

Local/dev default is now SQLite:

```bash
DB_TYPE=sqlite
SQLITE_DB_PATH=proxies.db
```

Production MySQL remains supported, but must be explicit:

```bash
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=proxypool
DB_PASS=...
DB_NAME=proxypool
```

Do not switch production database settings without backing up first.

## Recommended post-Phase-8 workflow

1. Start dashboard.
2. Go to Settings.
3. Click **⚡ Normalize Legacy Statuses**.
4. Run a monitor over reclassified/old rows.
5. Use Proxy Inventory `Ready: Web / Telegram / DNS` chips to inspect usable proxies.
6. Start server profiles using the correct use-case preset.

## Project notes

Phase notes are kept in files named `PHASE*_NOTES.md`. The most important current ones:

- `PHASE8A_PROTOCOL_QUALITY_NOTES.md`
- `PHASE8B_USE_CASE_NOTES.md`
- `PHASE8B1_SQLITE_DEFAULT_NOTES.md`
- `RUNBOOK.md`

## Safety

- Do not deploy without explicit approval.
- Back up `proxies.db` before destructive import/replace operations.
- Treat public free proxy lists as untrusted and unstable.
- Use `web_https_ok` / `telegram_ok` filters before using proxies for real traffic.
