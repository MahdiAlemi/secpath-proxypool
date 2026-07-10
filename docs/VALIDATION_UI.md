# Validation workspace

Phase 7 replaces the legacy monitor card grid and inline modal with a focused validation workspace. The monitor lifecycle introduced in Phase 2 is unchanged; this phase presents that lifecycle through a safer and more useful operator interface.

## Workspace structure

The page is split into two progressive-disclosure regions:

- a searchable profile rail with runtime state and configured target counts;
- a selected-profile detail surface with live progress, targeting rules, process state, recent results, and log output.

The browser refreshes monitor state only while the Validation tab is visible. Profile configuration and display logic live in `dashboard/static/js/validation.js`; the large legacy monitor block has been removed from `base.js`.

## Candidate preview

`POST /api/monitor/preview` validates a proposed profile and returns a non-mutating candidate snapshot:

- total matching proxies;
- protocol and status mix;
- HTTPS, remote-DNS, and Telegram capability counts;
- a small credential-free sample.

Preview uses the same profile normalization and candidate query as execution. It does not create a monitor record, process claim, progress file, or database session.

## Latest session results

`GET /api/monitor/<monitor_id>/results` returns up to 100 recent proxies recorded in `monitor_tested` for the profile's current/latest session. The response includes operational fields only and never returns upstream usernames or passwords.

The result list is intentionally a latest-session view. Historical retention across multiple runs remains outside this phase because the current database model stores one resumable session per profile.

## Profile editor

The editor groups configuration into identity, candidate scope, probe strategy, and execution policy. It provides an asynchronous candidate preview before save and preserves all existing backend constraints:

- 1–200 threads;
- 1–60 second timeout;
- 1–5 probes;
- validated public check URLs;
- supported protocol and status values;
- bounded schedule and interval settings;
- explicit systemd service creation.

Profiles cannot be edited while running or paused, matching the lifecycle API contract.

## Security and operational boundaries

All monitor APIs remain protected by browser login, CSRF for mutation, and `monitor.view` or `monitor.control` permissions. Preview and result endpoints are read/non-mutating and redact proxy credentials. Applying this overlay does not start a monitor, create a service, restart a process, or deploy anything.
