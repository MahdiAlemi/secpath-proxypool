# Security baseline

This is the local application security baseline after Phase 1. It is not a deployment authorization or a claim that the proxy listener is production-hardened.

## Authentication

There is no built-in `admin/password123` account. Create a database-backed administrator:

```bash
python3 scripts/create_admin.py --username admin --role admin
```

The optional `DASHBOARD_PASSWORD` variable enables a legacy environment-backed `admin` account. It is intended only as a migration bridge and cannot be changed through the dashboard.

Set independent random values for `FLASK_SECRET_KEY` and `JWT_SECRET`. When `FLASK_SECRET_KEY` is missing, the application uses an ephemeral key and browser sessions reset on restart.

## Browser/API boundaries

- Browser requests use the HttpOnly session cookie and a CSRF token.
- Unsafe cookie-authenticated requests without a valid `X-CSRF-Token` or form token are rejected.
- Bearer-token API clients are not subject to browser CSRF checks.
- Login failures are throttled per direct remote address in the application process.
- API responses set `Cache-Control: no-store` and conservative browser security headers.

## Proxy credentials

General proxy list, stats, server preview, and normal export responses do not expose upstream usernames or passwords. Credential-bearing exports require both:

1. the `proxies.credentials` permission; and
2. `include_credentials=true` on the export request.

The legacy UI deliberately does not prefill stored upstream credentials when editing a proxy. Leaving credential fields blank preserves existing credentials.

## Source imports

Dashboard URL imports allow only public HTTP/HTTPS destinations. The application rejects localhost, private, link-local, multicast, reserved, unspecified, credential-bearing, oversized, and redirecting source URLs. It ignores ambient proxy environment variables and verifies that the connected peer matches the public addresses resolved during validation, reducing DNS-rebinding risk. Source bodies are capped at 2 MB and link configurations at 100 URLs.

## Server profiles and runtime identifiers

Server profile ports, protocols, rotation modes, booleans, numeric bounds, and text lengths are validated before being written to runtime state. Server status responses redact listener usernames/passwords, and blank edit fields preserve existing listener credentials unless `clear_credentials=true` is explicitly submitted. Monitor IDs and server log ports are constrained before being used in filesystem paths.

## Database backups

Creating a backup requires `settings.edit`. Downloading or restoring a database backup additionally requires `proxies.credentials`, because a backup can contain upstream proxy credentials and user records. SQLite backups use the SQLite backup API; uploaded SQLite files are staged, integrity-checked, schema-checked, and atomically replaced before schema verification.

## Remaining boundaries

The proxy listener and monitor lifecycle still require dedicated correctness/security phases. In particular, listener secret storage on disk/argv, public bind policy, process ownership, protocol framing, cooperative cancellation, service management, and versioned database migrations are not declared resolved by this baseline.
