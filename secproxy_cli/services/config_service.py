from __future__ import annotations

from pathlib import Path
from typing import Any


def config_snapshot() -> dict[str, Any]:
    import config as config_module

    config = config_module.config
    env_path = Path(config_module.__file__).resolve().parent / ".env"
    return {
        "env_file": str(env_path),
        "env_exists": env_path.exists(),
        "db_type": config.DB_TYPE,
        "database_url": _redact_database_url(config.get_database_url()),
        "sqlite_db_path": config.SQLITE_DB_PATH if config.DB_TYPE.lower() == "sqlite" else None,
        "db_pool_size": config.DB_POOL_SIZE,
        "db_max_overflow": config.DB_MAX_OVERFLOW,
        "db_pool_timeout": config.DB_POOL_TIMEOUT,
        "db_pool_recycle": config.DB_POOL_RECYCLE,
    }


def env_path() -> Path:
    import config as config_module

    return Path(config_module.__file__).resolve().parent / ".env"


def validate_config() -> list[dict[str, Any]]:
    snapshot = config_snapshot()
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "env_file",
            "ok": bool(snapshot["env_exists"]),
            "detail": snapshot["env_file"],
        }
    )
    checks.append(
        {
            "name": "db_type",
            "ok": snapshot["db_type"].lower() in {"sqlite", "mysql"},
            "detail": snapshot["db_type"],
        }
    )
    if snapshot["db_type"].lower() == "sqlite":
        sqlite_path = snapshot["sqlite_db_path"]
        checks.append(
            {
                "name": "sqlite_path",
                "ok": bool(sqlite_path),
                "detail": sqlite_path or "missing",
            }
        )
    return checks


def _redact_database_url(url: str) -> str:
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<configured>" if url else ""
