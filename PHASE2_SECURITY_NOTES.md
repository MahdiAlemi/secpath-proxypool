# Phase 2: Secure process execution and logging

Changes:
- Removed shell-based start commands for proxy server and monitor.
- Replaced `bash -c` / command string execution with `subprocess.Popen([...], shell=False)`.
- Removed unsafe `pkill -f` usage from server start.
- Monitor start/resume now writes real per-monitor log files (`<monitor_id>.log`) instead of redirecting to `/dev/null`.
- Server start now uses the current Python interpreter and writes to `server_<port>.log`.
- Added `--readonly` parser support in `proxy_server/config.py`.
- Fixed dashboard `--insecure_upstream` flag spelling to match the parser.
- Made JWT secret stable in dev by falling back to `FLASK_SECRET_KEY` before a dev placeholder.
- Updated `.env.example` with `DB_TYPE`, `DASHBOARD_PASSWORD`, and `JWT_SECRET`.
- Kept missing Python dependencies in `requirements.txt`.

Apply:
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase2_security.zip -d .
```

Test:
```bash
export DB_TYPE=sqlite
python3 -m compileall -q dashboard proxy_server proxy_monitor
python3 dashboard/app.py
```
