from __future__ import annotations
import contextlib, fcntl, json, os, tempfile, threading
from pathlib import Path
from typing import Any
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ["http", "https", "socks4", "socks5"]
ROTATE_MODES = ["fixed", "per_connection", "better_cost", "time", "sticky"]
SERVERS_CONFIG_FILE = PROJECT_ROOT / ".servers.json"
MONITORS_CONFIG_FILE = PROJECT_ROOT / ".monitors.json"
_json_lock = threading.RLock()
@contextlib.contextmanager
def _file_lock(path: Path):
    lock_path = Path(str(path) + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
def _load_json_config(path: Path) -> dict[str, Any]:
    with _json_lock, _file_lock(path):
        try:
            payload=json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError): return {}
def _save_json_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _json_lock, _file_lock(path):
        fd,temp_path=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=str(path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle:
                json.dump(payload,handle,indent=2); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_path,path); os.chmod(path,0o600)
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(temp_path)
def load_monitors_config(): return _load_json_config(MONITORS_CONFIG_FILE)
def save_monitors_config(config): _save_json_config(MONITORS_CONFIG_FILE, config)
def load_servers_config(): return _load_json_config(SERVERS_CONFIG_FILE)
def save_servers_config(config): _save_json_config(SERVERS_CONFIG_FILE, config)
