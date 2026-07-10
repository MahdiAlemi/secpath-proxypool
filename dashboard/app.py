#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import create_app
from dashboard.runtime import dashboard_bind_from_env

app = create_app()

if __name__ == "__main__":
    try:
        bind_host, bind_port = dashboard_bind_from_env()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    app.run(host=bind_host, port=bind_port, debug=False)
