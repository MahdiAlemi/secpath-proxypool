from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Any

from secproxy_core.errors import ConflictError


def _monitor_module():
    # Framework-neutral core: no Flask route import or request context.
    from secproxy_core import monitor as monitor_core
    return monitor_core


def _registry() -> dict[str, dict[str, Any]]:
    from secproxy_core.config_store import load_monitors_config
    return load_monitors_config()


def resolve_monitor(identifier: str) -> tuple[str, dict[str, Any]] | None:
    value = str(identifier or "").strip()
    if not value:
        return None
    registry = _registry()
    if value in registry:
        return value, registry[value]

    lowered = value.lower()
    matches: list[tuple[str, dict[str, Any]]] = []
    for monitor_id, record in registry.items():
        candidates = {
            monitor_id.lower(),
            monitor_id.removeprefix("monitor_").lower(),
            str(record.get("name") or "").strip().lower(),
            str(record.get("safe_name") or "").strip().lower(),
        }
        if lowered in candidates:
            matches.append((monitor_id, record))
    if len(matches) > 1:
        raise ValueError(f"monitor identifier {identifier!r} is ambiguous")
    return matches[0] if matches else None


def _progress_snapshot(monitor_id: str, record: dict[str, Any]) -> dict[str, Any] | None:
    from database import MonitorSession, db
    from proxy_monitor.utils.progress import read_progress

    m = _monitor_module()
    progress = read_progress(m._root_dir(), monitor_id)
    if progress:
        return progress
    with db.session() as session:
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if not monitor_session:
            return None
        total = int(monitor_session.total_proxies or 0)
        tested = int(monitor_session.tested_count or 0)
        return {
            "state": monitor_session.status,
            "completed": monitor_session.status == "completed",
            "paused": monitor_session.status == "paused",
            "stopped": monitor_session.status == "stopped",
            "total": total,
            "tested": tested,
            "alive": int(monitor_session.alive_count or 0),
            "dead": int(monitor_session.dead_count or 0),
            "other": int(monitor_session.other_count or 0),
            "percent": int((tested / total) * 100) if total else 0,
        }


def _serialize_monitor(monitor_id: str, record: dict[str, Any]) -> dict[str, Any]:
    from database import MonitorSession, db

    m = _monitor_module()
    runtime = m._runtime_status(monitor_id, record)
    with db.session() as session:
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        session_status = monitor_session.status if monitor_session else record.get("last_state")
    progress = _progress_snapshot(monitor_id, record)
    return {
        "id": monitor_id,
        "name": record.get("name") or monitor_id.removeprefix("monitor_"),
        "safe_name": record.get("safe_name") or monitor_id.removeprefix("monitor_"),
        "running": bool(runtime.get("running")),
        "starting": bool(runtime.get("starting")),
        "pid": runtime.get("pid"),
        "memory_mb": runtime.get("memory_mb", 0.0),
        "state": session_status or record.get("last_state") or "idle",
        "last_state": record.get("last_state"),
        "last_error": record.get("last_error"),
        "proxy_count": int(record.get("proxy_count") or 0),
        "start_time": record.get("start_time"),
        "end_time": record.get("end_time"),
        "service": record.get("service"),
        "config": dict(record.get("config") or {}),
        "progress": progress,
    }


def list_monitors() -> list[dict[str, Any]]:
    registry = _registry()
    rows = []
    for monitor_id in sorted(registry):
        try:
            rows.append(_serialize_monitor(monitor_id, registry[monitor_id]))
        except Exception as exc:
            rows.append(
                {
                    "id": monitor_id,
                    "name": registry[monitor_id].get("name") or monitor_id,
                    "running": False,
                    "starting": False,
                    "pid": None,
                    "memory_mb": 0.0,
                    "state": "unknown",
                    "last_state": registry[monitor_id].get("last_state"),
                    "last_error": str(exc)[:500],
                    "proxy_count": int(registry[monitor_id].get("proxy_count") or 0),
                    "config": dict(registry[monitor_id].get("config") or {}),
                    "progress": None,
                    "service": registry[monitor_id].get("service"),
                    "start_time": registry[monitor_id].get("start_time"),
                    "end_time": registry[monitor_id].get("end_time"),
                }
            )
    return rows


def get_monitor(identifier: str) -> dict[str, Any] | None:
    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    return _serialize_monitor(*resolved)


