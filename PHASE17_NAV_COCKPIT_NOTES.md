# Phase 17 – Navigation Hardening & Cockpit Default

## Added

- Cockpit is now the default landing screen for `/` and `/index`.
- Added Cockpit to the main navigation.
- Hardened `showTab()`:
  - clicking nested `span` / `small` inside nav buttons works correctly
  - programmatic calls no longer depend on a global browser `event`
  - missing tab elements are handled safely
- Added regression test for default `/` landing on Cockpit.

## Scope

No schema changes. This is UI/navigation hardening only.
