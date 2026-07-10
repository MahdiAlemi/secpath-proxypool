#!/usr/bin/env python3
"""Safely migrate ProxyPool proxy records from SQLite to another SQLAlchemy DB.

The command is dry-run by default.  Pass ``--execute`` to write data.  Existing
proxy identities are skipped; ``--replace --yes-replace`` deletes only target
proxy rows before migration and never drops user or audit tables.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import DateTime, create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from database import Base, Proxy

IDENTITY_COLUMNS = ("protocol", "ip", "port", "username", "password")
JSON_COLUMNS = {"speed_history", "validation_summary"}




def _target_matches_source(source: Path, target_url: str) -> bool:
    url = make_url(target_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return False
    target = Path(url.database)
    if not target.is_absolute():
        target = Path.cwd() / target
    return target.resolve() == source.resolve()

def _redacted_url(value: str) -> str:
    return make_url(value).render_as_string(hide_password=True)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _normalize_value(column_name: str, value: Any) -> Any:
    column = Proxy.__table__.columns[column_name]
    if value is None:
        return None
    if column_name in JSON_COLUMNS and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(column.type, DateTime):
        return _parse_datetime(value)
    return value


def inspect_source(path: Path) -> tuple[int, list[str]]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "proxies" not in tables:
            raise ValueError("Source database does not contain the proxies table")
        columns = [row[1] for row in connection.execute("PRAGMA table_info(proxies)")]
        missing = set(IDENTITY_COLUMNS) - set(columns)
        if missing:
            raise ValueError("Source proxies table is missing identity columns: " + ", ".join(sorted(missing)))
        total = int(connection.execute("SELECT COUNT(*) FROM proxies").fetchone()[0])
        return total, columns
    finally:
        connection.close()


def _iter_rows(path: Path, columns: list[str], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    quoted = ", ".join(f'"{name}"' for name in columns)
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(f"SELECT {quoted} FROM proxies ORDER BY id")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [
                {name: _normalize_value(name, row[name]) for name in columns}
                for row in rows
            ]
    finally:
        connection.close()


def _insert_ignore(engine: Engine, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    dialect = engine.dialect.name
    table = Proxy.__table__
    with engine.begin() as connection:
        if dialect == "mysql":
            from sqlalchemy.dialects.mysql import insert as mysql_insert

            connection.execute(mysql_insert(table).values(rows).prefix_with("IGNORE"))
            return
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            statement = sqlite_insert(table).values(rows).on_conflict_do_nothing(
                index_elements=list(IDENTITY_COLUMNS)
            )
            connection.execute(statement)
            return

        for row in rows:
            try:
                with connection.begin_nested():
                    connection.execute(table.insert().values(**row))
            except IntegrityError:
                continue


def migrate(
    *,
    source: Path,
    target_url: str,
    batch_size: int,
    replace: bool,
) -> dict[str, Any]:
    source_total, source_columns = inspect_source(source)
    target_columns = [column.name for column in Proxy.__table__.columns if column.name != "id"]
    copy_columns = [name for name in target_columns if name in source_columns]

    engine = create_engine(target_url, poolclass=NullPool, pool_pre_ping=True)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            before = int(connection.scalar(select(func.count()).select_from(Proxy.__table__)) or 0)
            if replace:
                connection.execute(Proxy.__table__.delete())
                before = 0

        processed = 0
        for batch in _iter_rows(source, copy_columns, batch_size):
            _insert_ignore(engine, batch)
            processed += len(batch)

        with engine.connect() as connection:
            after = int(connection.scalar(select(func.count()).select_from(Proxy.__table__)) or 0)
        return {
            "source_rows": source_total,
            "processed_rows": processed,
            "target_before": before,
            "target_after": after,
            "inserted_rows": max(0, after - before),
            "skipped_rows": max(0, processed - max(0, after - before)),
            "copied_columns": copy_columns,
        }
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("SQLITE_DB_PATH", "proxies.db")),
        help="Source SQLite database",
    )
    parser.add_argument(
        "--target-url",
        default=os.environ.get("MIGRATION_TARGET_URL", ""),
        help="Target SQLAlchemy URL; MIGRATION_TARGET_URL is also supported",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--execute", action="store_true", help="Perform the migration")
    parser.add_argument("--replace", action="store_true", help="Delete target proxy rows first")
    parser.add_argument(
        "--yes-replace",
        action="store_true",
        help="Required confirmation for --replace",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.batch_size <= 10000:
        print("--batch-size must be between 1 and 10000", file=sys.stderr)
        return 2
    if not args.target_url:
        print("--target-url or MIGRATION_TARGET_URL is required", file=sys.stderr)
        return 2
    if args.replace and not args.yes_replace:
        print("--replace requires --yes-replace", file=sys.stderr)
        return 2

    try:
        source_total, source_columns = inspect_source(args.source)
        if _target_matches_source(args.source, args.target_url):
            raise ValueError("Source and target databases must be different files")
        plan = {
            "mode": "execute" if args.execute else "dry-run",
            "source": str(args.source.resolve()),
            "source_rows": source_total,
            "source_columns": source_columns,
            "target": _redacted_url(args.target_url),
            "replace": bool(args.replace),
            "batch_size": args.batch_size,
        }
        if not args.execute:
            print(json.dumps(plan, indent=2, sort_keys=True))
            print("Dry-run only. Re-run with --execute to write to the target database.")
            return 0

        result = migrate(
            source=args.source,
            target_url=args.target_url,
            batch_size=args.batch_size,
            replace=args.replace,
        )
        print(json.dumps({**plan, **result}, indent=2, sort_keys=True))
        return 0
    except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"Migration validation failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
