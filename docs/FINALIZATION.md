# Finalization and end-to-end baseline

Phase 10 removes the temporary UI compatibility layer and turns repository hygiene into an enforced invariant.

## Final UI architecture

- `base.js` contains only shared browser primitives, Cockpit loading, tab navigation, and the shared proxy dialogs.
- Inventory, Sources, Validation, Serving, Insights, Operations, and Access each own their page-specific JavaScript and CSS.
- `compat.css` is retired and must not be tracked.
- Dashboard templates do not use inline `style` attributes.
- The application favicon is provided by `dashboard/static/img/favicon.svg`.

## Apply cleanup

After applying the overlay, run:

```bash
bash scripts/apply_phase10_cleanup.sh
```

The script removes the retired stylesheet and normalizes Git executable modes. Only scripts and executable application entrypoints remain executable.

## End-to-end regression

`tests/test_end_to_end_workflow.py` exercises the operator path without external network access or process creation:

1. Render the complete application shell.
2. Preview and execute a manual import.
3. Verify credential-redacted inventory output.
4. Preview a Validation profile against the imported candidate.
5. Simulate a validated candidate in the disposable test database.
6. Preview a Serving profile using the same scoped candidate.
7. Verify Insights and sanitized import history.

All tests use temporary SQLite databases.

## Repository invariants

`repo_hygiene_check.sh` now fails when:

- runtime files, databases, logs, or obsolete phase artifacts are tracked;
- a non-entrypoint source file is executable;
- `compat.css` is tracked;
- templates contain inline style attributes;
- merge-conflict markers are present;
- the shared `base.js` grows beyond its modularity budget;
- the favicon is missing.
