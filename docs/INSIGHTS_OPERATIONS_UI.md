# Insights, Operations, and Access

Phase 9 replaces the remaining dense statistics and modal-based administration surfaces with three dedicated workspaces. The phase does not deploy the application, start services, or alter proxy records merely by applying the overlay.

## Insights

The Insights page is a decision-oriented view of the proxy inventory. It uses the existing scoped `/api/stats` endpoint, enriched with:

- stable, unstable, unavailable, and pending quality groups;
- success and capability coverage rates;
- validation freshness bands;
- latency and reliability bands for alive proxies;
- per-protocol alive rates;
- country and provider concentration signals.

All counts honor the current user's proxy scope. The browser renders text and CSS bars; no third-party charting library is required.

## Operations

Operations is a real page rather than a settings modal. It combines:

- database and runtime preflight;
- security posture without returning secret values;
- backup creation, listing, bounded named download, and restore;
- password rotation;
- log cleanup, runtime cleanup, and legacy-status normalization;
- destructive group deletion with an explicit danger zone.

Mutation controls are disabled for view-only users. The API remains authoritative and enforces `settings.edit`, `proxies.credentials`, and `proxies.delete` independently.

### Runtime cleanup safety

Runtime cleanup is conservative. It inspects both configured profiles and process-claim files under `.runtime/` before removing state. Cleanup is rejected while a managed or orphaned monitor/server process is running or has a fresh start reservation. Invalid runtime identifiers also block cleanup until the registry is repaired.

The cleanup operation removes stale PID files and the `progress/` and `.runtime/` directories. It does not delete monitor or server profile registries.

### Backups

Named backup downloads accept only project-root files matching:

```text
proxies_backup_*.sqlite
proxies_backup_*.sql
```

Credential-bearing backup downloads require both `settings.edit` and `proxies.credentials`. SQLite restore validates file size, magic bytes, integrity, and the presence of the `proxies` table before replacement.

## Access control

Access is a dedicated user directory and detail workspace. It displays:

- active state and role;
- effective permissions;
- proxy status/protocol scope;
- token/session count;
- creation and last-login timestamps.

The editor supports database-backed account creation, username and password changes, role defaults, permission overrides, proxy scope, and activation state. Password hashes and token values are never returned.

The backend prevents self-deactivation, self-demotion, self-deletion, and deletion or demotion of the final active administrator. Password changes and deactivation revoke API tokens.

## API additions and changes

- `GET /api/stats` returns quality, freshness, latency, reliability, protocol-rate, and concentration sections.
- `GET /api/settings/diagnostics` returns bounded database, runtime, backup, access, and security state.
- `GET /api/settings/backups/<name>` downloads one validated backup.
- `GET /api/users/<id>` returns a redacted user detail record.
- `GET /api/users` includes effective permissions, token count, proxy scope, and current-account state.

## Frontend modules

```text
dashboard/static/css/insights.css
dashboard/static/css/operations.css
dashboard/static/js/insights.js
dashboard/static/js/operations.js
dashboard/static/js/access.js
dashboard/templates/pages/stats.html
dashboard/templates/pages/operations.html
dashboard/templates/pages/users.html
```

## Verification boundary

The automated suite verifies scoped statistics, non-secret diagnostics, runtime cleanup guards, orphan process detection, backup name validation, enriched user serialization, and final-administrator protection. Browser screenshots are still a local review step because automated Chromium access may be blocked by the execution environment.
