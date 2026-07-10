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
from sqlalchemy import or_

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


monitor_bp = Blueprint("monitor", __name__)

_ALLOWED_PROTOCOLS = {"http", "https", "socks4", "socks5"}
_ALLOWED_STATUSES = {
    "untested",
    "alive",
    "soft",
    "flaky",
    "cooling",
    "dead",
    "revived",
    "semi-revived",
}
_ALLOWED_RUN_MODES = {"once", "infinite", "restart", "schedule", "custom"}
_SCHEDULE_DAY_NAMES = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_SCHEDULE_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_SERVICE_RE = re.compile(r"^proxy-monitor-[a-z0-9_-]{1,80}$")


def _root_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _monitor_id(value):
    try:
        return validate_monitor_id(value)
    except ValueError:
        return None


def _bounded_int(value, *, name, minimum, maximum, default=None):
    if value in (None, "") and default is not None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _normalize_csv(value, allowed, *, name):
    if value in (None, ""):
        return ""
    values = []
    for item in str(value).split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if normalized not in allowed:
            raise ValueError(f"Unsupported {name}: {normalized}")
        if normalized not in values:
            values.append(normalized)
    return ",".join(values)


def _normalize_schedule_days(value):
    normalized = str(value or "daily").strip().lower()
    if normalized in {"daily", "weekdays", "weekends"}:
        return normalized
    values = []
    for item in normalized.split(","):
        item = item.strip()
        if item not in _SCHEDULE_DAY_NAMES:
            raise ValueError("schedule_days must be daily, weekdays, weekends, or mon..sun")
        if item not in values:
            values.append(item)
    if not values:
        raise ValueError("schedule_days is required")
    return ",".join(values)


def _normalize_check_urls(value):
    if value in (None, ""):
        return ""
    urls = [item.strip() for item in str(value).split(",") if item.strip()]
    if len(urls) > 5:
        raise ValueError("At most 5 check URLs are allowed")
    validated = []
    for url in urls:
        if len(url) > 500:
            raise ValueError("Check URL is too long")
        # Reuse the SSRF-safe resolver introduced in the security phase.
        validated.append(validate_public_http_url(url))
    return ",".join(validated)


def _safe_name(name):
    value = re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower().strip("-")
    if not value:
        raise ValueError("Profile name must contain at least one letter or number")
    return value


def _normalize_profile(data, previous=None):
    previous = previous or {}
    name = str(data.get("name", previous.get("name", "")) or "").strip()
    if not name:
        raise ValueError("Profile name is required")
    if len(name) > 50:
        raise ValueError("Profile name must be 50 characters or less")

    run_mode = str(data.get("run_mode", previous.get("run_mode", "once")) or "once").strip().lower()
    if run_mode not in _ALLOWED_RUN_MODES:
        raise ValueError("Unsupported run mode")

    schedule_time = str(data.get("schedule_time", previous.get("schedule_time", "")) or "").strip()
    if run_mode == "schedule":
        schedule_time = schedule_time or "00:00"
        if not _SCHEDULE_TIME_RE.fullmatch(schedule_time):
            raise ValueError("schedule_time must use HH:MM in 24-hour format")
    elif schedule_time and not _SCHEDULE_TIME_RE.fullmatch(schedule_time):
        raise ValueError("schedule_time must use HH:MM in 24-hour format")

    geo = str(data.get("geo", previous.get("geo", "true"))).strip().lower()
    if geo not in {"true", "false"}:
        raise ValueError("geo must be true or false")
    create_service = str(data.get("create_service", previous.get("create_service", "no"))).strip().lower()
    if create_service not in {"yes", "no"}:
        raise ValueError("create_service must be yes or no")

    profile = {
        "name": name,
        "protocol": _normalize_csv(data.get("protocol", previous.get("protocol", "")), _ALLOWED_PROTOCOLS, name="protocol"),
        "status": _normalize_csv(data.get("status", previous.get("status", "")), _ALLOWED_STATUSES, name="status"),
        "check_urls": _normalize_check_urls(data.get("check_urls", previous.get("check_urls", ""))),
        "threads": _bounded_int(data.get("threads", previous.get("threads")), name="threads", minimum=1, maximum=200, default=50),
        "timeout": _bounded_int(data.get("timeout", previous.get("timeout")), name="timeout", minimum=1, maximum=60, default=5),
        "probes": _bounded_int(data.get("probes", previous.get("probes")), name="probes", minimum=1, maximum=5, default=2),
        "run_mode": run_mode,
        "interval": _bounded_int(data.get("interval", previous.get("interval")), name="interval", minimum=10, maximum=86400, default=60),
        "schedule_time": schedule_time,
        "schedule_days": _normalize_schedule_days(data.get("schedule_days", previous.get("schedule_days", "daily"))),
        "custom_every": _bounded_int(data.get("custom_every", previous.get("custom_every")), name="custom_every", minimum=1, maximum=720, default=24),
        "geo": geo,
        "create_service": create_service,
    }
    return profile, _safe_name(name)


