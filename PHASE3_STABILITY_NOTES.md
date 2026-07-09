# Phase 3: Stability, permissions, backup/import hardening

Changes:
- `/api/stats` now requires the `stats.view` permission instead of only login.
- Settings API now reports the real `DB_TYPE` and SQLite path.
- Admin password change now warns that the change is in-memory only and `.env` should be updated for persistence.
- Backup now supports SQLite (`.sqlite`) as well as MySQL (`.sql`).
- MySQL backup/import no longer passes DB password via command-line argv; it uses `MYSQL_PWD` in the subprocess environment.
- SQLite import no longer executes arbitrary uploaded SQL. It only supports full `.sqlite` backup replacement.
- Import URL counter validates URLs and only allows `http`/`https`.
- Import URL counter limits downloaded response text to 2 MB and checks HTTP errors.
- Importer subprocess now uses the current Python interpreter instead of hard-coded `python3`.

Apply:
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase3_stability.zip -d .
```

Test:
```bash
export DB_TYPE=sqlite
python3 -m compileall -q dashboard proxy_server proxy_monitor
python3 dashboard/app.py
```

Suggested commit:
```bash
git add .
git commit -m "Phase 3: Harden backup import and permissions"
```
