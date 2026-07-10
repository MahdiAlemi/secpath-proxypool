# SecPath ProxyPool baseline audit

Audit scope: repository structure, Flask/API behavior, fresh-database startup, monitor lifecycle, proxy listener behavior, UI architecture, test coverage, and repository hygiene.

This document replaces the repository's accumulated `PHASE*_NOTES.md` files. It records verified issues and the rebuild order without treating previous phase labels as requirements.

## Verified baseline

- Python source compilation succeeds.
- The existing JavaScript bundle passes `node --check`.
- The original automated suite passes when tables are initialized first.
- A fresh database fails on the original code because application startup upgrades an existing `proxies` table but does not create missing tables.
- The delete-user endpoint crashes on the original code because a SQLAlchemy session shadows Flask's browser session.
- The existing tests are predominantly helper and HTML-marker tests; they do not provide sufficient integration coverage for process lifecycle, permissions, protocol handling, or security boundaries.

## Critical and high-priority findings

### Application and data

1. Fresh-install database initialization is broken in the original baseline.
2. Browser state-changing endpoints have no systematic CSRF protection.
3. Development fallback credentials and a fallback JWT secret are present in code.
4. Token cleanup performs a database write transaction on every request.
5. API errors frequently return raw exception and SQL details, often with HTTP 200.
6. Proxy serialization includes upstream usernames and passwords for broad read endpoints.
7. Database schema changes use ad-hoc additive SQL without schema versioning.
8. Live SQLite backup/restore paths are not consistently atomic or connection-safe.
9. Proxy visibility filters are applied to list views but not consistently to export, update, delete, bulk delete, and test actions.
10. URL imports can request arbitrary HTTP/HTTPS targets, creating an SSRF boundary.

### Proxy server

1. The default listener can bind to all interfaces without authentication, creating an open-proxy risk.
2. Listener credentials are passed on the process command line and stored as plaintext runtime state.
3. Sticky rotation is exposed but does not select a proxy in the original implementation.
4. String boolean filters treat `"false"` as true in runtime selection.
5. Listener authentication and upstream-auth filtering use overlapping, confusing configuration names.
6. HTTPS upstream connection handling uses incorrect TLS/SNI assumptions.
7. SOCKS handlers assume one `recv()` call returns every requested byte.
8. A new unbounded thread is created per connection.
9. PID-only process control can target an unrelated process after PID reuse.
10. Runtime health updates do not consistently update the monitor state machine fields.

### Monitor

1. The stop flag is imported by value, so signal-driven graceful shutdown does not propagate reliably.
2. Dashboard stop/pause actions use immediate hard termination.
3. Service creation can launch both a direct process and a system service, producing duplicate monitors.
4. Service management writes privileged systemd configuration from the dashboard path.
5. Zero probes or zero threads can produce invalid classifications or misleading completion.
6. Configured schedule days and check URLs are not consistently honored.
7. Infinite mode can overlap worker batches and bypass normal state transitions.
8. Final progress can report all items tested even when work did not complete.
9. Runtime JSON files are written without atomic replace/locking.
10. Monitor log/profile identifiers need stricter path and ownership validation.

### Dashboard and frontend

1. The current dashboard is a monolith: all major screens and dialogs are rendered into one document.
2. `main.html` is over one thousand lines and `base.js` is a very large global script.
3. The template contains extensive inline styles and inline event handlers.
4. Inventory exposes too many columns simultaneously and lacks task-oriented information hierarchy.
5. Multiple unescaped `innerHTML` and inline-handler paths can turn imported proxy/source/log data into stored XSS.
6. Strict Content Security Policy adoption is blocked by inline scripts and handlers.
7. Semantic forms, keyboard behavior, focus management, and accessibility states are weak.
8. Navigation markup contains malformed class expressions in the original template.
9. UI state, API calls, rendering, and domain logic are tightly coupled in one JavaScript namespace.
10. The current UI should be replaced with a modular application shell and task-specific pages, not cosmetically restyled.

### Repository

1. The repository tracks `proxies.db`, runtime JSON, progress snapshots, and duplicate dashboard state.
2. Logs and Python caches are present in the delivered archive.
3. More than twenty historical phase-note files obscure the active engineering baseline.
4. Temporary patch scripts are tracked.
5. Documentation references an incorrect path casing and obsolete phase-oriented instructions.
6. Many source files are marked executable in Git even though only scripts need execute permission.

## Rebuild sequence

### Foundation

- Clean tracked runtime artifacts without deleting the local active database/state.
- Make fresh database startup deterministic.
- Isolate automated tests from the real database.
- Add regression tests for confirmed baseline failures.
- Replace phase-note sprawl with this audit and an operational runbook.

### Security and API contracts

- Remove unsafe credential fallbacks and fail clearly on insecure production configuration.
- Add CSRF, rate limits, session hardening, consistent error envelopes, and request validation.
- Define redacted/public versus privileged proxy serializers.
- Centralize user-scoped query filters for every read and mutation.
- Block SSRF and unsafe import targets.
- Introduce versioned database migrations and safe backup/restore.

### Monitor correctness

- Rebuild stop/pause/resume semantics around cooperative cancellation.
- Validate all numeric/configuration bounds.
- Make state/progress writes atomic.
- Prevent overlapping runs and duplicate service processes.
- Separate privileged service management from the web application.
- Add deterministic lifecycle tests.

### Proxy server correctness

- Default to loopback and require explicit public binding.
- Correct rotation, filter parsing, upstream TLS, SOCKS framing, and health accounting.
- Replace unbounded connection threads with bounded concurrency.
- Harden process ownership and secret handling.
- Add protocol-level integration tests with local fixtures.

### New dashboard

- Build a new shell, navigation model, design tokens, and reusable components.
- Split pages and JavaScript modules by domain.
- Use safe DOM APIs and prepare for a strict CSP.
- Redesign inventory/import, monitoring, serving, insights, settings, and users as focused workflows.
- Add responsive behavior, empty/loading/error states, keyboard navigation, and accessible dialogs.

### Final integration

- Run end-to-end local tests for import → validation → serving.
- Add backup/restore and permission regression suites.
- Document upgrade and rollback procedures.
- Deployment remains a separate, explicitly approved activity.