def _filtered_proxy_query(session, saved_config):
    query = session.query(Proxy)
    protocols = [item for item in str(saved_config.get("protocol") or "").split(",") if item]
    if protocols:
        query = query.filter(Proxy.protocol.in_(protocols))
    statuses = [item for item in str(saved_config.get("status") or "").split(",") if item]
    if statuses:
        conditions = []
        for status in statuses:
            if status == "untested":
                conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
            else:
                conditions.append(Proxy.status == status)
        if conditions:
            query = query.filter(or_(*conditions))
    return query


def _proxy_count(saved_config):
    with db.session() as session:
        return _filtered_proxy_query(session, saved_config).count()


def _build_args(saved_config, monitor_id, start_token):
    root_dir = _root_dir()
    monitor_path = os.path.join(root_dir, "proxy_monitor", "app.py")
    args = [sys.executable, "-u", monitor_path]
    mapping = (
        ("protocol", "--protocol"),
        ("status", "--status"),
        ("check_urls", "--check-urls"),
        ("threads", "--threads"),
        ("timeout", "--timeout"),
        ("probes", "--probes"),
        ("name", "--name"),
        ("run_mode", "--run-mode"),
        ("interval", "--interval"),
        ("schedule_time", "--schedule-time"),
        ("schedule_days", "--schedule-days"),
        ("custom_every", "--custom-every"),
        ("geo", "--geo"),
    )
    for key, flag in mapping:
        value = saved_config.get(key)
        if value not in (None, ""):
            args.extend([flag, str(value)])
    args.extend(["--monitor-id", monitor_id, "--start-token", start_token])
    return args


def _log_path(monitor_id):
    return os.path.join(_root_dir(), f"{monitor_id}.log")


def _wait_for_claim(monitor_id, *, pid_hint=None, timeout=4.0):
    root_dir = _root_dir()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        claim = active_claim(root_dir, monitor_id)
        if claim and claim.get("state") == "running":
            return claim
        if pid_hint is not None and not psutil.pid_exists(int(pid_hint)):
            break
        time.sleep(0.05)
    return None


def _dashboard_user():
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        return getpass.getuser()


def _service_name(monitor_id):
    name = f"proxy-monitor-{monitor_id.removeprefix('monitor_')}"
    if not _SERVICE_RE.fullmatch(name):
        raise ValueError("Invalid service name")
    return name


def _service_file(service_name):
    if not _SERVICE_RE.fullmatch(service_name or ""):
        raise ValueError("Invalid service name")
    return Path("/etc/systemd/system") / f"{service_name}.service"


def _systemctl(*args, check=True, timeout=30):
    if not shutil.which("systemctl"):
        raise RuntimeError("systemctl is not available")
    result = subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "systemctl failed").strip()[:500]
        raise RuntimeError(detail)
    return result


