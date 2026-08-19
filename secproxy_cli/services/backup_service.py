from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def project_root() -> Path:
    import config as config_module
    return Path(config_module.__file__).resolve().parent


def backup_dir() -> Path:
    path = project_root() / "backups" / "secproxy"
    path.mkdir(parents=True, exist_ok=True)
    with contextlib_suppress():
        os.chmod(path, 0o700)
    return path


class contextlib_suppress:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return True


def _db_path() -> Path:
    from database import db

    if db.engine.dialect.name != "sqlite":
        raise RuntimeError("SecProxy built-in backup currently supports SQLite only")
    raw = db.engine.url.database
    if not raw or raw == ":memory:":
        raise RuntimeError("SQLite database is not file-backed")
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / path
    return path.resolve()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize_label(label: str | None) -> str:
    if not label:
        return ""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-._")
    return value[:40]


def create_backup(*, label: str | None = None) -> dict[str, Any]:
    source = _db_path()
    if not source.exists():
        raise FileNotFoundError(f"Database file not found: {source}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = _sanitize_label(label)
    stem = f"secproxy-{stamp}" + (f"-{safe}" if safe else "")
    destination = backup_dir() / f"{stem}.sqlite3"
    suffix = 1
    while destination.exists():
        destination = backup_dir() / f"{stem}-{suffix}.sqlite3"
        suffix += 1

    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(destination))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(destination, 0o600)

    verification = verify_path(destination)
    meta = {
        "name": destination.name,
        "path": str(destination),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "integrity": verification["integrity"],
        "tables": verification["tables"],
    }
    metadata_path = destination.with_suffix(destination.suffix + ".json")
    metadata_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(metadata_path, 0o600)
    return meta


def verify_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
    finally:
        conn.close()
    return {
        "name": path.name,
        "path": str(path),
        "ok": integrity == "ok",
        "integrity": integrity,
        "tables": tables,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _resolve(identifier: str) -> Path:
    value = str(identifier).strip()
    direct = Path(value).expanduser()
    if direct.is_file():
        return direct.resolve()

    candidates = []
    for path in backup_dir().glob("*.sqlite3"):
        if path.name == value or path.stem == value or path.name.startswith(value):
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"backup {identifier!r} not found")
    if len(candidates) > 1:
        raise ValueError(f"backup identifier {identifier!r} is ambiguous")
    return candidates[0]


def list_backups() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(backup_dir().glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta_path = path.with_suffix(path.suffix + ".json")
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "created_at": meta.get("created_at")
                or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "bytes": path.stat().st_size,
                "sha256": meta.get("sha256"),
                "integrity": meta.get("integrity"),
            }
        )
    return rows


def verify_backup(identifier: str) -> dict[str, Any]:
    return verify_path(_resolve(identifier))


def _active_runtime() -> list[str]:
    active = []
    try:
        from secproxy_cli.services.server_service import list_servers
        for item in list_servers():
            if item.get("running") or item.get("starting"):
                active.append(f"server:{item.get('port')}")
    except Exception:
        pass
    try:
        from secproxy_cli.services.monitor_service import list_monitors
        for item in list_monitors():
            if item.get("running") or item.get("starting"):
                active.append(f"monitor:{item.get('name') or item.get('id')}")
    except Exception:
        pass
    return active


def restore_backup(identifier: str) -> dict[str, Any]:
    from database import db

    selected = _resolve(identifier)
    verification = verify_path(selected)
    if not verification["ok"]:
        raise RuntimeError(f"Backup integrity check failed: {verification['integrity']}")

    active = _active_runtime()
    if active:
        raise RuntimeError("Refusing restore while runtime processes are active: " + ", ".join(active))

    target = _db_path()
    safety = create_backup(label="pre-restore")
    temp = target.with_name(target.name + ".restore.tmp")

    db.engine.dispose()
    shutil.copy2(selected, temp)
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            stale.unlink()
    db.engine.dispose()

    return {
        "restored": selected.name,
        "database": str(target),
        "safety_backup": safety["name"],
        "sha256": verification["sha256"],
    }


def delete_backup(identifier: str) -> dict[str, Any]:
    path = _resolve(identifier)
    result = {"name": path.name, "path": str(path)}
    meta = path.with_suffix(path.suffix + ".json")
    path.unlink()
    if meta.exists():
        meta.unlink()
    return result
