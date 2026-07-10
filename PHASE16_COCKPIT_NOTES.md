# Phase 16 – Dashboard Cockpit / Overview

Adds a product-style overview tab that brings readiness, diagnostics, runtime status, and next actions into one place.

## Added

- New **Cockpit** nav item / tab.
- Cockpit cards for:
  - DB type/size
  - total proxies
  - alive count
  - web readiness percentage
  - Web-ready / Telegram-ready / Full-capability
  - legacy revived count
  - server profile / running server counts
  - progress files and last scan
- Next-action list based on diagnostics and readiness.
- Shortcut actions to Import, Monitor, Inventory, Server Builder, and Diagnostics.
- Regression test that `/index?tab=cockpit` renders the cockpit markup.

## Scope

No schema changes. Uses existing `/api/stats`, `/api/settings/diagnostics`, and `/api/server` APIs.
