import os
import subprocess
import sys
import ipaddress
import contextlib

from flask import Blueprint, request, jsonify

from dashboard.decorators import login_required, require_permission
from dashboard.proxy_scope import apply_proxy_scope, public_proxy_dict
from dashboard.security import api_error
from dashboard.config import PROTOCOLS, ROTATE_MODES, load_servers_config, save_servers_config
from dashboard.utils.process import get_server_status
from proxy_server.lifecycle import (
    atomic_write_json as write_runtime_json,
    profile_path as server_profile_path,
    release as release_server_claim,
    reserve_start as reserve_server_start,
    snapshot as server_snapshot,
    terminate as terminate_server,
    wait_until_claimed,
)
from dashboard.utils.helpers import log

server_bp = Blueprint('server', __name__)


_BOOL_FIELDS = {
    "insecure_upstream",
    "require_web_https",
    "require_remote_dns",
    "require_telegram",
    "readonly",
    "allow_public_no_auth",
}
_OPTIONAL_BOOL_TEXT_FIELDS = {"mobile", "proxy", "hosting"}
_TEXT_FIELDS = {
    "auth_required",
    "username",
    "password",
    "certfile",
    "keyfile",
    "sticky_upstream",
    "upstream_protocol",
    "candidate_statuses",
    "countryCodes",
    "regions",
    "cities",
    "orgs",
    "isp",
    "asn",
    "continentCode",
    "zip_codes",
    "timezones",
}


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _parse_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return port


def _parse_bool(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"{field} must be a boolean")


