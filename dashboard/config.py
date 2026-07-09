import os
import json
import secrets

DB_PATH = "proxies.db"
PROTOCOLS = ["http", "https", "socks4", "socks5"]
ROTATE_MODES = ["fixed", "per_connection", "better_cost", "time", "sticky"]

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = 24

HIDDEN_COLS = {
    "id", "protocol", "port", "last_alive", "last_fail", "continent", "country",
    "zip", "lat", "lon", "asname", "last_geo", "resolved_ip", "last_checked",
    "district", "timezone", "isp", "org", "region", "username", "password"
}

USERS = {"admin": os.environ.get("DASHBOARD_PASSWORD", "password123")}

ROLE_PERMISSIONS = {
    'admin': ['*'],
    'superadmin': [
        'proxies.view', 'proxies.add', 'proxies.delete', 'proxies.import', 'proxies.export', 'proxies.test', 'proxies.edit', 'proxies.columns', 'proxies.search', 'proxies.refresh',
        'monitor.view', 'monitor.control',
        'server.view', 'server.control',
        'stats.view',
        'settings.view', 'settings.edit'
    ],
    'user': [
        'proxies.view', 'server.view'
    ]
}

ALL_PERMISSIONS = [
    'proxies.view', 'proxies.add', 'proxies.delete', 'proxies.import', 'proxies.export', 'proxies.test', 'proxies.edit', 'proxies.columns', 'proxies.search', 'proxies.refresh',
    'monitor.view', 'monitor.control',
    'server.view', 'server.control',
    'stats.view',
    'settings.view', 'settings.edit',
    'users.manage'
]

monitor_pid_file = ".monitor.pid"
server_pid_file = ".server.pid"
servers_config_file = ".servers.json"
monitors_config_file = ".monitors.json"
log_file = "dashboard.log"


def load_monitors_config():
    if os.path.exists(monitors_config_file):
        try:
            with open(monitors_config_file) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_monitors_config(config):
    with open(monitors_config_file, "w") as f:
        json.dump(config, f)


def load_servers_config():
    if os.path.exists(servers_config_file):
        try:
            with open(servers_config_file) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_servers_config(config):
    with open(servers_config_file, "w") as f:
        json.dump(config, f)
