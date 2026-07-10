"""Safe local runtime configuration for the dashboard development server."""

from __future__ import annotations

import ipaddress
import os


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def dashboard_bind_from_env() -> tuple[str, int]:
    """Return a validated bind address for the Flask development server."""
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw_port = os.environ.get("DASHBOARD_PORT", "5003").strip() or "5003"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("DASHBOARD_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("DASHBOARD_PORT must be between 1 and 65535")

    is_loopback = host.lower() == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False

    if not is_loopback and not env_flag("DASHBOARD_ALLOW_PUBLIC"):
        raise ValueError(
            "Refusing to expose the Flask development server on a non-loopback host. "
            "Set DASHBOARD_ALLOW_PUBLIC=true only for an intentionally trusted local network."
        )
    return host, port
