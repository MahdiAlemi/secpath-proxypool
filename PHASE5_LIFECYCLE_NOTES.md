# Phase 5: Monitor lifecycle and state-machine cleanup

Fixes:
- Monitor state machine now classifies first scan results correctly:
  - `untested +2 => alive`
  - `untested +1-1 => soft`
  - `untested -2 => dead`
- Previously, `untested +2` became `flaky` and `untested -2` became `revived`, which made first-run results confusing.
- Completed one-shot monitors now clear their PID in `.monitors.json` and set `end_time`, so the UI should stop showing completed monitors as Running.
- If a monitor has no remaining proxies to test, it now writes a completed progress state and clears the PID.
- Proxy server now supports configurable candidate statuses via `--candidate_statuses` while defaulting to `alive` for production safety.
- Dashboard server start forwards `candidate_statuses` if present in a server profile config.

Apply:
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase5_lifecycle.zip -d .
```

Test:
```bash
export DB_TYPE=sqlite
python3 -m compileall -q proxy_monitor proxy_server dashboard
python3 dashboard/app.py
```

Suggested commit:
```bash
git add .
git commit -m "Phase 5: Fix monitor lifecycle and state transitions"
```
