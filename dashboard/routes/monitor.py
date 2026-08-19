import contextlib
import getpass
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
from flask import Blueprint, Response, jsonify, request
from sqlalchemy import case, func, or_

from dashboard.config import load_monitors_config
from dashboard.decorators import login_required, require_permission
from dashboard.security import api_error, validate_public_http_url
from dashboard.utils.helpers import log
from database import MonitorSession, MonitorTested, Proxy, db
from proxy_monitor.lifecycle import (
    MonitorAlreadyRunning,
    active_claim,
    abandon_reservation,
    activate_claim,
    clear_action,
    create_monitor_record,
    delete_monitor_record,
    find_runtime_process,
    process_snapshot,
    read_claim,
    remove_runtime_files,
    rename_monitor_record,
    request_action,
    reserve_start,
    terminate_process,
    update_monitor_registry,
    utcnow_iso,
    validate_monitor_id,
)
from proxy_monitor.utils.progress import delete_progress, read_progress
from secproxy_core import monitor_service as monitor_ops
from secproxy_core.errors import ConflictError


monitor_bp = Blueprint("monitor", __name__)


from secproxy_core.monitor import (
    _bounded_int,
    _candidate_preview,
    _log_path,
    _mark_interrupted,
    _monitor_id,
    _normalize_profile,
    _proxy_count,
    _remove_service_for_record,
    _root_dir,
    _runtime_status,
    _spawn_monitor,
    _stop_monitor,
)

