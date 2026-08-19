from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def _root() -> Path:
    import config as config_module
    return Path(config_module.__file__).resolve().parent


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


def _older(path: Path, days: int) -> bool:
    cutoff = time.time() - (days * 86400)
    return path.stat().st_mtime < cutoff


def log_candidates(*, older_than_days: int = 30) -> list[dict[str, Any]]:
    root = _root()
    paths = set()
    for pattern in ("*.log", "monitor_*.log", "server_*.log"):
        paths.update(p for p in root.glob(pattern) if p.is_file())
    rows = []
    for path in sorted(paths):
        if _older(path, older_than_days):
            rows.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "age_days": int((time.time() - path.stat().st_mtime) / 86400),
                }
            )
    return rows


def delete_logs(*, older_than_days: int = 30) -> dict[str, Any]:
    candidates = log_candidates(older_than_days=older_than_days)
    deleted = []
    total = 0
    for item in candidates:
        path = Path(item["path"])
        total += int(item["bytes"])
        path.unlink(missing_ok=True)
        deleted.append(str(path))
    return {"deleted": len(deleted), "bytes": total, "files": deleted}


def runtime_candidates(*, older_than_days: int = 7) -> list[dict[str, Any]]:
    active = _active_runtime()
    if active:
        raise RuntimeError("Refusing runtime cleanup while processes are active: " + ", ".join(active))

    runtime = _root() / ".runtime"
    if not runtime.exists():
        return []
    rows = []
    for path in runtime.rglob("*"):
        if path.is_file() and _older(path, older_than_days):
            rows.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "age_days": int((time.time() - path.stat().st_mtime) / 86400),
                }
            )
    return rows


def delete_runtime(*, older_than_days: int = 7) -> dict[str, Any]:
    candidates = runtime_candidates(older_than_days=older_than_days)
    deleted = []
    total = 0
    runtime = _root() / ".runtime"
    for item in candidates:
        path = Path(item["path"])
        total += int(item["bytes"])
        path.unlink(missing_ok=True)
        deleted.append(str(path))
    if runtime.exists():
        for directory in sorted((p for p in runtime.rglob("*") if p.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
    return {"deleted": len(deleted), "bytes": total, "files": deleted}
