# Phase 11 – Repository Hygiene

Adds guardrails so local runtime artifacts do not keep getting committed.

## Added

- Expanded `.gitignore` for:
  - Python caches
  - local env/secrets
  - logs/pids
  - dashboard/server/monitor runtime state
  - SQLite DB/backups
  - progress JSON files
  - generated archives/overlays
- `scripts/clean_runtime.sh`
  - removes caches/logs by default
  - optional `--include-state` for dashboard/server/progress runtime JSON
  - optional `--include-db` for local SQLite DB/backups
- `scripts/repo_hygiene_check.sh`
  - detects runtime/cache artifacts that are already tracked by git
  - prints safe `git rm --cached` cleanup commands
- README/RUNBOOK notes for hygiene workflow

## Important

`.gitignore` only prevents new untracked files from being added. If runtime files
were already committed, run `scripts/repo_hygiene_check.sh` and follow its
`git rm --cached` instructions. That removes them from git tracking without
deleting local files.

No runtime behavior changes.
