# Serving Center

The Serving Center is the operator interface for proxy listener profiles. It sits on top of the hardened proxy-server lifecycle and protocol implementation documented in `PROXY_SERVER_CORE.md`.

## Workspace

The page is split into a searchable profile list and a selected-profile detail panel. The detail view exposes only operational information:

- listener endpoint and exposure scope;
- running/stopped process state and PID;
- rotation and timeout policy;
- candidate status, protocol, capability, geo, and network filters;
- a credential-redacted candidate preflight;
- recent bounded log output;
- Start, Stop, Edit, and Delete actions allowed by `server.control`.

Client and upstream credentials are never returned by the status, detail, preview, or sample APIs. A detail response includes only `has_auth`.

## Profile editor

The editor supports four presets: Web, Telegram, HTTP scraping, and Custom. Presets initialize capability requirements but remain fully editable. Preview uses the same normalization and proxy-scope rules as runtime selection and does not start a process or modify the database.

Existing listener credentials are preserved when an authorized operator edits a profile and leaves the credential fields blank. Preview identifies the existing profile by port so it can enforce network-exposure rules without returning or resubmitting the secret. The operator may explicitly clear stored credentials.

## API additions

`GET /api/server/<port>` returns a single credential-redacted profile, current process state, safe endpoint metadata, scoped candidate counts/samples, and the last 80 log lines.

`POST /api/server/preview-candidates` now validates candidate statuses and upstream protocols. During edit it accepts `existing_port` only to resolve the saved profile and preserve hidden credentials during normalization.

`GET /api/server/log` validates both `port` and `limit`, caps output at 500 lines, and rejects unknown profiles.

## Safety boundaries

- Non-loopback no-auth listeners remain blocked unless the explicit override is enabled.
- Applying the overlay does not start or stop listeners.
- The UI warns before starting a profile with zero matching candidates.
- Logs may contain upstream hostnames and operational errors and must be treated as local runtime data.
- Profile port changes are intentionally disabled during edit; create a new profile to move a listener to another port.
