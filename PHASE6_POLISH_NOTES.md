# Phase 6: Cleanup and product polish

Changes:
- Added Settings cleanup actions:
  - Clear Logs: deletes dashboard/server/monitor log files.
  - Clear Runtime Files: deletes stale `.monitors.json`, `.servers.json`, PID files, and progress state without deleting the database.
  - Normalize Legacy Statuses: converts old pre-Phase-5 `revived` records into `dead` or `soft` based on whether they ever succeeded.
- Settings now reports SQLite database path and size more reliably.
- Backup import file picker now accepts `.sqlite` as well as `.sql`.
- Server UI now exposes `Candidate Statuses` so you can choose `alive` for production or `alive,soft` for dev/testing.
- Server cards now show the configured candidate statuses.

Apply:
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase6_polish.zip -d .
```

Test:
```bash
export DB_TYPE=sqlite
python3 -m compileall -q dashboard
python3 dashboard/app.py
```

Suggested commit:
```bash
git add .
git commit -m "Phase 6: Add cleanup tools and server candidate status UI"
```
