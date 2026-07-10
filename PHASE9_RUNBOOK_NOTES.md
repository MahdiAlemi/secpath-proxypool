# Phase 9 – Documentation & Operational Runbook

This phase does not change runtime behavior. It adds product-facing and operator-facing documentation plus safe local helper scripts.

## Added / updated

- `README.md` rewritten as a real project guide.
- `RUNBOOK.md` added for development, SQLite operations, monitoring, server presets, smoke tests, production checklist, and troubleshooting.
- `scripts/dev_setup.sh` initializes local SQLite development environment.
- `scripts/run_dashboard.sh` starts the dashboard with SQLite defaults.
- `scripts/run_monitor_once.sh` runs a targeted one-shot monitor with environment-overridable filters.
- `scripts/health_check.sh` runs Python compile checks, JS syntax check, DB config smoke, dashboard app import, and validation helper smoke tests.

## No deployment

This phase intentionally does not deploy, install services, or change runtime process managers.