def _is_local_bind(value):
    normalized = str(value or "").strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _normalize_server_config(data, *, existing=None):
    if not isinstance(data, dict):
        raise ValueError("A JSON object is required")
    normalized = dict(existing or {})
    normalized.update(data)

    port = _parse_port(normalized.get("port", 8080))
    protocol = str(normalized.get("protocol", "http")).strip().lower()
    if protocol not in PROTOCOLS:
        raise ValueError("protocol is invalid")
    rotate = str(normalized.get("rotate", "better_cost")).strip().lower()
    if rotate not in ROTATE_MODES:
        raise ValueError("rotate mode is invalid")

    bind = str(normalized.get("bind", "127.0.0.1")).strip()
    if not bind or len(bind) > 255 or any(char.isspace() for char in bind) or "/" in bind or "\\" in bind:
        raise ValueError("bind address is invalid")

    result = {
        "protocol": protocol,
        "bind": bind,
        "port": port,
        "rotate": rotate,
    }

    for field, default, minimum, maximum, cast in (
        ("rotate_interval", 60, 1, 86400, int),
        ("min_cost", 0.0, 0.0, 1_000_000.0, float),
        ("threads", 100, 1, 1000, int),
        ("timeout", 10.0, 1.0, 300.0, float),
        ("header_limit", 65536, 4096, 1048576, int),
    ):
        try:
            number = cast(normalized.get(field, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is invalid") from exc
        if not minimum <= number <= maximum:
            raise ValueError(f"{field} is out of range")
        result[field] = number

    threshold = normalized.get("cost_threshold")
    if threshold not in (None, ""):
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError("cost_threshold is invalid") from exc
        if not 0.0 <= threshold <= 1_000_000.0:
            raise ValueError("cost_threshold is out of range")
        result["cost_threshold"] = threshold
    else:
        result["cost_threshold"] = None

    for field in _BOOL_FIELDS:
        result[field] = _parse_bool(normalized.get(field, False), field)

    for field in _OPTIONAL_BOOL_TEXT_FIELDS:
        value = normalized.get(field)
        if value in (None, ""):
            result[field] = None
        else:
            result[field] = "true" if _parse_bool(value, field) else "false"

    for field in _TEXT_FIELDS:
        value = normalized.get(field)
        if value in (None, ""):
            result[field] = None
            continue
        text = str(value).strip()
        max_length = 255 if field in {"username", "password"} else 2048
        if len(text) > max_length or any(ord(char) < 32 for char in text):
            raise ValueError(f"{field} is invalid")
        result[field] = text

    if data.get("clear_credentials") is True:
        result["username"] = None
        result["password"] = None
    elif existing:
        # The read API intentionally redacts secrets. Blank edit fields preserve
        # existing listener credentials instead of silently disabling auth.
        if data.get("username") in (None, ""):
            result["username"] = existing.get("username")
        if data.get("password") in (None, ""):
            result["password"] = existing.get("password")

    has_username = bool(result.get("username"))
    has_password = bool(result.get("password"))
    if protocol != "socks4" and has_username != has_password:
        raise ValueError("listener username and password must be configured together")
    if protocol == "socks4" and has_password:
        raise ValueError("SOCKS4 listener authentication supports UserID only; leave password empty")
    if bool(result.get("certfile")) != bool(result.get("keyfile")):
        raise ValueError("certfile and keyfile must be configured together")
    if result.get("cost_threshold") is not None and result["cost_threshold"] < result["min_cost"]:
        raise ValueError("cost_threshold cannot be lower than min_cost")
    if not _is_local_bind(bind) and not (has_username or result.get("allow_public_no_auth")):
        raise ValueError(
            "unauthenticated listeners beyond loopback are blocked; configure credentials or explicitly allow public no-auth"
        )

    return result


def _public_server_config(value):
    data = dict(value or {})
    had_credentials = bool(data.get("username") or data.get("password"))
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = had_credentials
    return data


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _remove_runtime_profile(port):
    with contextlib.suppress(FileNotFoundError, OSError, ValueError):
        os.unlink(server_profile_path(_project_root(), str(port)))


@server_bp.route("/api/server", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_status():
    try:
        config = load_servers_config()
        servers = {}
        config_dirty = False
        for port_key, conf in config.items():
            try:
                port = str(_parse_port(port_key))
            except ValueError:
                continue
            try:
                status = get_server_status(port)
                servers[port] = status
                if not status.get("running") and conf.get("pid"):
                    conf["pid"] = None
                    conf["process_create_time"] = None
                    config_dirty = True
                servers[port]["protocol"] = conf.get("protocol", "http")
                servers[port]["config"] = _public_server_config(conf.get("config", {}))
            except Exception:
                servers[port] = {"running": False, "error": "Server status unavailable"}
        if config_dirty:
            save_servers_config(config)
        return jsonify({"servers": servers})
    except Exception:
        return api_error("Could not read server status", 500, "server_status_failed")




@server_bp.route("/api/server/preview-candidates", methods=["POST"])
@login_required
@require_permission("server.view")
def api_server_preview_candidates():
    """Preview how many proxies match a server profile before creating it."""
    from sqlalchemy import or_
    from database import db, Proxy

    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        data = _normalize_server_config(data)
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    with db.session() as session:
        query = apply_proxy_scope(session.query(Proxy))

        statuses = [x.strip() for x in str(data.get("candidate_statuses") or "alive").split(',') if x.strip()]
        if statuses:
            conditions = []
            for st in statuses:
                if st == "untested":
                    conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                else:
                    conditions.append(Proxy.status == st)
            query = query.filter(or_(*conditions))

        if data.get("require_web_https"):
            query = query.filter(Proxy.web_https_ok.is_(True))
        if data.get("require_remote_dns"):
            query = query.filter(Proxy.remote_dns_ok.is_(True))
        if data.get("require_telegram"):
            query = query.filter(Proxy.telegram_ok.is_(True))

        if data.get("upstream_protocol"):
            protocols = [p.strip() for p in str(data.get("upstream_protocol")).split(',') if p.strip()]
            if protocols:
                query = query.filter(Proxy.protocol.in_(protocols))

        text_filters = {
            "countryCodes": Proxy.countryCode,
            "regions": Proxy.regionName,
            "cities": Proxy.city,
            "orgs": Proxy.org,
            "isp": Proxy.isp,
            "asn": Proxy.asn,
            "continentCode": Proxy.continentCode,
            "zip_codes": Proxy.zip,
            "timezones": Proxy.timezone,
        }
        for key, col in text_filters.items():
            raw = data.get(key)
            if raw:
                vals = [v.strip() for v in str(raw).split(',') if v.strip()]
                if vals:
                    query = query.filter(col.in_(vals))

        bool_filters = {"mobile": Proxy.mobile, "proxy": Proxy.proxy, "hosting": Proxy.hosting}
        for key, col in bool_filters.items():
            raw = data.get(key)
            if raw in ("true", "false"):
                query = query.filter(col == (1 if raw == "true" else 0))

        total = query.count()
        by_protocol = {}
        for proto in ["http", "https", "socks4", "socks5"]:
            by_protocol[proto] = query.filter(Proxy.protocol == proto).count()

        samples = [public_proxy_dict(p) for p in query.order_by(Proxy.cost.asc()).limit(5).all()]

    warnings = []
    if total == 0:
        warnings.append("No proxies match this server profile. Loosen filters or run a monitor first.")
    if data.get("require_telegram") and not data.get("require_remote_dns"):
        warnings.append("Telegram preset usually needs remote DNS; consider requiring Remote DNS.")
    if not data.get("require_web_https"):
        warnings.append("HTTPS is not required. This is OK for HTTP scraping, but not recommended for web browsing.")

    return jsonify({"success": True, "total": total, "by_protocol": by_protocol, "samples": samples, "warnings": warnings})


@server_bp.route("/api/server/create", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_create():
    try:
        data = _json_object()
        normalized = _normalize_server_config(data)
        port = str(normalized["port"])
        config = load_servers_config()
        if port in config:
            return api_error(f"A server on port {port} already exists", 409, "duplicate_server")
        config[port] = {"pid": None, "protocol": normalized["protocol"], "config": normalized}
        save_servers_config(config)
        log(f"Server profile created on port {port}")
        return jsonify({"success": True, "port": port, "protocol": normalized["protocol"]}), 201
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    except Exception:
        return api_error("Could not create server profile", 500, "server_create_failed")


@server_bp.route("/api/server/update", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_update():
    try:
        data = _json_object()
        if data is None:
            return api_error("A JSON object is required", 400, "invalid_json")
        port = str(_parse_port(data.get("port", 8080)))
        config = load_servers_config()
        if port not in config:
            return api_error(f"No server profile on port {port}", 404, "not_found")

        existing = config[port].get("config", {})
        normalized = _normalize_server_config(data, existing=existing)
        status = server_snapshot(_project_root(), port)
        if status["running"]:
            termination = terminate_server(_project_root(), port)
            if not termination.get("stopped"):
                return api_error("Server did not stop cleanly; profile was not changed", 409, "server_stop_failed")

        config[port] = {"pid": None, "process_create_time": None, "protocol": normalized["protocol"], "config": normalized}
        save_servers_config(config)
        _remove_runtime_profile(port)
        log(f"Server profile updated on port {port}")
        return jsonify({"success": True, "port": port, "protocol": normalized["protocol"], "was_running": status["running"]})
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    except Exception:
        return api_error("Could not update server profile", 500, "server_update_failed")


@server_bp.route("/api/server/start", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_start():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        port = str(_parse_port(data.get("port", 8080)))
        config = load_servers_config()
        saved = config.get(port, {}).get("config", {})
        source = saved if saved and not data.get("config") and set(data) <= {"port"} else data
        normalized = _normalize_server_config(source, existing=saved or None)
        normalized["port"] = int(port)
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")

    root_dir = _project_root()
    server_path = os.path.join(root_dir, "proxy_server", "app.py")
    log_file = os.path.join(root_dir, f"server_{port}.log")
    profile = server_profile_path(root_dir, port)

    try:
        try:
            token = reserve_server_start(root_dir, port)
        except RuntimeError as exc:
            return api_error(str(exc), 409, "server_running")
        write_runtime_json(profile, normalized, mode=0o600)
        cmd = [
            sys.executable,
            "-u",
            server_path,
            "--server-id",
            port,
            "--claim-token",
            token,
            "--config-file",
            str(profile),
        ]
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "ab", buffering=0) as log_handle:
            proc = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )

        claimed = wait_until_claimed(root_dir, port, proc.pid, timeout=3.0)
        if claimed is None or proc.poll() is not None:
            with contextlib.suppress(Exception):
                terminate_server(root_dir, port, grace_seconds=1)
            _remove_runtime_profile(port)
            return api_error(
                f"Server exited during startup. Check {os.path.basename(log_file)}",
                500,
                "server_start_failed",
            )

        config = load_servers_config()
        config[port] = {
            "pid": proc.pid,
            "process_create_time": claimed.get("process_create_time"),
            "protocol": normalized["protocol"],
            "config": normalized,
        }
        save_servers_config(config)
        log(f"Server started on port {port} with PID {proc.pid}")
        return jsonify({"success": True, "pid": proc.pid, "port": port})
    except Exception:
        release_server_claim(root_dir, port)
        _remove_runtime_profile(port)
        return api_error("Could not start server", 500, "server_start_failed")


@server_bp.route("/api/server/stop", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_stop():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        port = str(_parse_port(data.get("port")))
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")

    config = load_servers_config()
    if port not in config:
        return api_error(f"No server profile on port {port}", 404, "not_found")
    result = terminate_server(_project_root(), port)
    if not result.get("stopped"):
        return api_error("Server did not stop cleanly", 409, "server_stop_failed")
    config[port]["pid"] = None
    config[port]["process_create_time"] = None
    save_servers_config(config)
    _remove_runtime_profile(port)
    log(f"Server stopped on port {port}")
    return jsonify({"success": True, "port": port, "graceful": result["graceful"], "killed": result["killed"]})


@server_bp.route("/api/server/delete", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_delete():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        port = str(_parse_port(data.get("port")))
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")

    config = load_servers_config()
    if port not in config:
        return api_error(f"No server profile on port {port}", 404, "not_found")
    if server_snapshot(_project_root(), port)["running"]:
        return api_error("Server is running. Stop it first.", 409, "server_running")
    del config[port]
    save_servers_config(config)
    release_server_claim(_project_root(), port)
    _remove_runtime_profile(port)
    log(f"Server profile deleted on port {port}")
    return jsonify({"success": True, "port": port})


@server_bp.route("/api/server/log", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_log():
    try:
        port = str(_parse_port(request.args.get("port", "8080")))
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    log_file = os.path.join(root_dir, f"server_{port}.log")
    lines = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()[-100:]
    return jsonify({"lines": lines, "port": port})
