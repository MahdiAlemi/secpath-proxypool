# Phase 15 – Server Builder Wizard

Makes server creation more interactive without changing the existing server create/start API contract.

## Added

- Wizard controls in the server modal:
  1. Use case / listener
  2. Routing / auth / TLS
  3. Geo & network filters
  4. Review / preflight
- Review panel that summarizes the generated profile before creation.
- `POST /api/server/preview-candidates`
  - counts matching proxies for the chosen profile
  - breaks matches down by protocol
  - returns sample candidates
  - returns warnings for zero candidates or risky presets
- Frontend preflight refresh in the review step.
- Regression test for the preview endpoint shape.

## Scope

No schema changes. Existing server create/update/start payloads remain compatible.
