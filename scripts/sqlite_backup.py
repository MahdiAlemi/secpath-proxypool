#!/usr/bin/env python3
"""Create, verify, or restore private SecPath ProxyPool SQLite backups."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backup_utils import (  # noqa: E402
    create_sqlite_backup,
    replace_sqlite_database,
    stage_sqlite_copy,
    validate_sqlite_database,
)


def _default_database() -> Path:
    return Path(os.environ.get("SQLITE_DB_PATH", "proxies.db"))


def command_backup(args: argparse.Namespace) -> int:
    backup = create_sqlite_backup(
        args.source,
        directory=args.directory,
        prefix=args.prefix,
    )
    print(f"Backup created: {backup}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    tables = validate_sqlite_database(args.file)
    print(f"Backup valid: {args.file} ({len(tables)} tables)")
    return 0


def command_restore(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Restore requires --yes because it replaces the destination database.", file=sys.stderr)
        return 2

    source = Path(args.file).resolve()
    destination = Path(args.destination).resolve()
    validate_sqlite_database(source)

    previous = None
    if destination.exists():
        previous = create_sqlite_backup(
            destination,
            directory=args.backup_directory,
            prefix="proxies_backup_before_restore",
        )

    staged = stage_sqlite_copy(source, destination_directory=destination.parent)
    try:
        replace_sqlite_database(staged, destination)
    finally:
        staged.unlink(missing_ok=True)

    message = f"Database restored: {destination}"
    if previous is not None:
        message += f" (previous database backed up to {previous})"
    print(message)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="Create a consistent private backup")
    backup.add_argument("--source", type=Path, default=_default_database())
    backup.add_argument("--directory", type=Path, default=Path("backups"))
    backup.add_argument("--prefix", default="proxies_backup")
    backup.set_defaults(handler=command_backup)

    verify = subparsers.add_parser("verify", help="Validate an SQLite backup")
    verify.add_argument("file", type=Path)
    verify.set_defaults(handler=command_verify)

    restore = subparsers.add_parser("restore", help="Replace a database from a verified backup")
    restore.add_argument("file", type=Path)
    restore.add_argument("--destination", type=Path, default=_default_database())
    restore.add_argument("--backup-directory", type=Path, default=Path("backups"))
    restore.add_argument("--yes", action="store_true")
    restore.set_defaults(handler=command_restore)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
