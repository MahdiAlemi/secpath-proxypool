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

import psutil

SERVER_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")


def validate_server_id(server_id: str) -> str:
    value = str(server_id or "")
    if not SERVER_ID_RE.fullmatch(value):
        raise ValueError("invalid server id")
    return value


def runtime_dir(root_dir) -> Path:
    path = Path(root_dir).resolve() / ".runtime" / "servers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(root_dir, server_id) -> Path:
    return runtime_dir(root_dir) / f"{validate_server_id(server_id)}.json"


def profile_path(root_dir, server_id) -> Path:
    return runtime_dir(root_dir) / f"{validate_server_id(server_id)}.profile.json"


def _lock_path(root_dir, server_id) -> Path:
    return runtime_dir(root_dir) / f"{validate_server_id(server_id)}.lock"


@contextlib.contextmanager
def server_lock(root_dir, server_id):
    with open(_lock_path(root_dir, server_id), "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path, payload, *, mode=0o600):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, mode)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def read_state(root_dir, server_id):
    try:
        with open(state_path(root_dir, server_id), encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _extract_server_id(cmdline):
    for index, value in enumerate(cmdline or []):
        if value == "--server-id" and index + 1 < len(cmdline):
            return cmdline[index + 1]
        if str(value).startswith("--server-id="):
            return str(value).split("=", 1)[1]
    return None


def process_matches(pid, server_id, expected_create_time=None):
    try:
        process = psutil.Process(int(pid))
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        if expected_create_time is not None and abs(process.create_time() - float(expected_create_time)) > 2:
            return False
        return _extract_server_id(process.cmdline()) == validate_server_id(server_id)
    except (TypeError, ValueError, OSError, psutil.Error):
        return False


def snapshot(root_dir, server_id):
    state = read_state(root_dir, server_id)
    if not process_matches(state.get("pid"), server_id, state.get("process_create_time")):
        return {"running": False, "pid": None, "memory_mb": 0.0, "connections": 0, "create_time": None}
    try:
        process = psutil.Process(int(state["pid"]))
        return {
            "running": True,
            "pid": int(state["pid"]),
            "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
            "connections": len(process.net_connections(kind="inet")),
            "create_time": process.create_time(),
        }
    except psutil.Error:
        return {"running": False, "pid": None, "memory_mb": 0.0, "connections": 0, "create_time": None}



def reserve_start(root_dir, server_id, ttl=30.0):
    server_id = validate_server_id(server_id)
    with server_lock(root_dir, server_id):
        current = read_state(root_dir, server_id)
        if current.get("state") == "running" and process_matches(
            current.get("pid"), server_id, current.get("process_create_time")
        ):
            raise RuntimeError(f"server {server_id} is already running")
        if current.get("state") == "starting":
            try:
                if time.time() - float(current.get("reserved_at_epoch", 0)) < float(ttl):
                    raise RuntimeError(f"server {server_id} is already starting")
            except (TypeError, ValueError):
                pass
        token = secrets.token_urlsafe(24)
        atomic_write_json(
            state_path(root_dir, server_id),
            {
                "server_id": server_id,
                "state": "starting",
                "token": token,
                "reserved_at_epoch": time.time(),
                "reserved_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return token

def claim(root_dir, server_id, pid=None, token=None):
    server_id = validate_server_id(server_id)
    pid = int(pid or os.getpid())
    process = psutil.Process(pid)
    with server_lock(root_dir, server_id):
        current = read_state(root_dir, server_id)
        if current.get("state") == "running" and process_matches(
            current.get("pid"), server_id, current.get("process_create_time")
        ):
            if int(current["pid"]) != pid:
                raise RuntimeError(f"server {server_id} is already running")
        elif current.get("state") == "starting" and current.get("token") != token:
            raise RuntimeError("server start reservation token does not match")
        payload = {
            "server_id": server_id,
            "state": "running",
            "pid": pid,
            "process_create_time": process.create_time(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(state_path(root_dir, server_id), payload)
        return payload


def release(root_dir, server_id, pid=None):
    with server_lock(root_dir, server_id):
        state = read_state(root_dir, server_id)
        if pid is not None and state.get("pid") not in (None, int(pid)):
            return
        with contextlib.suppress(FileNotFoundError):
            os.unlink(state_path(root_dir, server_id))


def terminate(root_dir, server_id, grace_seconds=10.0):
    current = snapshot(root_dir, server_id)
    if not current["running"]:
        release(root_dir, server_id)
        return {"found": False, "stopped": True, "graceful": True, "killed": False, "pid": None}
    process = psutil.Process(int(current["pid"]))
    children = process.children(recursive=True)
    for item in [*children, process]:
        with contextlib.suppress(psutil.Error):
            item.terminate()
    _, alive = psutil.wait_procs([process, *children], timeout=max(0.1, float(grace_seconds)))
    killed = bool(alive)
    for item in alive:
        with contextlib.suppress(psutil.Error):
            item.kill()
    if alive:
        psutil.wait_procs(alive, timeout=3)
    stopped = not process_matches(current["pid"], server_id, current.get("create_time"))
    if stopped:
        release(root_dir, server_id)
    return {
        "found": True,
        "stopped": stopped,
        "graceful": stopped and not killed,
        "killed": killed,
        "pid": current["pid"],
    }


def wait_until_claimed(root_dir, server_id, pid, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_state(root_dir, server_id)
        if (
            state.get("state") == "running"
            and state.get("pid") == int(pid)
            and process_matches(pid, server_id, state.get("process_create_time"))
        ):
            return state
        time.sleep(0.05)
    return None
