from __future__ import annotations

from typing import Any

from sqlalchemy import inspect


def initialize_database() -> dict[str, Any]:
    """Create missing database tables and apply additive schema upgrades.

    This operation is intentionally idempotent and non-destructive. It is safe
    to run after deleting a local SQLite database, on a fresh installation, or
    against an existing database that already contains data.
    """
    from database import db, ensure_db_schema

    ensure_db_schema()

    inspector = inspect(db.engine)
    tables = sorted(inspector.get_table_names())

    return {
        "ok": True,
        "database": db.engine.dialect.name,
        "schema_ready": True,
        "table_count": len(tables),
        "tables": tables,
    }
