# Local dashboard runtime

The Flask development server is now loopback-only by default:

```dotenv
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=5003
DASHBOARD_ALLOW_PUBLIC=false
```

`bash scripts/run_dashboard.sh` therefore exposes the dashboard only to the current machine. A non-loopback bind such as `0.0.0.0` is rejected unless `DASHBOARD_ALLOW_PUBLIC=true` is set explicitly. This override is intended only for a trusted local network and is not a production deployment mechanism.

## Rotate local secrets without exposing them

Secrets previously printed in a terminal or pasted into a conversation must be treated as compromised. Rotate them atomically with:

```bash
python3 scripts/rotate_local_secrets.py
```

The command updates `FLASK_SECRET_KEY` and `JWT_SECRET` directly in `.env`, sets the file mode to `0600`, and does not print either value.

## Favicon

Both the dashboard and login pages reference `/favicon.ico`. The route is public, serves the bundled ICO asset, and does not require authentication.
