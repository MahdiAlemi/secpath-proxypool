import os
import subprocess
import sys
import ipaddress
import contextlib
from pathlib import Path

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
from secproxy_core import server_service as server_ops
from secproxy_core.errors import ConflictError

server_bp = Blueprint('server', __name__)



from secproxy_core.server import (
    _candidate_query as _core_candidate_query,
    _candidate_snapshot as _core_candidate_snapshot,
    _is_local_bind,
    _normalize_server_config,
    _parse_port,
    _project_root,
    _public_server_config,
    _remove_runtime_profile,
    _server_log_tail,
)


def _candidate_query(session, data):
    # Web UI preserves its authenticated per-user inventory scope.
    return _core_candidate_query(session, data, scope_query=apply_proxy_scope)


def _candidate_snapshot(session, data, *, sample_limit=5):
    # Web UI serializer/scoping remain web-specific; filtering is shared core.
    return _core_candidate_snapshot(
        session,
        data,
        sample_limit=sample_limit,
        scope_query=apply_proxy_scope,
        serializer=public_proxy_dict,
    )

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




@server_bp.route("/api/server/<int:port>", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_detail(port):
    from database import db

    port_key = str(port)
    config = load_servers_config()
    profile = config.get(port_key)
    if not profile:
        return api_error(f"No server profile on port {port_key}", 404, "not_found")

    saved = profile.get("config", {})
    try:
        normalized = _normalize_server_config(saved, existing=saved)
    except ValueError:
        normalized = dict(saved)
    status = get_server_status(port_key)
    with db.session() as session:
        candidates = _candidate_snapshot(session, normalized, sample_limit=6)

    bind = str(normalized.get("bind") or "127.0.0.1")
    protocol = str(normalized.get("protocol") or profile.get("protocol") or "http")
    safe_host = f"[{bind}]" if ":" in bind and not bind.startswith("[") else bind
    endpoint = f"{protocol}://{safe_host}:{port_key}"
    return jsonify({
        "success": True,
        "port": port_key,
        "running": bool(status.get("running")),
        "pid": status.get("pid"),
        "process_create_time": status.get("process_create_time"),
        "protocol": protocol,
        "config": _public_server_config(normalized),
        "endpoint": {
            "uri": endpoint,
            "host": bind,
            "port": port,
            "scope": "local" if _is_local_bind(bind) else "network",
            "has_auth": bool(normalized.get("username") or normalized.get("password")),
        },
        "candidates": candidates,
        "log": {"lines": _server_log_tail(port_key, limit=80)},
    })


@server_bp.route("/api/server/preview-candidates", methods=["POST"])
@login_required
@require_permission("server.view")
def api_server_preview_candidates():
    """Preview how many proxies match a server profile before creating it."""
    from database import db

    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        existing = None
        existing_port = data.get("existing_port")
        if existing_port not in (None, ""):
            existing_key = str(_parse_port(existing_port))
            existing_profile = load_servers_config().get(existing_key)
            if not existing_profile:
                return api_error(f"No server profile on port {existing_key}", 404, "not_found")
            existing = existing_profile.get("config", {})
        data = _normalize_server_config(data, existing=existing)
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    with db.session() as session:
        snapshot = _candidate_snapshot(session, data, sample_limit=6)

    warnings = []
    if snapshot["total"] == 0:
        warnings.append("No proxies match this server profile. Loosen filters or run a monitor first.")
    if data.get("require_telegram") and not data.get("require_remote_dns"):
        warnings.append("Telegram routing usually needs remote DNS; enable the Remote DNS requirement.")
    if not data.get("require_web_https") and data.get("use_case") in {"web", "telegram"}:
        warnings.append("This preset normally requires verified HTTPS capability.")
    if not _is_local_bind(data.get("bind")) and not data.get("username") and not data.get("allow_public_no_auth"):
        warnings.append("A network listener needs authentication or an explicit public no-auth override.")

    return jsonify({"success": True, **snapshot, "warnings": warnings})


@server_bp.route("/api/server/create", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_create():
    data = _json_object()
    if data is None: return api_error("A JSON object is required", 400, "invalid_json")
    try:
        result = server_ops.create_server(data, include_candidates=False); port=str(result["port"])
        log(f"Server profile created on port {port}")
        return jsonify({"success": True, "port": port, "protocol": result["protocol"]}), 201
    except ValueError as exc: return api_error(str(exc), 400, "invalid_server_config")
    except ConflictError as exc: return api_error(str(exc), 409, "duplicate_server")
    except Exception: return api_error("Could not create server profile", 500, "server_create_failed")


@server_bp.route("/api/server/update", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_update():
    data = _json_object()
    if data is None: return api_error("A JSON object is required", 400, "invalid_json")
    try:
        port=str(_parse_port(data.get("port",8080))); result=server_ops.update_server(port,data,include_candidates=False)
        if result is None: return api_error(f"No server profile on port {port}",404,"not_found")
        log(f"Server profile updated on port {port}")
        return jsonify({"success":True,"port":port,"protocol":result["protocol"],"was_running":bool(result.get("was_running"))})
    except ValueError as exc: return api_error(str(exc),400,"invalid_server_config")
    except ConflictError as exc: return api_error(str(exc),409,"server_stop_failed")
    except Exception: return api_error("Could not update server profile",500,"server_update_failed")


@server_bp.route("/api/server/start", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_start():
    data = _json_object()
    if data is None: return api_error("A JSON object is required",400,"invalid_json")
    try:
        port=str(_parse_port(data.get("port",8080))); result=server_ops.start_server(port,overrides=data,allow_create=True,include_candidates=False)
        if result is None: return api_error(f"No server profile on port {port}",404,"not_found")
        log(f"Server started on port {port} with PID {result.get('pid')}")
        return jsonify({"success":True,"pid":result.get("pid"),"port":port})
    except ValueError as exc: return api_error(str(exc),400,"invalid_server_config")
    except ConflictError as exc: return api_error(str(exc),409,"server_running")
    except Exception: return api_error("Could not start server",500,"server_start_failed")


@server_bp.route("/api/server/stop", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_stop():
    data = _json_object()
    if data is None: return api_error("A JSON object is required",400,"invalid_json")
    try:
        port=str(_parse_port(data.get("port"))); result=server_ops.stop_server(port)
        if result is None: return api_error(f"No server profile on port {port}",404,"not_found")
        log(f"Server stopped on port {port}")
        return jsonify({"success":True,"port":port,"graceful":result["graceful"],"killed":result["killed"]})
    except ValueError as exc: return api_error(str(exc),400,"invalid_server_config")
    except ConflictError as exc: return api_error(str(exc),409,"server_stop_failed")
    except Exception: return api_error("Could not stop server",500,"server_stop_failed")


@server_bp.route("/api/server/delete", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_delete():
    data = _json_object()
    if data is None: return api_error("A JSON object is required",400,"invalid_json")
    try:
        port=str(_parse_port(data.get("port"))); result=server_ops.delete_server(port)
        if result is None: return api_error(f"No server profile on port {port}",404,"not_found")
        log(f"Server profile deleted on port {port}")
        return jsonify({"success":True,"port":port})
    except ValueError as exc: return api_error(str(exc),400,"invalid_server_config")
    except ConflictError as exc: return api_error(str(exc),409,"server_running")
    except Exception: return api_error("Could not delete server profile",500,"server_delete_failed")


@server_bp.route("/api/server/log", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_log():
    try:
        port = str(_parse_port(request.args.get("port", "8080")))
        limit = int(request.args.get("limit", 100))
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
    except (TypeError, ValueError) as exc:
        return api_error(str(exc), 400, "invalid_server_config")
    if port not in load_servers_config():
        return api_error(f"No server profile on port {port}", 404, "not_found")
    return jsonify({"lines": _server_log_tail(port, limit=limit), "port": port})
