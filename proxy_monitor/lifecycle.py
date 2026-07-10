"""Process-safe lifecycle state for proxy monitor jobs.

The dashboard and monitor worker are separate processes. This module provides
small, dependency-light primitives shared by both sides:

* atomic JSON state writes;
* per-monitor file locks;
* start reservations to reject concurrent launches;
* process identity checks that protect against PID reuse;
* control requests used to distinguish pause from stop;
* graceful process termination with a bounded kill fallback.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import psutil


MONITOR_ID_RE = re.compile(r"^monitor_[a-z0-9_-]{1,80}$")
VALID_ACTIONS = {"pause", "stop"}
START_RESERVATION_TTL = 30.0


class MonitorLifecycleError(RuntimeError):
    pass


class MonitorAlreadyRunning(MonitorLifecycleError):
    def __init__(self, monitor_id: str, pid: int | None = None):
        self.monitor_id = monitor_id
        self.pid = pid
        suffix = f" (PID {pid})" if pid else ""
        super().__init__(f"Monitor is already running: {monitor_id}{suffix}")


class MonitorStartReservationError(MonitorLifecycleError):
    pass


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_monitor_id(monitor_id: str) -> str:
    value = str(monitor_id or "")
    if not MONITOR_ID_RE.fullmatch(value):
        raise ValueError("Invalid monitor id")
    return value


def runtime_dir(root_dir: str | os.PathLike[str]) -> Path:
    path = Path(root_dir).resolve() / ".runtime" / "monitors"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(root_dir: str | os.PathLike[str], monitor_id: str, suffix: str) -> Path:
    validate_monitor_id(monitor_id)
    return runtime_dir(root_dir) / f"{monitor_id}.{suffix}"


@contextlib.contextmanager
def monitor_lock(root_dir: str | os.PathLike[str], monitor_id: str) -> Iterator[None]:
    lock_path = _state_path(root_dir, monitor_id, "lock")
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def registry_lock(root_dir: str | os.PathLike[str]) -> Iterator[None]:
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".monitors.json.lock"
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path: str | os.PathLike[str], data: Any, *, indent: int | None = 2) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def load_monitor_registry(root_dir: str | os.PathLike[str]) -> dict[str, Any]:
    payload = read_json(Path(root_dir).resolve() / ".monitors.json", {})
    return payload if isinstance(payload, dict) else {}


def update_monitor_registry(
    root_dir: str | os.PathLike[str],
    monitor_id: str,
    updates: dict[str, Any],
    *,
    create: bool = False,
) -> dict[str, Any] | None:
    validate_monitor_id(monitor_id)
    path = Path(root_dir).resolve() / ".monitors.json"
    with registry_lock(root_dir):
        registry = read_json(path, {})
        if not isinstance(registry, dict):
            registry = {}
        if monitor_id not in registry and not create:
            return None
        record = registry.setdefault(monitor_id, {})
        if not isinstance(record, dict):
            record = {}
            registry[monitor_id] = record
        record.update(updates)
        atomic_write_json(path, registry, indent=2)
        return dict(record)


def claim_path(root_dir: str | os.PathLike[str], monitor_id: str) -> Path:
    return _state_path(root_dir, monitor_id, "claim.json")


def control_path(root_dir: str | os.PathLike[str], monitor_id: str) -> Path:
    return _state_path(root_dir, monitor_id, "control.json")


def _extract_monitor_id(cmdline: list[str]) -> str | None:
    for index, value in enumerate(cmdline):
        if value == "--monitor-id" and index + 1 < len(cmdline):
            return cmdline[index + 1]
        if value.startswith("--monitor-id="):
            return value.split("=", 1)[1]
    return None


def process_matches(
    pid: int | str | None,
    monitor_id: str,
    *,
    expected_create_time: float | int | None = None,
) -> bool:
    validate_monitor_id(monitor_id)
    try:
        process = psutil.Process(int(pid))
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        if expected_create_time is not None and abs(process.create_time() - float(expected_create_time)) > 2.0:
            return False
        return _extract_monitor_id(process.cmdline()) == monitor_id
    except (TypeError, ValueError, psutil.Error, OSError):
        return False


def process_snapshot(pid: int | str | None, monitor_id: str, *, expected_create_time=None) -> dict[str, Any]:
    if not process_matches(pid, monitor_id, expected_create_time=expected_create_time):
        return {"running": False, "pid": None, "memory_mb": 0.0, "create_time": None}
    try:
        process = psutil.Process(int(pid))
        return {
            "running": True,
            "pid": int(pid),
            "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
            "create_time": process.create_time(),
        }
    except psutil.Error:
        return {"running": False, "pid": None, "memory_mb": 0.0, "create_time": None}


def read_claim(root_dir: str | os.PathLike[str], monitor_id: str) -> dict[str, Any] | None:
    payload = read_json(claim_path(root_dir, monitor_id), None)
    return payload if isinstance(payload, dict) else None


def _claim_is_starting(claim: dict[str, Any]) -> bool:
    if claim.get("state") != "starting":
        return False
    try:
        return time.time() - float(claim.get("reserved_at_epoch", 0)) < START_RESERVATION_TTL
    except (TypeError, ValueError):
        return False


def active_claim(root_dir: str | os.PathLike[str], monitor_id: str) -> dict[str, Any] | None:
    claim = read_claim(root_dir, monitor_id)
    if not claim:
        return None
    if claim.get("state") == "running" and process_matches(
        claim.get("pid"),
        monitor_id,
        expected_create_time=claim.get("process_create_time"),
    ):
        return claim
    if _claim_is_starting(claim):
        return claim
    return None


def reserve_start(root_dir: str | os.PathLike[str], monitor_id: str) -> str:
    validate_monitor_id(monitor_id)
    token = secrets.token_urlsafe(24)
    with monitor_lock(root_dir, monitor_id):
        claim = active_claim(root_dir, monitor_id)
        if claim:
            raise MonitorAlreadyRunning(monitor_id, claim.get("pid"))
        atomic_write_json(
            claim_path(root_dir, monitor_id),
            {
                "state": "starting",
                "token": token,
                "reserved_at": utcnow_iso(),
                "reserved_at_epoch": time.time(),
            },
        )
    return token


def activate_claim(
    root_dir: str | os.PathLike[str],
    monitor_id: str,
    *,
    token: str | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    validate_monitor_id(monitor_id)
    pid = int(pid or os.getpid())
    process = psutil.Process(pid)
    with monitor_lock(root_dir, monitor_id):
        claim = read_claim(root_dir, monitor_id)
        if claim:
            if claim.get("state") == "running" and process_matches(
                claim.get("pid"), monitor_id, expected_create_time=claim.get("process_create_time")
            ):
                if int(claim.get("pid")) != pid:
                    raise MonitorAlreadyRunning(monitor_id, int(claim.get("pid")))
            elif _claim_is_starting(claim):
                expected_token = claim.get("token")
                if expected_token and token != expected_token:
                    raise MonitorStartReservationError("Monitor start reservation token does not match")
        payload = {
            "state": "running",
            "pid": pid,
            "process_create_time": process.create_time(),
            "started_at": utcnow_iso(),
            "token": token,
        }
        atomic_write_json(claim_path(root_dir, monitor_id), payload)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(control_path(root_dir, monitor_id))
        return payload


def abandon_reservation(root_dir: str | os.PathLike[str], monitor_id: str, token: str | None) -> None:
    with monitor_lock(root_dir, monitor_id):
        claim = read_claim(root_dir, monitor_id)
        if not claim:
            return
        if claim.get("state") == "starting" and (not token or claim.get("token") == token):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(claim_path(root_dir, monitor_id))


def release_claim(root_dir: str | os.PathLike[str], monitor_id: str, *, pid: int | None = None) -> None:
    with monitor_lock(root_dir, monitor_id):
        claim = read_claim(root_dir, monitor_id)
        if not claim:
            return
        if pid is not None and claim.get("pid") not in (None, int(pid)):
            return
        with contextlib.suppress(FileNotFoundError):
            os.unlink(claim_path(root_dir, monitor_id))


def request_action(root_dir: str | os.PathLike[str], monitor_id: str, action: str) -> dict[str, Any]:
    validate_monitor_id(monitor_id)
    if action not in VALID_ACTIONS:
        raise ValueError("Invalid monitor control action")
    payload = {"action": action, "requested_at": utcnow_iso(), "requested_at_epoch": time.time()}
    atomic_write_json(control_path(root_dir, monitor_id), payload)
    return payload


def read_action(root_dir: str | os.PathLike[str], monitor_id: str) -> str | None:
    payload = read_json(control_path(root_dir, monitor_id), None)
    if isinstance(payload, dict) and payload.get("action") in VALID_ACTIONS:
        return payload["action"]
    return None


def clear_action(root_dir: str | os.PathLike[str], monitor_id: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(control_path(root_dir, monitor_id))


def find_runtime_process(root_dir: str | os.PathLike[str], monitor_id: str) -> dict[str, Any]:
    claim = read_claim(root_dir, monitor_id)
    if claim and claim.get("state") == "running":
        snapshot = process_snapshot(
            claim.get("pid"),
            monitor_id,
            expected_create_time=claim.get("process_create_time"),
        )
        if snapshot["running"]:
            return snapshot
    return {"running": False, "pid": None, "memory_mb": 0.0, "create_time": None}


def terminate_process(
    root_dir: str | os.PathLike[str],
    monitor_id: str,
    *,
    action: str,
    grace_seconds: float = 12.0,
) -> dict[str, Any]:
    request_action(root_dir, monitor_id, action)
    snapshot = find_runtime_process(root_dir, monitor_id)
    if not snapshot["running"]:
        return {"found": False, "graceful": True, "killed": False, "pid": None}

    pid = int(snapshot["pid"])
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            with contextlib.suppress(psutil.Error):
                child.terminate()
        process.terminate()
        gone, alive = psutil.wait_procs([process, *children], timeout=max(0.1, float(grace_seconds)))
        if alive:
            for remaining in alive:
                with contextlib.suppress(psutil.Error):
                    remaining.kill()
            psutil.wait_procs(alive, timeout=3.0)
            return {"found": True, "graceful": False, "killed": True, "pid": pid}
        return {"found": True, "graceful": True, "killed": False, "pid": pid}
    except psutil.NoSuchProcess:
        return {"found": False, "graceful": True, "killed": False, "pid": pid}
    except psutil.Error as exc:
        raise MonitorLifecycleError(f"Could not stop monitor process: {exc}") from exc


def remove_runtime_files(root_dir: str | os.PathLike[str], monitor_id: str) -> None:
    validate_monitor_id(monitor_id)
    for suffix in ("claim.json", "control.json", "lock"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(_state_path(root_dir, monitor_id, suffix))


def create_monitor_record(root_dir, monitor_id, record):
    validate_monitor_id(monitor_id)
    path = Path(root_dir).resolve() / ".monitors.json"
    with registry_lock(root_dir):
        registry = read_json(path, {})
        if not isinstance(registry, dict):
            registry = {}
        if monitor_id in registry:
            raise FileExistsError(monitor_id)
        registry[monitor_id] = dict(record)
        atomic_write_json(path, registry, indent=2)
        return dict(registry[monitor_id])


def delete_monitor_record(root_dir, monitor_id):
    validate_monitor_id(monitor_id)
    path = Path(root_dir).resolve() / ".monitors.json"
    with registry_lock(root_dir):
        registry = read_json(path, {})
        if not isinstance(registry, dict) or monitor_id not in registry:
            return False
        del registry[monitor_id]
        atomic_write_json(path, registry, indent=2)
        return True


def rename_monitor_record(root_dir, old_monitor_id, new_monitor_id, updates=None):
    validate_monitor_id(old_monitor_id)
    validate_monitor_id(new_monitor_id)
    path = Path(root_dir).resolve() / ".monitors.json"
    with registry_lock(root_dir):
        registry = read_json(path, {})
        if not isinstance(registry, dict) or old_monitor_id not in registry:
            raise KeyError(old_monitor_id)
        if new_monitor_id != old_monitor_id and new_monitor_id in registry:
            raise FileExistsError(new_monitor_id)
        record = registry.pop(old_monitor_id)
        if updates:
            record.update(updates)
        registry[new_monitor_id] = record
        atomic_write_json(path, registry, indent=2)
        return dict(record)
