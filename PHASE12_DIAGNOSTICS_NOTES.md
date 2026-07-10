# Phase 12 – Dashboard Diagnostics / Preflight

Adds an operator-facing diagnostics snapshot inside Settings.

## Added

- `GET /api/settings/diagnostics`
  - DB type/path/SQLite size
  - proxy counts
  - capability counts: web-ready, DNS-ready, Telegram-ready, full-capability
  - legacy revived count
  - runtime state/progress file counts
  - actionable recommendations
- Settings modal UI section: **Diagnostics / Preflight**
  - refresh button
  - cards for DB/proxy/capability state
  - recommendation list
- Regression test for diagnostics endpoint response shape.

## Why

This makes it easier to decide the next operational step without running manual SQL:
Normalize legacy statuses, run monitor, use capability filters, or clean runtime files.

No schema changes.
