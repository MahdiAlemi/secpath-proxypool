import contextlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from proxy_monitor.lifecycle import atomic_write_json, validate_monitor_id

_lock = threading.RLock()


def get_progress_dir(root_dir):
    path = Path(root_dir).resolve() / "progress"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _progress_path(root_dir, monitor_id):
    validate_monitor_id(monitor_id)
    return Path(get_progress_dir(root_dir)) / f"{monitor_id}.json"


def write_progress(root_dir, monitor_id, data):
    payload = dict(data or {})
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        atomic_write_json(_progress_path(root_dir, monitor_id), payload, indent=None)


def read_progress(root_dir, monitor_id):
    path = _progress_path(root_dir, monitor_id)
    try:
        with _lock, open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def delete_progress(root_dir, monitor_id):
    with _lock, contextlib.suppress(FileNotFoundError):
        os.remove(_progress_path(root_dir, monitor_id))


def cleanup_old_progress(root_dir, max_age_hours=24):
    progress_dir = Path(get_progress_dir(root_dir))
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    with _lock:
        for path in progress_dir.glob("monitor_*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