def _write_service(service_name, args, run_mode):
    if os.geteuid() != 0:
        raise PermissionError("Creating a system service requires the dashboard to run as root")
    root_dir = _root_dir()
    restart = "on-failure" if run_mode != "once" else "no"
    content = "\n".join(
        [
            "[Unit]",
            f"Description=Proxy Pool Monitor - {service_name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"User={_dashboard_user()}",
            f"WorkingDirectory={root_dir}",
            f"ExecStart={' '.join(shlex.quote(item) for item in args)}",
            f"Restart={restart}",
            "RestartSec=5",
            "TimeoutStopSec=20",
            "KillSignal=SIGTERM",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )
    path = _service_file(service_name)
    temp_path = path.with_suffix(".service.tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)
    _systemctl("daemon-reload")
    _systemctl("enable", service_name)


def _spawn_monitor(monitor_id, saved_config):
    root_dir = _root_dir()
    token = reserve_start(root_dir, monitor_id)
    args = _build_args(saved_config, monitor_id, token)
    create_service = saved_config.get("create_service") == "yes"
    service_name = _service_name(monitor_id) if create_service else None
    proc = None
    try:
        if create_service:
            _write_service(service_name, args, saved_config.get("run_mode", "once"))
            _systemctl("restart", service_name)
            claim = _wait_for_claim(monitor_id, timeout=6.0)
            if not claim:
                status = _systemctl("status", service_name, "--no-pager", check=False).stdout[-1000:]
                raise RuntimeError(f"Service did not start the monitor. {status.strip()}")
            pid = int(claim["pid"])
        else:
            log_handle = open(_log_path(monitor_id), "ab", buffering=0)
            try:
                proc = subprocess.Popen(
                    args,
                    cwd=root_dir,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
            finally:
                log_handle.close()
            pid = int(proc.pid)
            claim = _wait_for_claim(monitor_id, pid_hint=pid, timeout=4.0)
            if not claim:
                return_code = proc.poll()
                raise RuntimeError(f"Monitor process exited during startup (code {return_code})")

        update_monitor_registry(
            root_dir,
            monitor_id,
            {
                "pid": str(pid),
                "process_create_time": claim.get("process_create_time"),
                "start_time": utcnow_iso(),
                "end_time": None,
                "service": service_name,
                "last_state": "running",
                "last_error": None,
            },
        )
        return {"pid": pid, "service": service_name}
    except Exception:
        abandon_reservation(root_dir, monitor_id, token)
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(psutil.Error):
                psutil.Process(proc.pid).kill()
        raise


def _runtime_status(monitor_id, record):
    root_dir = _root_dir()
    status = find_runtime_process(root_dir, monitor_id)
    if status["running"]:
        return status

    pid = record.get("pid")
    if pid:
        legacy = process_snapshot(pid, monitor_id, expected_create_time=record.get("process_create_time"))
        if legacy["running"]:
            # Adopt a process started before this lifecycle phase.
            try:
                claim = activate_claim(root_dir, monitor_id, pid=int(pid))
                legacy["create_time"] = claim.get("process_create_time")
            except Exception:
                pass
            return legacy
    claim = read_claim(root_dir, monitor_id)
    return {
        "running": False,
        "starting": bool(claim and claim.get("state") == "starting"),
        "pid": None,
        "memory_mb": 0.0,
        "create_time": None,
    }


def _mark_interrupted(monitor_id, record, session):
    if not record.get("pid"):
        return
    now = utcnow_iso()
    updates = {
        "pid": None,
        "process_create_time": None,
        "end_time": record.get("end_time") or now,
    }
    if session and session.status == "running":
        session.status = "interrupted"
        updates["last_state"] = "interrupted"
    update_monitor_registry(_root_dir(), monitor_id, updates)
    record.update(updates)


def _stop_monitor(monitor_id, action):
    root_dir = _root_dir()
    registry = load_monitors_config()
    record = registry.get(monitor_id)
    if not record:
        raise KeyError(monitor_id)

    # Reconcile/adopt a legacy process before issuing the control request so
    # termination never relies on a stale PID alone.
    _runtime_status(monitor_id, record)
    service_name = record.get("service")
    request_action(root_dir, monitor_id, action)
    if service_name:
        if not _SERVICE_RE.fullmatch(service_name):
            raise RuntimeError("Stored service name is invalid")
        _systemctl("stop", service_name, check=False)
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline and find_runtime_process(root_dir, monitor_id)["running"]:
            time.sleep(0.1)
        if find_runtime_process(root_dir, monitor_id)["running"]:
            result = terminate_process(root_dir, monitor_id, action=action, grace_seconds=3)
        else:
            result = {"found": True, "graceful": True, "killed": False, "pid": record.get("pid")}
    else:
        result = terminate_process(root_dir, monitor_id, action=action)

    state = "paused" if action == "pause" else "stopped"
    update_monitor_registry(
        root_dir,
        monitor_id,
        {
            "pid": None,
            "process_create_time": None,
            "end_time": None if action == "pause" else utcnow_iso(),
            "last_state": state,
        },
    )
    with db.session() as session:
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if monitor_session:
            monitor_session.status = state
    return result


def _remove_service_for_record(record):
    if os.geteuid() != 0:
        raise PermissionError("Removing a system service requires the dashboard to run as root")
    service_name = record.get("service")
    if not service_name:
        return False
    if not _SERVICE_RE.fullmatch(service_name):
        raise RuntimeError("Stored service name is invalid")
    _systemctl("stop", service_name, check=False)
    _systemctl("disable", service_name, check=False)
    path = _service_file(service_name)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    _systemctl("daemon-reload", check=False)
    _systemctl("reset-failed", service_name, check=False)
    return True


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


@monitor_bp.route("/api/monitor/create", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_create():
    try:
        profile, safe_name = _normalize_profile(request.get_json(silent=True) or {})
        monitor_id = f"monitor_{safe_name}"
        proxy_count = _proxy_count(profile)
        create_monitor_record(
            _root_dir(),
            monitor_id,
            {
                "name": profile["name"],
                "safe_name": safe_name,
                "pid": None,
                "process_create_time": None,
                "config": profile,
                "proxy_count": proxy_count,
                "start_time": None,
                "end_time": None,
                "service": None,
                "last_state": "idle",
                "last_error": None,
            },
        )
        log(f"Monitor profile created: {monitor_id}")
        return jsonify({"success": True, "monitor_id": monitor_id, "proxy_count": proxy_count}), 201
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
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    registry = load_monitors_config()
    record = registry.get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    status = _runtime_status(monitor_id, record)
    if status.get("running") or status.get("starting"):
        return api_error("Cannot update a running monitor", 409, "monitor_running")
    with db.session() as session:
        paused = session.query(MonitorSession).filter_by(id=monitor_id, status="paused").first()
        if paused:
            return api_error("Resume or stop the paused session before editing this profile", 409, "monitor_paused")

    try:
        profile, safe_name = _normalize_profile(data, record.get("config", {}))
        new_monitor_id = f"monitor_{safe_name}"
        proxy_count = _proxy_count(profile)
        updates = {
            "name": profile["name"],
            "safe_name": safe_name,
            "config": profile,
            "proxy_count": proxy_count,
            "last_error": None,
        }
        if new_monitor_id != monitor_id:
            rename_monitor_record(_root_dir(), monitor_id, new_monitor_id, updates)
            old_progress = Path(_root_dir()) / "progress" / f"{monitor_id}.json"
            new_progress = Path(_root_dir()) / "progress" / f"{new_monitor_id}.json"
            if old_progress.exists():
                os.replace(old_progress, new_progress)
            monitor_id = new_monitor_id
        else:
            update_monitor_registry(_root_dir(), monitor_id, updates)
        return jsonify({"success": True, "monitor_id": monitor_id, "proxy_count": proxy_count})
    except FileExistsError:
        return api_error("A monitor profile with this name already exists", 409, "monitor_exists")
    except ValueError as exc:
        return api_error(str(exc), 400, "invalid_monitor_config")
    except Exception:
        return api_error("Could not update monitor profile", 500, "monitor_update_failed")


@monitor_bp.route("/api/monitor/start", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_start():
    data = request.get_json(silent=True) or {}
    monitor_id = _monitor_id(data.get("monitor_id"))
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    record = load_monitors_config().get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    if _runtime_status(monitor_id, record).get("running"):
        return api_error("Monitor is already running", 409, "monitor_running")

    saved_config = record.get("config", {})
    if saved_config.get("create_service") == "yes" and os.geteuid() != 0:
        return api_error(
            "Creating a system service requires the dashboard to run as root",
            403,
            "service_permission_denied",
        )
    proxy_count = _proxy_count(saved_config)
    if proxy_count == 0 and saved_config.get("run_mode", "once") == "once":
        return api_error("No proxies match this monitor profile", 409, "monitor_empty")

    delete_progress(_root_dir(), monitor_id)
    clear_action(_root_dir(), monitor_id)
    with db.session() as session:
        session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
        session.query(MonitorSession).filter_by(id=monitor_id).delete()
    update_monitor_registry(_root_dir(), monitor_id, {"proxy_count": proxy_count, "last_state": "starting"})

    try:
        result = _spawn_monitor(monitor_id, saved_config)
        return jsonify(
            {
                "success": True,
                "monitor_id": monitor_id,
                "pid": result["pid"],
                "service_created": bool(result["service"]),
            }
        )
    except MonitorAlreadyRunning as exc:
        return api_error(str(exc), 409, "monitor_running")
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except Exception as exc:
        update_monitor_registry(_root_dir(), monitor_id, {"last_state": "failed", "last_error": str(exc)[:500]})
        return api_error("Failed to start monitor", 500, "monitor_start_failed")


@monitor_bp.route("/api/monitor/stop", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_stop():
    data = request.get_json(silent=True) or {}
    monitor_id = data.get("monitor_id")
    if monitor_id:
        monitor_id = _monitor_id(monitor_id)
        if not monitor_id:
            return api_error("Invalid monitor id", 400, "invalid_monitor_id")
        try:
            result = _stop_monitor(monitor_id, "stop")
            return jsonify({"success": True, "monitor_id": monitor_id, **result})
        except KeyError:
            return api_error("Monitor profile not found", 404, "monitor_not_found")
        except Exception:
            return api_error("Could not stop monitor", 500, "monitor_stop_failed")

    results = {}
    for candidate in load_monitors_config():
        if not _monitor_id(candidate):
            continue
        try:
            results[candidate] = _stop_monitor(candidate, "stop")
        except Exception as exc:
            results[candidate] = {"error": str(exc)[:300]}
    return jsonify({"success": not any("error" in item for item in results.values()), "results": results})


@monitor_bp.route("/api/monitor/pause", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_pause():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    record = load_monitors_config().get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    if not _runtime_status(monitor_id, record).get("running"):
        return api_error("Monitor is not running", 409, "monitor_not_running")
    try:
        result = _stop_monitor(monitor_id, "pause")
        return jsonify({"success": True, "monitor_id": monitor_id, **result})
    except Exception:
        return api_error("Could not pause monitor", 500, "monitor_pause_failed")


@monitor_bp.route("/api/monitor/resume", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_resume():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    record = load_monitors_config().get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    if _runtime_status(monitor_id, record).get("running"):
        return api_error("Monitor is already running", 409, "monitor_running")
    with db.session() as session:
        monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if not monitor_session or monitor_session.status != "paused":
            return api_error("No paused session found", 409, "monitor_not_paused")
    try:
        result = _spawn_monitor(monitor_id, record.get("config", {}))
        return jsonify({"success": True, "monitor_id": monitor_id, "pid": result["pid"]})
    except MonitorAlreadyRunning as exc:
        return api_error(str(exc), 409, "monitor_running")
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except Exception:
        return api_error("Failed to resume monitor", 500, "monitor_resume_failed")


@monitor_bp.route("/api/monitor/remove-service", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_remove_service():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    record = load_monitors_config().get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    if not record.get("service"):
        return api_error("No service exists for this monitor", 409, "service_not_found")
    try:
        _remove_service_for_record(record)
        update_monitor_registry(_root_dir(), monitor_id, {"service": None, "pid": None, "process_create_time": None})
        return jsonify({"success": True, "monitor_id": monitor_id})
    except PermissionError as exc:
        return api_error(str(exc), 403, "service_permission_denied")
    except Exception:
        return api_error("Could not remove monitor service", 500, "service_remove_failed")


@monitor_bp.route("/api/monitor/delete", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_delete():
    monitor_id = _monitor_id((request.get_json(silent=True) or {}).get("monitor_id"))
    if not monitor_id:
        return api_error("Invalid monitor id", 400, "invalid_monitor_id")
    record = load_monitors_config().get(monitor_id)
    if not record:
        return api_error("Monitor profile not found", 404, "monitor_not_found")
    try:
        if _runtime_status(monitor_id, record).get("running"):
            _stop_monitor(monitor_id, "stop")
        if record.get("service"):
            _remove_service_for_record(record)
        delete_progress(_root_dir(), monitor_id)
        with db.session() as session:
            session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
            session.query(MonitorSession).filter_by(id=monitor_id).delete()
        remove_runtime_files(_root_dir(), monitor_id)
        delete_monitor_record(_root_dir(), monitor_id)
        with contextlib.suppress(FileNotFoundError):
            os.remove(_log_path(monitor_id))
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
