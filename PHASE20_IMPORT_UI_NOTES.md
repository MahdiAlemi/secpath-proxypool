# Phase 20 – Import / Source Center UI Refinement

Turns the Import tab into a clearer source center for raw proxy ingestion.

## Added

- Renamed import section to **Source Center**.
- Source mode cards for Single URL, Source config, and Manual batch.
- Import checklist / guidance strip.
- Dynamic mode summary for selected import mode.
- Safer `showImportTab(tab, event)` behavior that does not rely on global `event`.
- Styled import panels and importing result state.
- Regression test for import source center shell rendering.

## Scope

No schema changes and no import API contract changes. UI-only import refinement.
