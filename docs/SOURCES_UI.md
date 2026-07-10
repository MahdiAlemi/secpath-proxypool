# Sources and import workflow

Phase 6 replaces the legacy import panel with a preflight-first workflow. Operators can inspect and normalize candidates before writing anything to Inventory, save repeatable public sources, and review sanitized import history.

## Input modes

The workspace accepts three input types:

- **Manual or file:** pasted proxy lines or a local text file. This is a one-off batch and cannot be saved as a recurring source.
- **Single URL:** one public HTTP/HTTPS list with a default protocol label.
- **Grouped source config:** an INI-style list containing `[http]`, `[https]`, `[socks4]`, and `[socks5]` sections.

The same normalization engine is used by preview and execution, so browser estimates cannot drift from the actual importer.

## Preflight preview

`POST /api/import/preview` performs a non-mutating preflight. It reports:

- unique valid candidates;
- new versus already stored candidates;
- invalid lines and duplicates in the submitted input;
- protocol distribution;
- sanitized sample endpoints;
- per-source readiness or failure for grouped configurations.

Preview samples never include proxy usernames or passwords. A preview does not create `Proxy` or `ImportRun` rows.

## Import execution

`POST /api/import` writes only candidates that are not already in Inventory. Existing rows are preserved. Duplicate checks are batched rather than issuing one database query per candidate.

Grouped configurations support partial success. Reachable and valid sources are imported even when another source fails; the response and audit record use the `partial` state and retain sanitized source-level results.

## Saved sources

Repeatable URL and grouped configurations are stored in `import_sources`. The UI supports:

- create and rename;
- edit URL, protocol, or grouped configuration;
- enable or disable;
- preview without importing;
- run and update last-run status;
- delete.

Collection responses omit the source URL and grouped content. The detail endpoint returns configuration only to an authenticated user with `proxies.import` permission.

Endpoints:

```text
GET    /api/import/sources
POST   /api/import/sources
GET    /api/import/sources/<id>
PUT    /api/import/sources/<id>
DELETE /api/import/sources/<id>
POST   /api/import/sources/<id>/preview
POST   /api/import/sources/<id>/run
```

Disabled sources remain editable and previewable but cannot be executed.

## Import history

Each actual execution creates an `import_runs` record containing counts, protocol distribution, source-level outcomes, status, timestamps, and actor ID. Manual previews do not create history records.

`GET /api/import/runs?limit=20` returns the recent sanitized audit trail. URLs containing query tokens, fragments, or user information are not copied into source-level error messages or history.

## Limits and security boundary

- Source response body: 2 MB maximum.
- Combined import body: 10 MB maximum.
- Saved grouped configuration: 128 KB maximum.
- Grouped source URLs: 100 maximum.
- Parsed input lines: 100,000 maximum.
- Preview samples: 10 maximum.

Remote fetching reuses the public-address, redirect, peer-verification, response-size, and DNS-rebinding protections documented in `docs/SECURITY.md`.

The two tables are created additively by the normal schema initialization. Existing Proxy rows are not migrated or rewritten.