def normalize_profile(data: dict[str, Any], previous: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    return _monitor_module()._normalize_profile(data, previous)


def preview_profile(data: dict[str, Any], *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    m = _monitor_module()
    profile, safe_name = m._normalize_profile(data, previous)
    return {
        "monitor_id": f"monitor_{safe_name}",
        "profile": profile,
        "preview": m._candidate_preview(profile),
    }


def preview_monitor(identifier: str) -> dict[str, Any] | None:
    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    profile = dict(record.get("config") or {})
    return {"monitor_id": monitor_id, "profile": profile, "preview": m._candidate_preview(profile)}


def create_monitor(data: dict[str, Any]) -> dict[str, Any]:
    from proxy_monitor.lifecycle import create_monitor_record

    m = _monitor_module()
    profile, safe_name = m._normalize_profile(data)
    monitor_id = f"monitor_{safe_name}"
    proxy_count = m._proxy_count(profile)
    create_monitor_record(
        m._root_dir(),
        monitor_id,
        {
            "name": profile["name"],
            "safe_name": safe_name,
            "pid": None,
            "process_create_time": None,
            "config": profile,
            "proxy_count": proxy_count,
            "start_time": None,
            "end_time": None,
            "service": None,
            "last_state": "idle",
            "last_error": None,
        },
    )
    return {"monitor_id": monitor_id, "proxy_count": proxy_count, "profile": profile}


def update_monitor(identifier: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    from database import MonitorSession, db
    from proxy_monitor.lifecycle import rename_monitor_record, update_monitor_registry

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    runtime = m._runtime_status(monitor_id, record)
    if runtime.get("running") or runtime.get("starting"):
        raise ConflictError("Cannot update a running monitor")
    with db.session() as session:
        paused = session.query(MonitorSession).filter_by(id=monitor_id, status="paused").first()
        if paused:
            raise ConflictError("Resume or stop the paused session before editing this profile")

    profile, safe_name = m._normalize_profile(changes, record.get("config", {}))
    new_monitor_id = f"monitor_{safe_name}"
    proxy_count = m._proxy_count(profile)
    updates = {
        "name": profile["name"],
        "safe_name": safe_name,
        "config": profile,
        "proxy_count": proxy_count,
        "last_error": None,
    }
    if new_monitor_id != monitor_id:
        rename_monitor_record(m._root_dir(), monitor_id, new_monitor_id, updates)
        old_progress = Path(m._root_dir()) / "progress" / f"{monitor_id}.json"
        new_progress = Path(m._root_dir()) / "progress" / f"{new_monitor_id}.json"
        if old_progress.exists():
            os.replace(old_progress, new_progress)
        old_log = Path(m._log_path(monitor_id))
        new_log = Path(m._log_path(new_monitor_id))
        if old_log.exists() and not new_log.exists():
            os.replace(old_log, new_log)
        monitor_id = new_monitor_id
    else:
        update_monitor_registry(m._root_dir(), monitor_id, updates)
    return {"monitor_id": monitor_id, "proxy_count": proxy_count, "profile": profile}


def start_monitor(identifier: str) -> dict[str, Any] | None:
    from database import MonitorSession, MonitorTested, db
    from proxy_monitor.lifecycle import MonitorAlreadyRunning, clear_action, update_monitor_registry
    from proxy_monitor.utils.progress import delete_progress

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    if m._runtime_status(monitor_id, record).get("running"):
        raise ConflictError("Monitor is already running")

    saved_config = dict(record.get("config") or {})
    if saved_config.get("create_service") == "yes" and os.geteuid() != 0:
        raise PermissionError("Creating a system service requires secproxy to run as root")

    proxy_count = m._proxy_count(saved_config)
    if proxy_count == 0 and saved_config.get("run_mode", "once") == "once":
        raise ConflictError("No proxies match this monitor profile")

    delete_progress(m._root_dir(), monitor_id)
    clear_action(m._root_dir(), monitor_id)
    with db.session() as session:
        session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
        session.query(MonitorSession).filter_by(id=monitor_id).delete()
    update_monitor_registry(
        m._root_dir(), monitor_id, {"proxy_count": proxy_count, "last_state": "starting", "last_error": None}
    )
    try:
        result = m._spawn_monitor(monitor_id, saved_config)
    except MonitorAlreadyRunning as exc:
        update_monitor_registry(m._root_dir(), monitor_id, {"last_state": "running", "last_error": None})
        raise ConflictError(str(exc)) from exc
    except Exception as exc:
        update_monitor_registry(
            m._root_dir(), monitor_id, {"last_state": "failed", "last_error": str(exc)[:500]}
        )
        raise
    return {
        "monitor_id": monitor_id,
        "pid": result["pid"],
        "service": result.get("service"),
        "proxy_count": proxy_count,
    }


def stop_monitor(identifier: str, *, action: str = "stop") -> dict[str, Any] | None:
    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    if action == "pause" and not m._runtime_status(monitor_id, record).get("running"):
        raise ConflictError("Monitor is not running")
    result = m._stop_monitor(monitor_id, action)
    return {"monitor_id": monitor_id, "action": action, **result}



def stop_all_monitors() -> dict[str, dict[str, Any]]:
    results = {}
    for monitor_id in sorted(_registry()):
        try:
            item = stop_monitor(monitor_id, action="stop")
            results[monitor_id] = item or {"error": "Monitor profile not found"}
        except Exception as exc:
            results[monitor_id] = {"error": str(exc)[:300]}
    return results

def resume_monitor(identifier: str) -> dict[str, Any] | None:
    from database import MonitorSession, db
    from proxy_monitor.lifecycle import MonitorAlreadyRunning

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    if m._runtime_status(monitor_id, record).get("running"):
        raise ConflictError("Monitor is already running")
    with db.session() as session:
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if not monitor_session or monitor_session.status != "paused":
            raise ConflictError("No paused session found")
    try:
        result = m._spawn_monitor(monitor_id, record.get("config", {}))
    except MonitorAlreadyRunning as exc:
        raise ConflictError(str(exc)) from exc
    return {"monitor_id": monitor_id, "pid": result["pid"], "service": result.get("service")}


def restart_monitor(identifier: str) -> dict[str, Any] | None:
    current = get_monitor(identifier)
    if current is None:
        return None
    if current.get("running"):
        stop_monitor(current["id"], action="stop")
    return start_monitor(current["id"])


def delete_monitor(identifier: str) -> dict[str, Any] | None:
    from database import MonitorSession, MonitorTested, db
    from proxy_monitor.lifecycle import delete_monitor_record, remove_runtime_files
    from proxy_monitor.utils.progress import delete_progress

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    m = _monitor_module()
    if m._runtime_status(monitor_id, record).get("running"):
        m._stop_monitor(monitor_id, "stop")
    if record.get("service"):
        m._remove_service_for_record(record)
    delete_progress(m._root_dir(), monitor_id)
    with db.session() as session:
        session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
        session.query(MonitorSession).filter_by(id=monitor_id).delete()
    remove_runtime_files(m._root_dir(), monitor_id)
    delete_monitor_record(m._root_dir(), monitor_id)
    with contextlib.suppress(FileNotFoundError):
        os.remove(m._log_path(monitor_id))
    return {"monitor_id": monitor_id, "deleted": True}


def remove_service(identifier: str) -> dict[str, Any] | None:
    from proxy_monitor.lifecycle import update_monitor_registry

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, record = resolved
    if not record.get("service"):
        raise ConflictError("No systemd service exists for this monitor")
    m = _monitor_module()
    m._remove_service_for_record(record)
    update_monitor_registry(
        m._root_dir(), monitor_id, {"service": None, "pid": None, "process_create_time": None}
    )
    return {"monitor_id": monitor_id, "removed": True}


def monitor_results(identifier: str, *, limit: int = 25) -> dict[str, Any] | None:
    from database import MonitorSession, MonitorTested, Proxy, db

    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, _record = resolved
    with db.session() as session:
        rows = (
            session.query(MonitorTested, Proxy)
            .join(Proxy, Proxy.id == MonitorTested.proxy_id)
            .filter(MonitorTested.session_id == monitor_id)
            .order_by(MonitorTested.tested_at.desc(), Proxy.id.desc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        results = [
            {
                "proxy_id": proxy.id,
                "tested_at": tested.tested_at.isoformat() if tested.tested_at else None,
                "protocol": proxy.protocol,
                "endpoint": f"{proxy.ip}:{proxy.port}",
                "status": proxy.status or "untested",
                "speed_ms": proxy.speed_ms,
                "country_code": proxy.countryCode,
                "web_https_ok": bool(proxy.web_https_ok),
                "remote_dns_ok": bool(proxy.remote_dns_ok),
                "telegram_ok": bool(proxy.telegram_ok),
                "last_checked": proxy.last_checked.isoformat() if proxy.last_checked else None,
            }
            for tested, proxy in rows
        ]
        session_data = None
        if monitor_session:
            session_data = {
                "status": monitor_session.status,
                "started_at": monitor_session.started_at.isoformat() if monitor_session.started_at else None,
                "total": int(monitor_session.total_proxies or 0),
                "tested": int(monitor_session.tested_count or 0),
                "alive": int(monitor_session.alive_count or 0),
                "dead": int(monitor_session.dead_count or 0),
                "other": int(monitor_session.other_count or 0),
            }
    return {"monitor_id": monitor_id, "session": session_data, "results": results}


def log_path(identifier: str) -> Path | None:
    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, _record = resolved
    return Path(_monitor_module()._log_path(monitor_id))


def read_logs(identifier: str, *, lines: int = 100) -> dict[str, Any] | None:
    resolved = resolve_monitor(identifier)
    if not resolved:
        return None
    monitor_id, _record = resolved
    path = Path(_monitor_module()._log_path(monitor_id))
    output: list[str] = []
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            output = handle.readlines()[-max(1, min(int(lines), 5000)) :]
    return {"monitor_id": monitor_id, "path": str(path), "lines": [line.rstrip("\n") for line in output]}


def wait_until_stopped(identifier: str, *, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = get_monitor(identifier)
        if not current or not current.get("running"):
            return True
        time.sleep(0.1)
    return False
