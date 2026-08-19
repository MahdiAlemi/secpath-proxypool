# SecProxy CLI

`secproxy` is the local operator interface for SecPath ProxyPool. The dashboard and
CLI share the same core service layer for monitor/server lifecycle operations.

## Supported installation model

SecPath ProxyPool keeps operational state beside the checkout: `.env`, the default
SQLite database, saved monitor/server profiles, logs, runtime claims, and backups.
For that reason the supported operator installation is **editable from the checkout**.

### Existing virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-dev.txt
python3 -m pip install -e . --no-deps
secproxy --version
```

### pipx-managed CLI environment

From the repository root:

```bash
pipx install --editable .
secproxy --version
```

Use editable mode so the command continues to use this checkout as its application
source/state root. A wheel is built by release checks to validate packaging metadata,
but the wheel is not yet the recommended relocatable deployment format for the
stateful control plane.

## Global options

```text
--json       machine-readable output
--no-color   disable Rich colors
--verbose    include additional error detail
--version    print project/CLI version
```

Global options precede the command:

```bash
secproxy --json status
secproxy --json proxy list
```

## Command tree

```text
secproxy
├── status
├── doctor
├── config
│   ├── show
│   ├── path
│   └── check
├── proxy
│   ├── list
│   ├── show
│   ├── count
│   ├── add
│   ├── edit
│   ├── delete
│   ├── purge
│   ├── test
│   └── export
├── source
│   ├── list
│   ├── show
│   ├── add
│   ├── enable
│   ├── disable
│   ├── delete
│   ├── preview
│   ├── import
│   ├── run
│   └── history
├── monitor
│   ├── list
│   ├── show
│   ├── status
│   ├── preview
│   ├── create
│   ├── edit
│   ├── start
│   ├── pause
│   ├── resume
│   ├── stop
│   ├── restart
│   ├── delete
│   ├── remove-service
│   ├── results
│   ├── logs
│   └── watch
├── server
│   ├── list
│   ├── show
│   ├── status
│   ├── preview
│   ├── create
│   ├── edit
│   ├── start
│   ├── stop
│   ├── restart
│   ├── delete
│   ├── logs
│   └── test
├── insights
│   ├── summary
│   ├── health
│   ├── protocols
│   ├── capabilities
│   ├── latency
│   ├── countries
│   └── providers
├── backup
│   ├── create
│   ├── list
│   ├── verify
│   ├── restore
│   └── delete
├── cleanup
│   ├── logs
│   └── runtime
└── user
    ├── schema
    ├── list
    ├── show
    ├── create
    ├── enable
    ├── disable
    ├── role
    ├── passwd
    └── delete
```

## Safety contracts

### Proxy credentials

Normal output and JSON never include stored proxy passwords. Prefer hidden input:

```bash
secproxy proxy add socks5 203.0.113.10 1080 \
  --username operator \
  --password-prompt
```

For automation, use one-line stdin:

```bash
printf '%s\n' "$PROXY_PASSWORD" |
  secproxy proxy add socks5 203.0.113.10 1080 \
    --username operator \
    --password-stdin
```

Credential export is intentionally gated:

```bash
secproxy proxy export \
  --include-credentials \
  --output ~/private-proxies.txt \
  --yes
```

Credential export to stdout is refused and export files are written mode `0600`.

### Bulk deletion

`proxy purge` is a preview unless `--yes` is supplied, and at least one filter is
required:

```bash
secproxy proxy purge --status dead
secproxy proxy purge --status dead --max-delete 5000 --yes
```

### Ad-hoc proxy diagnostics

`proxy test` does not update health state. The monitor is authoritative for health:

```bash
secproxy proxy test 42 --connect-timeout 2 --timeout 5
echo $?
```

A failed proxy test exits `6`.

### Listener exposure

Loopback is the safe default. A non-loopback listener without authentication is
rejected unless the explicit public-no-auth override is configured.

### Restore and cleanup

Backup restore verifies SQLite integrity, refuses known active SecProxy runtimes, and
creates a pre-restore safety backup. Cleanup is preview-first.

## Release checks

Run the SecProxy-specific checks:

```bash
bash scripts/check_secproxy_cli.sh
```

This compiles the CLI/core, runs critical Ruff rules, executes all
`tests/test_secproxy*.py`, builds a wheel in a temporary directory, and verifies:

- `secproxy` console entry point;
- `secproxy_cli` and `secproxy_core` are in the wheel;
- runtime dependency metadata exists;
- local `.env`, database, and runtime profile files are not packaged.

The repository-wide release check remains:

```bash
bash scripts/release_check.sh
```
