# Phase 17.1 – Restore Cockpit after Navigation Hardening

Fixes the Phase 17 overlay regression that removed parts of the Phase 16 Cockpit UI.

## Fixed

- Restored Cockpit tab markup.
- Restored Cockpit frontend data loader and helper renderers.
- Restored Cockpit CSS layout rules.
- Kept Phase 17 behavior:
  - `/` defaults to Cockpit
  - `showTab(tab, event)` hardened navigation
- Restored/kept regression coverage for Cockpit route and default landing.

## Scope

No schema changes. UI regression fix only.
