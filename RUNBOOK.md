# ProxyPool Runbook

Operational guide for local development, validation, and production preparation.

## 1. Local development baseline

```bash
cd /home/mahdi/projects/proxyPool
export DB_TYPE=sqlite
export SQLITE_DB_PATH=proxies.db
python3 -m pip install -r requirements.txt
python3 -c "from database import init_db; init_db()"
python3 dashboard/app.py
```

Dashboard:

```text
http://localhost:5003
```

## 2. First checks after every overlay

```bash
python3 -m compileall -q config.py database.py dashboard proxy_monitor proxy_importer proxy_server
node --check dashboard/static/js/base.js
./scripts/health_check.sh
```

Expected:

- No Python syntax errors.
- `base.js` passes `node --check`.
- Health check reports `DB_TYPE sqlite` unless you explicitly configured MySQL.

## 3. SQLite database operations

### Initialize / upgrade schema

```bash
export DB_TYPE=sqlite
python3 -c "from database import init_db; init_db()"
```

### Backup SQLite manually

```bash
cp proxies.db proxies_backup_$(date +%Y%m%d_%H%M%S).sqlite
```

### Inspect capability distribution

```bash
export DB_TYPE=sqlite
python3 - <<'PY'
from database import db, Proxy
from sqlalchemy import func
with db.session() as s:
    rows = s.query(
        Proxy.status,
        Proxy.web_https_ok,
        Proxy.remote_dns_ok,
        Proxy.telegram_ok,
        func.count(Proxy.id),
    ).group_by(
        Proxy.status,
        Proxy.web_https_ok,
        Proxy.remote_dns_ok,
        Proxy.telegram_ok,
    ).all()
    for row in rows:
        print(row)
PY
```

## 4. Legacy status cleanup

After Phase 5+, old rows may still be marked `revived` without capability validation.

Recommended:

1. Dashboard → Settings → **⚡ Normalize Legacy Statuses**.
2. Run monitor again:

```bash
export DB_TYPE=sqlite
python3 proxy_monitor/app.py --run-mode once --status dead,soft,revived,semi-revived --threads 50 --timeout 5 --probes 2 --geo false
```

3. Check Stats / Ready chips.

## 5. What makes a proxy usable?

### HTTP proxy

A plain HTTP proxy can usually proxy:

- HTTP websites directly.
- HTTPS websites via the `CONNECT` method if implemented correctly.

It should not be treated as web-ready unless `web_https_ok=True`.

### HTTPS proxy label

Some lists label a proxy as `https`, but it is actually a normal HTTP proxy that supports HTTPS `CONNECT` tunnels. Phase 8A detects this and can reclassify `https` → `http` when only fallback works.

### SOCKS4 / SOCKS4A

- `socks4` usually needs local DNS resolution.
- `socks4a` supports remote DNS.
- `remote_dns_ok=True` means remote DNS behavior worked.

### SOCKS5 / SOCKS5H

- `socks5` may resolve DNS locally.
- `socks5h` resolves DNS through the proxy.
- For privacy/leak-sensitive use cases, prefer `remote_dns_ok=True`.

### Telegram

Telegram-ready means HTTPS web validation plus a Telegram API reachability check. Use the Telegram server preset.

## 6. Server profile presets

Use dashboard preset unless you need CLI.

### Web browsing

```bash
python3 proxy_server/app.py --protocol http --listen_port 8080 --candidate_statuses alive --require_web_https --rotate better_cost
```

### Telegram

```bash
python3 proxy_server/app.py --protocol socks5 --listen_port 1080 --candidate_statuses alive --require_web_https --require_remote_dns --require_telegram --rotate better_cost
```

### Scraping / HTTP-only

```bash
python3 proxy_server/app.py --protocol http --listen_port 8080 --candidate_statuses alive --rotate better_cost
```

## 7. Smoke tests

Dashboard:

```bash
curl -I http://127.0.0.1:5003/login
```

Proxy server:

```bash
curl -x http://127.0.0.1:8080 https://api.ipify.org
```

DB import health:

```bash
export DB_TYPE=sqlite
python3 - <<'PY'
from database import db, Proxy
with db.session() as s:
    print('proxy_count', s.query(Proxy).count())
PY
```

## 8. Production preparation checklist

Before any production deployment:

- [ ] Explicitly approve deployment target and method.
- [ ] Create `.env` with strong secrets.
- [ ] Decide SQLite vs MySQL.
- [ ] If MySQL, set `DB_TYPE=mysql` explicitly and test connectivity.
- [ ] Put dashboard behind a proper WSGI server / reverse proxy.
- [ ] Enforce TLS at the reverse proxy.
- [ ] Change dashboard/admin credentials.
- [ ] Back up database.
- [ ] Run health checks.
- [ ] Run monitor and verify capability stats.
- [ ] Use server profile presets instead of broad unfiltered proxy serving.

## 9. Troubleshooting

### App tries to connect to MySQL locally

Check:

```bash
echo $DB_TYPE
```

Fix:

```bash
export DB_TYPE=sqlite
export SQLITE_DB_PATH=proxies.db
```

Or ensure no `.env` overrides `DB_TYPE=mysql`.

### `alive` count drops after Phase 8A

Expected. Validation is stricter. The goal is fewer fake-alive proxies and more real-world usability.

### Many `revived` rows with all capabilities false

They are legacy rows. Run Normalize + re-monitor.

### HTTPS site fails through an HTTP proxy

HTTP proxy must support `CONNECT`. Only trust it for HTTPS sites if `web_https_ok=True`.

## 10. Repository hygiene

Runtime files should not be committed. Before committing a phase, run:

```bash
./scripts/clean_runtime.sh
./scripts/repo_hygiene_check.sh
```

If `repo_hygiene_check.sh` reports tracked runtime artifacts, remove them from git tracking with `git rm --cached` as shown by the script. This keeps local files on disk while preventing future commits of DB/log/progress/cache files.
