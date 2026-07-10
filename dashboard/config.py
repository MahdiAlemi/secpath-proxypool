import os
import json
import secrets
import contextlib
import fcntl
import tempfile
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "proxies.db")
PROTOCOLS = ["http", "https", "socks4", "socks5"]
ROTATE_MODES = ["fixed", "per_connection", "better_cost", "time", "sticky"]

_configured_secret = os.environ.get("JWT_SECRET")
JWT_SECRET = _configured_secret or secrets.token_hex(32)
JWT_SECRET_CONFIGURED = bool(_configured_secret)
JWT_EXPIRY_HOURS = max(1, int(os.environ.get("JWT_EXPIRY_HOURS", "24")))

HIDDEN_COLS = {
    "id", "protocol", "port", "last_alive", "last_fail", "continent", "country",
    "zip", "lat", "lon", "asname", "last_geo", "resolved_ip", "last_checked",
    "district", "timezone", "isp", "org", "region", "username", "password"
}

_legacy_admin_password = os.environ.get("DASHBOARD_PASSWORD", "").strip()
USERS = {"admin": _legacy_admin_password} if _legacy_admin_password else {}

ROLE_PERMISSIONS = {
    'admin': ['*'],
    'superadmin': [
        'proxies.view', 'proxies.add', 'proxies.delete', 'proxies.import', 'proxies.export', 'proxies.credentials', 'proxies.test', 'proxies.edit', 'proxies.columns', 'proxies.search', 'proxies.refresh',
        'monitor.view', 'monitor.control',
        'server.view', 'server.control',
        'stats.view',
        'settings.view', 'settings.edit',
        'users.manage'
    ],
    'user': [
        'proxies.view', 'server.view'
    ]
}

ALL_PERMISSIONS = [
    'proxies.view', 'proxies.add', 'proxies.delete', 'proxies.import', 'proxies.export', 'proxies.credentials', 'proxies.test', 'proxies.edit', 'proxies.columns', 'proxies.search', 'proxies.refresh',
    'monitor.view', 'monitor.control',
    'server.view', 'server.control',
    'stats.view',
    'settings.view', 'settings.edit',
    'users.manage'
]

monitor_pid_file = os.path.join(PROJECT_ROOT, ".monitor.pid")
server_pid_file = os.path.join(PROJECT_ROOT, ".server.pid")
servers_config_file = os.path.join(PROJECT_ROOT, ".servers.json")
monitors_config_file = os.path.join(PROJECT_ROOT, ".monitors.json")
log_file = os.path.join(PROJECT_ROOT, "dashboard.log")


_json_lock = threading.RLock()


@contextlib.contextmanager
def _file_lock(path):
    lock_path = f"{path}.lock"
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_json_config(path):
    with _json_lock, _file_lock(path):
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}


def _save_json_config(path, payload):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    with _json_lock, _file_lock(path):
        fd, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def load_monitors_config():
    return _load_json_config(monitors_config_file)


def save_monitors_config(config):
    _save_json_config(monitors_config_file, config)


def load_servers_config():
    return _load_json_config(servers_config_file)


def save_servers_config(config):
    _save_json_config(servers_config_file, config)
