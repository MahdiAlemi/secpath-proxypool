# Phase 21 – Stats / Insights Center UI Refinement

Turns the Stats tab into a clearer insights center for quality and readiness analytics.

## Added

- Product-style Insights Center header.
- Quick actions to refresh validation and build a server.
- Readiness insight cards:
  - Web readiness percentage
  - Telegram readiness percentage
  - Full capability percentage
  - Quality note / recommendation
- Stats summary strip for total, alive, dead, untested, and capability counts.
- Frontend readiness calculator based on existing `/api/stats` data.
- Regression test for stats insights shell rendering.

## Scope

No schema changes and no stats API contract changes. UI-only stats refinement.
