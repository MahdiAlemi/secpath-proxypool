# Phase 8B.1 – SQLite Default Hotfix

Problem found during local WSL test: when no `.env` / `DB_TYPE` is set, the app fell back to MySQL and failed with `Can't connect to MySQL server on localhost`.

Fix:
- `config.py` now defaults to `DB_TYPE=sqlite` for local/dev runs.
- Production MySQL remains supported, but must be explicit: `DB_TYPE=mysql`.
- Removed duplicate `DB_TYPE` assignment in `config.py`.
- Settings routes now read DB type/path from the central `config` object instead of separately defaulting to MySQL.
- `.env.example` now shows `DB_TYPE=sqlite` as the local default.

No schema changes.
