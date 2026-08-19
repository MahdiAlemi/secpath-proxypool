from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable


def _safe(call: Callable[[], Any], default: Any) -> tuple[Any, str | None]:
    try:
        return call(), None
    except Exception as exc:
        return default, str(exc)[:300]


def _safe_database_label(url: Any) -> str:
    try:
        return url.render_as_string(hide_password=True)
    except Exception:
        return str(url)


def _project_root() -> Path:
    import config as config_module

    return Path(config_module.__file__).resolve().parent


def collect_status() -> dict[str, Any]:
    from database import ImportSource, Proxy, User, db

    with db.session() as session:
        total = int(session.query(Proxy).count())
        status_rows = session.query(Proxy.status).all()
        protocol_rows = session.query(Proxy.protocol).all()

        statuses = Counter((row[0] or "unknown") for row in status_rows)
        protocols = Counter((row[0] or "unknown") for row in protocol_rows)

        capabilities = {
            "web_http": int(session.query(Proxy).filter(Proxy.web_http_ok.is_(True)).count()),
            "web_https": int(session.query(Proxy).filter(Proxy.web_https_ok.is_(True)).count()),
            "remote_dns": int(session.query(Proxy).filter(Proxy.remote_dns_ok.is_(True)).count()),
            "telegram": int(session.query(Proxy).filter(Proxy.telegram_ok.is_(True)).count()),
        }
        source_total = int(session.query(ImportSource).count())
        source_enabled = int(session.query(ImportSource).filter(ImportSource.is_active.is_(True)).count())
        user_total = int(session.query(User).count())

    from secproxy_core.monitor_service import list_monitors
    from secproxy_core.server_service import list_servers

    monitors, monitor_error = _safe(list_monitors, [])
    servers, server_error = _safe(list_servers, [])

    backup_dir = _project_root() / "backups" / "secproxy"
    backup_count = (
        sum(1 for path in backup_dir.glob("*.sqlite3") if path.is_file())
        if backup_dir.is_dir()
        else 0
    )

    return {
        "database": {
            "dialect": db.engine.dialect.name,
            "url": _safe_database_label(db.engine.url),
        },
        "proxies": {
            "total": total,
            "statuses": dict(sorted(statuses.items())),
            "protocols": dict(sorted(protocols.items())),
            "capabilities": capabilities,
        },
        "sources": {
            "configured": source_total,
            "enabled": source_enabled,
        },
        "users": {
            "configured": user_total,
        },
        "monitors": {
            "configured": len(monitors),
            "running": sum(1 for item in monitors if item.get("running")),
            "starting": sum(1 for item in monitors if item.get("starting")),
            "error": monitor_error,
        },
        "servers": {
            "configured": len(servers),
            "running": sum(1 for item in servers if item.get("running")),
            "starting": sum(1 for item in servers if item.get("starting")),
            "error": server_error,
        },
        "backups": {
            "configured": backup_count,
            "directory": str(backup_dir),
        },
    }
