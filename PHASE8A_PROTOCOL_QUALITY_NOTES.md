# Phase 8A: Protocol Quality Audit

Goal: make `alive` mean real-world usable web HTTPS validation, not just a non-empty curl response.

## What changed

### Validation engine
- Added `proxy_monitor/utils/validation.py`.
- Validates output from `https://api.ipify.org` as a real IP address.
- No longer treats arbitrary non-empty HTML/error bodies as success.
- Tests HTTP target reachability through `http://api.ipify.org`.
- Tests Telegram reachability through `https://api.telegram.org`.
- For SOCKS5, tries `socks5h` first to validate proxy-side DNS, then falls back to `socks5`.
- For SOCKS4, tries `socks4a` first, then falls back to `socks4`.
- For proxies imported as `https`, tries real `https://proxy` first, then detects common public-list behavior where "https" actually means HTTP CONNECT support.

### Database capabilities
Added additive schema columns:
- `web_http_ok`
- `web_https_ok`
- `remote_dns_ok`
- `telegram_ok`
- `exit_ip`
- `validation_profile`
- `validation_summary`

The dashboard startup and `init_db()` now apply these additive schema upgrades automatically.

### Monitor behavior
- Monitor now uses the new validation engine.
- A proxy only becomes fully `alive` after all probes validate HTTPS + real exit IP.
- Monitor logs include exit IP, remote DNS status, and Telegram status.
- Mislabelled `https` proxies that only work as HTTP CONNECT are reclassified to `http`.

### Server candidate quality filters
- Added server flags:
  - `--require_web_https`
  - `--require_remote_dns`
  - `--require_telegram`
- Dashboard server UI now exposes these filters.
- Default server UI requires HTTPS OK for production-quality candidates.

### UI
- Proxy table shows:
  - HTTPS OK
  - Remote DNS
  - Telegram
  - Exit IP
- Manual proxy Test now runs the quality validation and shows a short capability summary.

### Importer
- URL-format proxies now preserve credentials:
  - `protocol://user:pass@ip:port`
- Dashboard bulk import now uses the same parser.

## Apply
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase8a_protocol_quality.zip -d .
```

## Test
```bash
export DB_TYPE=sqlite
python3 -m compileall -q dashboard proxy_monitor proxy_importer proxy_server database.py
python3 -c "from database import init_db; init_db()"
python3 dashboard/app.py
```

Then run a fresh monitor on a small subset first, for example:
- Status: `alive,soft` or `untested`
- Threads: `20`
- Timeout: `8`
- Probes: `2`
- Geo: `false` for first quality test

Suggested commit:
```bash
git add .
git commit -m "Phase 8A: Add protocol quality validation"
```
