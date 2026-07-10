# Inventory workspace

Phase 5 replaces the legacy proxy table with a focused inventory workspace. The page is designed for routine inspection and bulk operations without exposing upstream credentials or displaying every database field at once.

## Information architecture

The default table contains only fields needed for operational decisions:

- proxy endpoint and protocol;
- current health state;
- measured latency;
- key capabilities;
- location or network context;
- last validation time;
- row selection and actions.

Full metadata is available in a detail drawer. This keeps the table compact while retaining access to validation history, network attributes, capability results, quality signals, and raw validation details.

## Filtering and selection

Inventory state is kept in the dedicated `static/js/inventory.js` module. Available controls include:

- text search;
- protocol filter;
- grouped health filter;
- capability filters for HTTPS, remote DNS, and Telegram;
- deterministic sort options;
- configurable page size;
- selection of visible rows;
- copy, test, delete, and export actions.

Selection is explicit and page-scoped. Destructive bulk deletion requires confirmation and is capped at 500 IDs per request.

## API additions

- `GET /api/proxies/<id>` returns one proxy after applying the current user's proxy scope. Upstream usernames and passwords are never included.
- `POST /api/proxies/selection/delete` deletes only IDs visible within the current user's scope and rejects invalid or unbounded selections.
- `GET /api/export` accepts comma-separated status groups and capability filters so an export can match the visible workspace.

These routes use the existing permission, CSRF, redaction, and proxy-scope boundaries introduced in the security phase.

## Module boundary

The redesigned Inventory uses:

- `templates/pages/inventory.html` for semantic structure;
- `static/css/inventory.css` for responsive layout and drawer behavior;
- `static/js/inventory.js` for state, rendering, selection, and actions.

Some shared proxy mutation dialogs still live in `base.js` and `partials/modals.html`. They remain temporarily shared so Add, Edit, Test, and Bulk Add continue to use the established API contracts. They can be extracted after the remaining workspaces are migrated.

## Responsive behavior

On narrow screens, secondary columns are progressively hidden, toolbar controls wrap, the selection bar remains usable, and the detail drawer occupies the available viewport. No backend behavior changes based on screen size.

## No deployment side effects

Applying this overlay updates source files and tests only. It does not migrate the database, start or restart a listener, create a monitor, modify systemd, commit changes, or deploy the application.
