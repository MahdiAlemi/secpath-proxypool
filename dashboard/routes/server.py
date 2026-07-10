import os
import subprocess
import sys
import signal
import time
import psutil

from flask import Blueprint, request, jsonify, Response

from dashboard.decorators import login_required, require_permission
from dashboard.proxy_scope import apply_proxy_scope, public_proxy_dict
from dashboard.security import api_error
from dashboard.config import PROTOCOLS, ROTATE_MODES, load_servers_config, save_servers_config
from dashboard.utils.process import get_server_status
from dashboard.utils.helpers import log

server_bp = Blueprint('server', __name__)


_BOOL_FIELDS = {
    "insecure_upstream",
    "require_web_https",
    "require_remote_dns",
    "require_telegram",
    "readonly",
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

    return result


def _public_server_config(value):
    data = dict(value or {})
    had_credentials = bool(data.get("username") or data.get("password"))
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = had_credentials
    return data


@server_bp.route("/api/server/log/stream", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_log_stream():
    import time
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    log_file = os.path.join(root_dir, "server.log")
    
    def generate():
        last_pos = 0
        while True:
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()
                    for line in new_lines:
                        yield f"data: {line}"
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')


@server_bp.route("/api/server", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_status():
    try:
        config = load_servers_config()
        servers = {}
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
                    save_servers_config(config)
                servers[port]["protocol"] = conf.get("protocol", "http")
                servers[port]["config"] = _public_server_config(conf.get("config", {}))
            except Exception:
                servers[port] = {"running": False, "error": "Server status unavailable"}
        
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
        pid = config[port].get("pid")
        was_running = False
        if pid:
            try:
                was_running = psutil.pid_exists(int(pid))
            except (TypeError, ValueError):
                was_running = False
        if was_running:
            try:
                os.kill(int(pid), signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(int(pid)):
                    os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        config[port] = {"pid": None, "protocol": normalized["protocol"], "config": normalized}
        save_servers_config(config)
        log(f"Server profile updated on port {port}")
        return jsonify({"success": True, "port": port, "protocol": normalized["protocol"], "was_running": was_running})
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
        data = normalized
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")

    if port in config and config[port].get("pid"):
        pid = config[port]["pid"]
        try:
            pid_int = int(pid)
            if psutil.pid_exists(pid_int):
                os.kill(pid_int, signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(pid_int):
                    os.kill(pid_int, signal.SIGKILL)
        except (TypeError, ValueError, ProcessLookupError, PermissionError):
            pass

    config.pop(port, None)
    save_servers_config(config)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    server_path = os.path.join(root_dir, "proxy_server", "app.py")
    log_file = os.path.join(root_dir, f"server_{port}.log")

    args_list = [
        "--protocol", data.get("protocol", "http"),
        "--bind", data.get("bind", "0.0.0.0"),
        "--listen_port", str(data.get("port", 8080)),
        "--rotate", data.get("rotate", "better_cost"),
    ]

    if data.get("rotate_interval"):
        args_list.extend(["--rotate_interval", str(data["rotate_interval"])])
    if data.get("min_cost"):
        args_list.extend(["--min_cost", str(data["min_cost"])])
    if data.get("cost_threshold"):
        args_list.extend(["--cost_threshold", str(data["cost_threshold"])])

    if data.get("auth_required"):
        args_list.extend(["--auth_required", data["auth_required"]])
    if data.get("username") and data.get("password"):
        args_list.extend(["--username", data["username"], "--password", data["password"]])

    if data.get("certfile"):
        args_list.extend(["--certfile", data["certfile"]])
    if data.get("keyfile"):
        args_list.extend(["--keyfile", data["keyfile"]])

    if data.get("insecure_upstream"):
        args_list.append("--insecure_upstream")
    if data.get("sticky_upstream"):
        args_list.extend(["--sticky_upstream", data["sticky_upstream"]])
    if data.get("upstream_protocol"):
        args_list.extend(["--upstream_protocol", data["upstream_protocol"]])
    if data.get("candidate_statuses"):
        args_list.extend(["--candidate_statuses", data["candidate_statuses"]])
    if data.get("require_web_https"):
        args_list.append("--require_web_https")
    if data.get("require_remote_dns"):
        args_list.append("--require_remote_dns")
    if data.get("require_telegram"):
        args_list.append("--require_telegram")

    if data.get("countryCodes"):
        args_list.extend(["--countryCodes", data["countryCodes"]])
    if data.get("regions"):
        args_list.extend(["--regions", data["regions"]])
    if data.get("cities"):
        args_list.extend(["--cities", data["cities"]])
    if data.get("orgs"):
        args_list.extend(["--orgs", data["orgs"]])
    if data.get("isp"):
        args_list.extend(["--isp", data["isp"]])
    if data.get("asn"):
        args_list.extend(["--asn", data["asn"]])
    if data.get("continentCode"):
        args_list.extend(["--continentCode", data["continentCode"]])
    if data.get("zip_codes"):
        args_list.extend(["--zip_codes", data["zip_codes"]])
    if data.get("timezones"):
        args_list.extend(["--timezones", data["timezones"]])
    if data.get("mobile"):
        args_list.extend(["--mobile", data["mobile"]])
    if data.get("proxy"):
        args_list.extend(["--proxy", data["proxy"]])
    if data.get("hosting"):
        args_list.extend(["--hosting", data["hosting"]])

    if data.get("readonly") is not None:
        if data["readonly"]:
            args_list.append("--readonly")

    try:
        # Security: never build a shell command from user-controlled values.
        # Popen(list, shell=False) passes each argument literally and prevents shell injection.
        cmd = [sys.executable, "-u", server_path] + args_list
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        log_handle = open(log_file, "ab", buffering=0)
        proc = subprocess.Popen(
            cmd,
            cwd=root_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        actual_pid = str(proc.pid)
        time.sleep(0.5)
        if proc.poll() is None:
            config = load_servers_config()
            config[port] = {"pid": actual_pid, "protocol": data.get("protocol", "http"), "config": data}
            save_servers_config(config)
            log(f"Server started on port {port} with PID {actual_pid}")
            return jsonify({"success": True, "pid": int(actual_pid), "port": port})
        return jsonify({"success": False, "error": f"Server exited immediately. Check {os.path.basename(log_file)}"})
    except Exception:
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
    
    if port in config:
        pid = config[port].get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(int(pid)):
                    os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
        config[port]["pid"] = None
        save_servers_config(config)
        log(f"Server stopped on port {port}")
        return jsonify({"success": True, "port": port})
    return api_error(f"No server running on port {port}", 404, "not_found")


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
    
    if port in config:
        pid = config[port].get("pid")
        if pid:
            try:
                if psutil.pid_exists(int(pid)):
                    return api_error("Server is running. Stop it first.", 409, "server_running")
            except Exception:
                pass
        del config[port]
        save_servers_config(config)
        log(f"Server profile deleted on port {port}")
        return jsonify({"success": True, "port": port})
    return api_error(f"No server profile on port {port}", 404, "not_found")


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
