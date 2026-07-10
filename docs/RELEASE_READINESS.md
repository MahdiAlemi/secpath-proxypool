# Release readiness without deployment

This phase prepares a reviewable local release candidate. It does not deploy,
start services, modify a remote machine, or authorize production changes.

## One-command verification

Activate the project virtual environment, then run:

```bash
bash scripts/release_check.sh
```

The command uses disposable SQLite databases and verifies:

- required Python distributions are installed;
- the full health and regression suite passes;
- repository hygiene and Ruff checks pass;
- a credential-bearing SQLite backup is created with mode `0600`;
- that backup can be validated and restored to a disposable destination;
- the migration CLI is dry-run by default and can migrate current Proxy fields;
- Git contains no whitespace errors.

After committing an approved overlay, require a clean tree with:

```bash
bash scripts/release_check.sh --require-clean
```

## Private SQLite backup CLI

Create a transactionally consistent backup:

```bash
python3 scripts/sqlite_backup.py backup \
  --source proxies.db \
  --directory backups
```

Validate a backup without modifying the active database:

```bash
python3 scripts/sqlite_backup.py verify backups/proxies_backup_*.sqlite
```

Restore is intentionally explicit and creates a pre-restore backup when the
destination already exists:

```bash
python3 scripts/sqlite_backup.py restore \
  backups/proxies_backup_<timestamp>.sqlite \
  --destination proxies.db \
  --backup-directory backups \
  --yes
```

Stop database writers before a manual restore. The Dashboard restore workflow
also disposes SQLAlchemy connections before replacing the SQLite file.

All generated backup files contain upstream proxy credentials and therefore use
mode `0600`. Backup names include UTC microseconds plus a random suffix, so two
operations in the same second cannot overwrite one another.

## SQLite-to-MySQL proxy migration

`migrate.py` migrates Proxy records only. It does not migrate users, tokens,
monitor sessions, or import audit records.

A target URL is mandatory. The default action is a non-writing dry-run:

```bash
python3 migrate.py \
  --source proxies.db \
  --target-url 'mysql+pymysql://USER:PASSWORD@HOST:3306/proxypool'
```

Execute only after reviewing the dry-run:

```bash
python3 migrate.py \
  --source proxies.db \
  --target-url 'mysql+pymysql://USER:PASSWORD@HOST:3306/proxypool' \
  --execute
```

Existing proxy identities are skipped. A destructive replacement of target
Proxy rows requires both flags:

```bash
python3 migrate.py \
  --source proxies.db \
  --target-url "$MIGRATION_TARGET_URL" \
  --replace --yes-replace --execute
```

The target URL is printed with its password redacted. Do not place a database
password directly in shared shell history; prefer `MIGRATION_TARGET_URL` in the
local, untracked `.env` or an ephemeral environment variable.

## Development tooling

Install runtime and verification tools into the project virtual environment:

```bash
python3 -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the runtime requirements and the Ruff version
range used by this repository. `pyproject.toml` contains the shared Ruff
configuration.

## Release boundary

A passing release check means the local source tree, disposable backup/restore
flow, migration path, and automated tests are consistent. It is not production
approval. Deployment still requires a separate explicit instruction, reviewed
runtime architecture, TLS/reverse-proxy decisions, service ownership, backup
retention, and rollback procedures.
