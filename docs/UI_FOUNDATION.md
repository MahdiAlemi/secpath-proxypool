# UI foundation

Phase 4 replaces the old horizontal dashboard with a new application shell and a modular template structure. It does not change the stabilized proxy, monitor, importer, or server APIs.

## Design principles

- Keep primary navigation persistent and predictable.
- Show one operational objective per screen.
- Prefer progressive disclosure over large always-visible forms.
- Make system state, active runtimes, and risk visible without opening settings.
- Keep destructive actions away from routine workflow controls.
- Support keyboard focus, responsive navigation, light/dark appearance, and reduced visual noise.

## Structure

- `templates/main.html`: application composition only.
- `templates/pages/`: one template per main workspace.
- `templates/partials/`: shared modal surfaces.
- `static/css/tokens.css`: design tokens and theme variables.
- `static/css/base.css`: shared controls, tables, forms, and modals.
- `static/css/shell.css`: sidebar, top bar, responsive navigation.
- `static/css/pages.css`: Cockpit and transitional page layout.
- `static/css/compat.css`: temporary compatibility rules for modules that have not yet been redesigned.
- `static/js/shell.js`: navigation state, responsive sidebar, URL synchronization, and keyboard dismissal.

## Phase boundary

This phase fully redesigns:

- application shell;
- navigation hierarchy;
- Cockpit;
- sign-in experience;
- theme foundation;
- responsive behavior;
- template organization.

Inventory, Sources, Validation, Serving, Insights, Users, and Operations remain functional inside the new shell. Their internal information architecture is intentionally migrated in later phases. `compat.css` should be removed after those modules no longer depend on legacy selectors.

## No deployment side effects

Applying this overlay only updates source files. It does not create services, restart processes, modify the database, or deploy the application.
