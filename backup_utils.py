"""Private, collision-safe SQLite backup helpers.

The dashboard stores upstream proxy credentials in the database, so backup files
must be treated as secrets.  Helpers in this module always create files with
mode ``0600`` and never overwrite an existing backup name.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

MAX_SQLITE_BACKUP_BYTES = 512 * 1024 * 1024


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def reserve_private_file(
    directory: str | os.PathLike[str],
    *,
    prefix: str,
    suffix: str,
) -> tuple[Path, int]:
    """Atomically reserve a unique private file and return ``(path, fd)``."""
    target_dir = Path(directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    for _attempt in range(20):
        name = f"{prefix}_{_stamp()}_{secrets.token_hex(3)}{suffix}"
        path = target_dir / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return path, fd
        except FileExistsError:
            continue
    raise FileExistsError("Unable to reserve a unique backup filename")


def validate_sqlite_database(
    path: str | os.PathLike[str],
    *,
    required_tables: Iterable[str] = ("proxies",),
    max_bytes: int = MAX_SQLITE_BACKUP_BYTES,
) -> set[str]:
    """Validate an SQLite database and return its table names."""
    source = Path(path)
    size = source.stat().st_size
    if size < 100 or size > max_bytes:
        raise ValueError("SQLite backup size is invalid")
    with source.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("Uploaded file is not a SQLite database")

    connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("SQLite backup failed integrity validation")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()

    missing = set(required_tables) - tables
    if missing:
        raise ValueError(
            "SQLite backup is missing required tables: " + ", ".join(sorted(missing))
        )
    return tables


def create_sqlite_backup(
    source_path: str | os.PathLike[str],
    *,
    directory: str | os.PathLike[str],
    prefix: str = "proxies_backup",
) -> Path:
    """Create a consistent, validated, mode-0600 SQLite backup."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    destination, fd = reserve_private_file(
        directory,
        prefix=prefix,
        suffix=".sqlite",
    )
    os.close(fd)
    try:
        source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        destination_conn = sqlite3.connect(destination)
        try:
            with destination_conn:
                source_conn.backup(destination_conn)
        finally:
            destination_conn.close()
            source_conn.close()
        os.chmod(destination, 0o600)
        validate_sqlite_database(destination)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def stage_sqlite_copy(
    source_path: str | os.PathLike[str],
    *,
    destination_directory: str | os.PathLike[str],
) -> Path:
    """Copy a validated SQLite file to a private temporary file for replacement."""
    source = Path(source_path).resolve()
    validate_sqlite_database(source)
    target_dir = Path(destination_directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".proxypool-restore-", suffix=".sqlite", dir=target_dir)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            while True:
                chunk = input_file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_path, 0o600)
        validate_sqlite_database(temp_path)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def replace_sqlite_database(
    staged_path: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
) -> None:
    """Atomically replace the destination with a validated staged database."""
    staged = Path(staged_path).resolve()
    destination = Path(destination_path).resolve()
    validate_sqlite_database(staged)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(staged, 0o600)
    os.replace(staged, destination)
    os.chmod(destination, 0o600)