@monitor_bp.route("/api/monitor", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_status():
    registry = load_monitors_config()
    monitor_ids = [mid for mid in registry if _monitor_id(mid)]
    with db.session() as session:
        sessions = {
            item.id: item
            for item in session.query(MonitorSession).filter(MonitorSession.id.in_(monitor_ids)).all()
        } if monitor_ids else {}
        monitors = {}
        for monitor_id in monitor_ids:
            record = registry[monitor_id]
            status = _runtime_status(monitor_id, record)
            monitor_session = sessions.get(monitor_id)
            if not status.get("running") and not status.get("starting") and record.get("pid"):
                _mark_interrupted(monitor_id, record, monitor_session)

            progress = read_progress(_root_dir(), monitor_id)
            if not progress and monitor_session:
                total = monitor_session.total_proxies or 0
                tested = monitor_session.tested_count or 0
                progress = {
                    "state": monitor_session.status,
                    "completed": monitor_session.status == "completed",
                    "paused": monitor_session.status == "paused",
                    "stopped": monitor_session.status == "stopped",
                    "total": total,
                    "tested": tested,
                    "alive": monitor_session.alive_count or 0,
                    "dead": monitor_session.dead_count or 0,
                    "other": monitor_session.other_count or 0,
                    "percent": int((tested / total) * 100) if total else 0,
                }

            monitors[monitor_id] = {
                **status,
                "config": record.get("config", {}),
                "proxy_count": record.get("proxy_count", 0),
                "start_time": record.get("start_time"),
                "end_time": record.get("end_time"),
                "service": record.get("service"),
                "name": record.get("name"),
                "session_status": monitor_session.status if monitor_session else record.get("last_state"),
                "last_state": record.get("last_state"),
                "last_error": record.get("last_error"),
                "progress": progress,
            }
    return jsonify({"monitors": monitors})




@monitor_bp.route("/api/monitor/preview", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_preview():
    try:
        profile, _safe = _normalize_profile(request.get_json(silent=True) or {})
        return jsonify({"success": True, "preview": _candidate_preview(profile)})
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_monitor_config")
    except Exception:
        return api_error("Could not preview monitor candidates", 500, "monitor_preview_failed")


@monitor_bp.route("/api/monitor/<monitor_id>/results", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_results(monitor_id):
    monitor_id = _monitor_id(monitor_id)
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    if monitor_id not in load_monitors_config():
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    try:
        limit = _bounded_int(request.args.get("limit"), name="limit", minimum=1, maximum=100, default=25)
        with db.session() as session:
            rows = (
                session.query(MonitorTested, Proxy)
                .join(Proxy, Proxy.id == MonitorTested.proxy_id)
                .filter(MonitorTested.session_id == monitor_id)
                .order_by(MonitorTested.tested_at.desc(), Proxy.id.desc())
                .limit(limit)
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
        return jsonify({"monitor_id": monitor_id, "session": session_data, "results": results})
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_limit")
    except Exception:
        return api_error("Could not load monitor results", 500, "monitor_results_failed")


@monitor_bp.route("/api/monitor/create", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_create():
    try:
        result = monitor_ops.create_monitor(request.get_json(silent=True) or {})
        log(f"Monitor profile created: {result['monitor_id']}")
        return jsonify({"success": True, "monitor_id": result["monitor_id"], "proxy_count": result["proxy_count"]}), 201
    except FileExistsError:
        return api_error("A monitor profile with this name already exists", 409, "monitor_exists")
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_monitor_config")
    except Exception:
        return api_error("Could not create monitor profile", 500, "monitor_create_failed")


@monitor_bp.route("/api/monitor/update", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_update():
    data = request.get_json(silent=True) or {}
    monitor_id = _monitor_id(data.get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.update_monitor(monitor_id, data)
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        log(f"Monitor profile updated: {result['monitor_id']}")
        return jsonify({"success": True, "monitor_id": result["monitor_id"], "proxy_count": result["proxy_count"]})
    except FileExistsError:
        return api_error("A monitor profile with this name already exists", 409, "monitor_exists")
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_monitor_config")
    except ConflictError as exc:
        return api_error(str(exc), 409, "monitor_conflict")
    except Exception:
        return api_error("Could not update monitor profile", 500, "monitor_update_failed")


@monitor_bp.route("/api/monitor/start", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_start():
    data = request.get_json(silent=True) or {}
    monitor_id = _monitor_id(data.get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.start_monitor(monitor_id)
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        log(f"Monitor started: {monitor_id} pid={result['pid']}")
        return jsonify({"success": True, "monitor_id": monitor_id, "pid": result["pid"], "service_created": bool(result.get("service"))})
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except ConflictError as exc:
        code = "monitor_empty" if "No proxies match" in str(exc) else "monitor_running"
        return api_error(str(exc), 409, code)
    except Exception:
        return api_error("Failed to start monitor", 500, "monitor_start_failed")


@monitor_bp.route("/api/monitor/stop", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_stop():
    data = request.get_json(silent=True) or {}
    monitor_id = data.get("monitor_id")
    if monitor_id:
        monitor_id = _monitor_id(monitor_id)
        if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
        try:
            result = monitor_ops.stop_monitor(monitor_id, action="stop")
            if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
            log(f"Monitor stopped: {monitor_id}")
            return jsonify({"success": True, **result})
        except Exception:
            return api_error("Could not stop monitor", 500, "monitor_stop_failed")
    results = monitor_ops.stop_all_monitors()
    return jsonify({"success": not any("error" in item for item in results.values()), "results": results})


@monitor_bp.route("/api/monitor/pause", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_pause():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.stop_monitor(monitor_id, action="pause")
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        return jsonify({"success": True, **result})
    except ConflictError as exc:
        return api_error(str(exc), 409, "monitor_not_running")
    except Exception:
        return api_error("Could not pause monitor", 500, "monitor_pause_failed")


@monitor_bp.route("/api/monitor/resume", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_resume():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.resume_monitor(monitor_id)
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        return jsonify({"success": True, "monitor_id": monitor_id, "pid": result["pid"]})
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except ConflictError as exc:
        code = "monitor_running" if "already running" in str(exc).lower() else "monitor_not_paused"
        return api_error(str(exc), 409, code)
    except Exception:
        return api_error("Failed to resume monitor", 500, "monitor_resume_failed")


@monitor_bp.route("/api/monitor/remove-service", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_remove_service():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.remove_service(monitor_id)
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        return jsonify({"success": True, "monitor_id": monitor_id})
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except ConflictError as exc:
        return api_error(str(exc), 409, "service_not_found")
    except Exception:
        return api_error("Could not remove monitor service", 500, "service_remove_failed")


@monitor_bp.route("/api/monitor/delete", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_delete():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id: return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    try:
        result = monitor_ops.delete_monitor(monitor_id)
        if result is None: return api_error("Monitor profile not found", 404, "monitor_not_found")
        log(f"Monitor profile deleted: {monitor_id}")
        return jsonify({"success": True, "monitor_id": monitor_id})
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except Exception:
        return api_error("Could not delete monitor profile", 500, "monitor_delete_failed")


@monitor_bp.route("/api/monitor/log", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_log():
    monitor_id = request.args.get("monitor_id", "monitor_all")
    if monitor_id != "monitor_all" and not _monitor_id(monitor_id):
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    path = os.path.join(_root_dir(), f"{monitor_id}.log")
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-100:]
    return jsonify({"lines": lines, "monitor_id": monitor_id})


@monitor_bp.route("/api/monitor/log/stream", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_log_stream():
    monitor_id = request.args.get("monitor_id", "monitor_all")
    if monitor_id != "monitor_all" and not _monitor_id(monitor_id):
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    path = os.path.join(_root_dir(), f"{monitor_id}.log")

    def generate():
        last_position = 0
        try:
            while True:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(last_position)
                        for line in handle:
                            yield f"data: {line.rstrip()}\n\n"
                        last_position = handle.tell()
                yield ": keep-alive\n\n"
                time.sleep(1)
        except GeneratorExit:
            return

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
