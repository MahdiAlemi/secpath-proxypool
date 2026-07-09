import os
import subprocess
import sys
import signal
import time
import glob
import psutil

from flask import Blueprint, request, jsonify

from dashboard.decorators import login_required, require_permission
from dashboard.config import load_monitors_config, save_monitors_config
from dashboard.utils.process import get_monitor_status
from dashboard.utils.helpers import log
from proxy_monitor.utils.progress import delete_progress
from database import db, MonitorSession, MonitorTested

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route("/api/monitor", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_status():
    from datetime import datetime, timezone
    from proxy_monitor.utils.progress import read_progress
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    
    config = load_monitors_config()
    monitors = {}
    for monitor_id, conf in config.items():
        try:
            status = get_monitor_status(monitor_id)
            is_running = status.get("running", False)
            
            with db.session() as dbs:
                session = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
                session_status = session.status if session else None
                session_tested = session.tested_count if session else 0
                session_total = session.total_proxies if session else 0
                session_alive = session.alive_count if session else 0
                session_dead = session.dead_count if session else 0
                session_other = session.other_count if session else 0
            
            is_paused = session_status == 'paused' and not is_running
            
            monitors[monitor_id] = status
            monitors[monitor_id]["config"] = conf.get("config", {})
            monitors[monitor_id]["proxy_count"] = conf.get("proxy_count")
            monitors[monitor_id]["start_time"] = conf.get("start_time")
            monitors[monitor_id]["end_time"] = conf.get("end_time")
            monitors[monitor_id]["service"] = conf.get("service")
            monitors[monitor_id]["name"] = conf.get("name")
            monitors[monitor_id]["session_status"] = session_status
            
            progress = read_progress(root_dir, monitor_id)
            if progress:
                if is_paused:
                    progress["paused"] = True
                monitors[monitor_id]["progress"] = progress
            elif is_paused:
                percent = int((session_tested / session_total) * 100) if session_total > 0 else 0
                monitors[monitor_id]["progress"] = {
                    "paused": True,
                    "total": session_total,
                    "tested": session_tested,
                    "alive": session_alive,
                    "dead": session_dead,
                    "other": session_other,
                    "percent": percent
                }
            
            if not is_running and conf.get("pid") and not conf.get("end_time"):
                conf["end_time"] = datetime.now(timezone.utc).isoformat()
                conf["pid"] = None
                save_monitors_config(config)
                monitors[monitor_id]["end_time"] = conf["end_time"]
        except Exception as e:
            monitors[monitor_id] = {"running": False, "error": str(e)}
    return jsonify({"monitors": monitors})


@monitor_bp.route("/api/monitor/create", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_create():
    try:
        import re
        from sqlalchemy import or_
        from database import db, Proxy
        
        data = request.json or {}
        
        # Get and validate profile name
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "Profile name is required"})
        
        if len(name) > 50:
            return jsonify({"success": False, "error": "Profile name must be 50 characters or less"})
        
        # Create safe name for monitor_id and service_name
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', name).lower().strip('-')
        if not safe_name:
            return jsonify({"success": False, "error": "Profile name must contain at least one letter or number"})
        
        monitor_id = f"monitor_{safe_name}"
        
        config = load_monitors_config()
        
        # Check if already exists
        if monitor_id in config:
            return jsonify({"success": False, "error": f"A profile with name '{name}' already exists"})
        
        # Count proxies matching the filters
        with db.session() as session:
            query = session.query(Proxy)
            
            protocol_filter = data.get("protocol")
            if protocol_filter:
                protocols_list = [p.strip() for p in protocol_filter.split(",") if p.strip()]
                if protocols_list:
                    query = query.filter(Proxy.protocol.in_(protocols_list))
            
            status_filter = data.get("status")
            if status_filter:
                statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
                if statuses:
                    status_conditions = []
                    for s in statuses:
                        if s == "untested":
                            status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                        else:
                            status_conditions.append(Proxy.status == s)
                    if status_conditions:
                        query = query.filter(or_(*status_conditions))
            
            proxy_count = query.count()
        
        # Save profile without starting
        config[monitor_id] = {
            "name": name,
            "safe_name": safe_name,
            "pid": None,
            "config": data,
            "proxy_count": proxy_count,
            "start_time": None,
            "end_time": None,
            "service": None
        }
        
        save_monitors_config(config)
        log(f"Monitor profile created: {monitor_id} ({name})")
        
        return jsonify({
            "success": True, 
            "monitor_id": monitor_id,
            "proxy_count": proxy_count
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@monitor_bp.route("/api/monitor/update", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_update():
    try:
        import re
        from sqlalchemy import or_
        from database import db, Proxy
        
        data = request.json or {}
        monitor_id = data.get("monitor_id")
        
        if not monitor_id:
            return jsonify({"success": False, "error": "monitor_id required"})
        
        config = load_monitors_config()
        
        if monitor_id not in config:
            return jsonify({"success": False, "error": f"Monitor profile not found: {monitor_id}"})
        
        # Check if monitor is running
        if config[monitor_id].get("pid"):
            pid = config[monitor_id]["pid"]
            if psutil.pid_exists(int(pid)):
                return jsonify({"success": False, "error": "Cannot update while monitor is running. Stop it first."})
        
        # Handle name change (requires key rename)
        new_name = (data.get("name") or "").strip()
        if new_name:
            if len(new_name) > 50:
                return jsonify({"success": False, "error": "Profile name must be 50 characters or less"})
            
            new_safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', new_name).lower().strip('-')
            if not new_safe_name:
                return jsonify({"success": False, "error": "Profile name must contain at least one letter or number"})
            
            new_monitor_id = f"monitor_{new_safe_name}"
            
            # Check if new name conflicts with another profile
            if new_monitor_id != monitor_id and new_monitor_id in config:
                return jsonify({"success": False, "error": f"A profile with name '{new_name}' already exists"})
            
            # Rename the key if name changed
            if new_monitor_id != monitor_id:
                config[new_monitor_id] = config.pop(monitor_id)
                monitor_id = new_monitor_id
            
            config[monitor_id]["name"] = new_name
            config[monitor_id]["safe_name"] = new_safe_name
        
        # Count proxies matching the new filters
        with db.session() as session:
            query = session.query(Proxy)
            
            protocol_filter = data.get("protocol")
            if protocol_filter:
                protocols_list = [p.strip() for p in protocol_filter.split(",") if p.strip()]
                if protocols_list:
                    query = query.filter(Proxy.protocol.in_(protocols_list))
            
            status_filter = data.get("status")
            if status_filter:
                statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
                if statuses:
                    status_conditions = []
                    for s in statuses:
                        if s == "untested":
                            status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                        else:
                            status_conditions.append(Proxy.status == s)
                    if status_conditions:
                        query = query.filter(or_(*status_conditions))
            
            proxy_count = query.count()
        
        # Update config
        config[monitor_id]["config"] = {
            "name": data.get("name", config[monitor_id].get("name", "")),
            "protocol": data.get("protocol", ""),
            "status": data.get("status", ""),
            "check_urls": data.get("check_urls", ""),
            "threads": data.get("threads", 50),
            "timeout": data.get("timeout", 5),
            "probes": data.get("probes", 2),
            "run_mode": data.get("run_mode", "once"),
            "interval": data.get("interval", 60),
            "schedule_time": data.get("schedule_time", ""),
            "schedule_days": data.get("schedule_days", "daily"),
            "custom_every": data.get("custom_every", 24),
            "geo": data.get("geo", "true"),
            "create_service": data.get("create_service", "no")
        }
        config[monitor_id]["proxy_count"] = proxy_count
        
        save_monitors_config(config)
        log(f"Monitor profile updated: {monitor_id}")
        
        return jsonify({
            "success": True, 
            "monitor_id": monitor_id,
            "proxy_count": proxy_count
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@monitor_bp.route("/api/monitor/start", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_start():
    try:
        from datetime import datetime, timezone
        from sqlalchemy import or_
        from database import db, Proxy
        
        data = request.json or {}
        monitor_id = data.get("monitor_id")
        
        if not monitor_id:
            return jsonify({"success": False, "error": "monitor_id required"})
        
        config = load_monitors_config()
        
        if monitor_id not in config:
            return jsonify({"success": False, "error": f"Monitor profile not found: {monitor_id}"})
        
        # Check if already running
        if config[monitor_id].get("pid"):
            pid = config[monitor_id]["pid"]
            if psutil.pid_exists(int(pid)):
                return jsonify({"success": False, "error": f"Monitor already running: {monitor_id}"})
        
        # Get saved config
        saved_config = config[monitor_id].get("config", {})
        
        # Count proxies matching the filters
        with db.session() as session:
            query = session.query(Proxy)
            
            protocol_filter = saved_config.get("protocol")
            if protocol_filter:
                protocols_list = [p.strip() for p in protocol_filter.split(",") if p.strip()]
                if protocols_list:
                    query = query.filter(Proxy.protocol.in_(protocols_list))
            
            status_filter = saved_config.get("status")
            if status_filter:
                statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
                if statuses:
                    status_conditions = []
                    for s in statuses:
                        if s == "untested":
                            status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                        else:
                            status_conditions.append(Proxy.status == s)
                    if status_conditions:
                        query = query.filter(or_(*status_conditions))
            
            proxy_count = query.count()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(base_dir))
        monitor_path = os.path.join(root_dir, "proxy_monitor", "app.py")
        
        delete_progress(root_dir, monitor_id)
        
        with db.session() as dbs:
            dbs.query(MonitorTested).filter_by(session_id=monitor_id).delete()
            dbs.query(MonitorSession).filter_by(id=monitor_id).delete()

        args_list = [sys.executable, "-u", monitor_path]
        
        if saved_config.get("protocol"):
            args_list.extend(["--protocol", saved_config["protocol"]])
        if saved_config.get("status"):
            args_list.extend(["--status", saved_config["status"]])
        if saved_config.get("check_urls"):
            args_list.extend(["--check-urls", saved_config["check_urls"]])
        if saved_config.get("threads"):
            args_list.extend(["--threads", str(saved_config["threads"])])
        if saved_config.get("timeout"):
            args_list.extend(["--timeout", str(saved_config["timeout"])])
        if saved_config.get("probes"):
            args_list.extend(["--probes", str(saved_config["probes"])])
        if saved_config.get("name"):
            args_list.extend(["--name", saved_config["name"]])
        if saved_config.get("run_mode"):
            args_list.extend(["--run-mode", saved_config["run_mode"]])
        if saved_config.get("interval"):
            args_list.extend(["--interval", str(saved_config["interval"])])
        if saved_config.get("schedule_time"):
            args_list.extend(["--schedule-time", saved_config["schedule_time"]])
        if saved_config.get("schedule_days"):
            args_list.extend(["--schedule-days", saved_config["schedule_days"]])
        if saved_config.get("custom_every"):
            args_list.extend(["--custom-every", str(saved_config["custom_every"])])
        if saved_config.get("geo"):
            args_list.extend(["--geo", saved_config["geo"]])
        args_list.extend(["--monitor-id", monitor_id])

        create_service = saved_config.get("create_service", "no") == "yes"
        safe_name = config[monitor_id].get("safe_name", monitor_id.replace("monitor_", ""))
        service_name = f"proxy-monitor-{safe_name}"

        log_file = os.path.join(root_dir, f"{monitor_id}.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        log_handle = open(log_file, "ab", buffering=0)
        proc = subprocess.Popen(
            args_list,
            cwd=root_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        actual_pid = str(proc.pid)
        time.sleep(0.5)
        
        if actual_pid and actual_pid.isdigit() and proc.poll() is None:
            config[monitor_id]["pid"] = actual_pid
            config[monitor_id]["proxy_count"] = proxy_count
            config[monitor_id]["start_time"] = datetime.now(timezone.utc).isoformat()
            config[monitor_id]["end_time"] = None
            
            if create_service:
                run_mode = saved_config.get("run_mode", "once")
                restart_policy = "always" if run_mode not in ["once"] else "no"
                service_content = f'''[Unit]
Description=Proxy Monitor - {monitor_id}
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={root_dir}
ExecStart={" ".join(__import__("shlex").quote(a) for a in args_list)}
Restart={restart_policy}
RestartSec=10

[Install]
WantedBy=multi-user.target
'''
                service_file = f"/etc/systemd/system/{service_name}.service"
                try:
                    with open(service_file, "w") as sf:
                        sf.write(service_content)
                    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                    subprocess.run(["systemctl", "enable", service_name], capture_output=True)
                    subprocess.run(["systemctl", "start", service_name], capture_output=True)
                    log(f"Service {service_name} created and started")
                    config[monitor_id]["service"] = service_name
                except Exception as se:
                    log(f"Failed to create service: {se}")
            
            save_monitors_config(config)
            log(f"Monitor started: {monitor_id} with PID {actual_pid}")
            return jsonify({"success": True, "pid": int(actual_pid), "monitor_id": monitor_id, "service_created": create_service})
        
        time.sleep(1)
        for p in glob.glob("/proc/*/cmdline"):
            try:
                with open(p, 'rb') as f:
                    cmd = f.read()
                    if b'proxy_monitor' in cmd and monitor_id.encode() in cmd:
                        actual_pid = p.split('/')[2]
                        config[monitor_id]["pid"] = actual_pid
                        config[monitor_id]["proxy_count"] = proxy_count
                        config[monitor_id]["start_time"] = datetime.now(timezone.utc).isoformat()
                        config[monitor_id]["end_time"] = None
                        if create_service:
                            config[monitor_id]["service"] = service_name
                        save_monitors_config(config)
                        log(f"Monitor started: {monitor_id} with PID {actual_pid}")
                        return jsonify({"success": True, "pid": int(actual_pid), "monitor_id": monitor_id})
            except:
                pass
        
        return jsonify({"success": False, "error": "Failed to start monitor"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@monitor_bp.route("/api/monitor/stop", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_stop():
    from datetime import datetime, timezone
    
    data = request.json or {}
    monitor_id = data.get("monitor_id")
    
    config = load_monitors_config()
    
    if monitor_id:
        if monitor_id in config:
            pid = config[monitor_id].get("pid")
            if pid:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    log(f"Monitor {monitor_id} killed (PID {pid})")
                except ProcessLookupError:
                    pass
                except Exception as e:
                    log(f"Failed to kill monitor {monitor_id}: {e}")
            
            service_name = config[monitor_id].get("service")
            if service_name:
                try:
                    subprocess.run(["systemctl", "stop", service_name], capture_output=True, timeout=30)
                    subprocess.run(["systemctl", "disable", service_name], capture_output=True)
                    service_file = f"/etc/systemd/system/{service_name}.service"
                    if os.path.exists(service_file):
                        os.remove(service_file)
                    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                    subprocess.run(["systemctl", "reset-failed", service_name], capture_output=True)
                    log(f"Service {service_name} removed")
                    del config[monitor_id]["service"]
                except Exception as e:
                    log(f"Failed to remove service: {e}")
            elif pid:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    log(f"Monitor {monitor_id} killed (PID {pid})")
                except ProcessLookupError:
                    pass
                except Exception as e:
                    log(f"Failed to kill monitor {monitor_id}: {e}")
            
            config[monitor_id]["pid"] = None
            config[monitor_id]["end_time"] = datetime.now(timezone.utc).isoformat()
            save_monitors_config(config)
            
            base_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(os.path.dirname(base_dir))
            delete_progress(root_dir, monitor_id)
            
            with db.session() as dbs:
                dbs.query(MonitorTested).filter_by(session_id=monitor_id).delete()
                dbs.query(MonitorSession).filter_by(id=monitor_id).delete()
            
            return jsonify({"success": True, "monitor_id": monitor_id})
        return jsonify({"success": False, "error": f"No monitor: {monitor_id}"})
    
    for mid, conf in list(config.items()):
        pid = conf.get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except:
                pass
        conf["pid"] = None
        conf["end_time"] = datetime.now(timezone.utc).isoformat()
    save_monitors_config(config)
    log("All monitors killed")
    return jsonify({"success": True})


@monitor_bp.route("/api/monitor/pause", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_pause():
    from datetime import datetime, timezone
    
    data = request.json or {}
    monitor_id = data.get("monitor_id")
    
    if not monitor_id:
        return jsonify({"success": False, "error": "monitor_id required"})
    
    config = load_monitors_config()
    
    if monitor_id not in config:
        return jsonify({"success": False, "error": f"Monitor not found: {monitor_id}"})
    
    if config[monitor_id].get("service"):
        return jsonify({"success": False, "error": "Cannot pause a service monitor. Use Stop to kill and remove the service."})
    
    pid = config[monitor_id].get("pid")
    if not pid or not psutil.pid_exists(int(pid)):
        return jsonify({"success": False, "error": "Monitor is not running"})
    
    try:
        os.kill(int(pid), signal.SIGKILL)
        log(f"Monitor {monitor_id} paused (killed PID {pid})")
    except ProcessLookupError:
        pass
    except Exception as e:
        log(f"Failed to kill monitor {monitor_id}: {e}")
    
    with db.session() as dbs:
        session = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
        if session:
            session.status = 'paused'
    
    config[monitor_id]["pid"] = None
    config[monitor_id]["end_time"] = None
    save_monitors_config(config)
    
    return jsonify({"success": True, "monitor_id": monitor_id})


@monitor_bp.route("/api/monitor/resume", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_resume():
    from datetime import datetime, timezone
    
    data = request.json or {}
    monitor_id = data.get("monitor_id")
    
    if not monitor_id:
        return jsonify({"success": False, "error": "monitor_id required"})
    
    config = load_monitors_config()
    
    if monitor_id not in config:
        return jsonify({"success": False, "error": f"Monitor not found: {monitor_id}"})
    
    with db.session() as dbs:
        session = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
        if not session or session.status != 'paused':
            return jsonify({"success": False, "error": "No paused session found for this monitor"})
    
    saved_config = config[monitor_id].get("config", {})
    proxy_count = config[monitor_id].get("proxy_count", 0)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    monitor_path = os.path.join(root_dir, "proxy_monitor", "app.py")
    
    args_list = [sys.executable, "-u", monitor_path]
    
    if saved_config.get("protocol"):
        args_list.extend(["--protocol", saved_config["protocol"]])
    if saved_config.get("status"):
        args_list.extend(["--status", saved_config["status"]])
    if saved_config.get("check_urls"):
        args_list.extend(["--check-urls", saved_config["check_urls"]])
    if saved_config.get("threads"):
        args_list.extend(["--threads", str(saved_config["threads"])])
    if saved_config.get("timeout"):
        args_list.extend(["--timeout", str(saved_config["timeout"])])
    if saved_config.get("probes"):
        args_list.extend(["--probes", str(saved_config["probes"])])
    if saved_config.get("name"):
        args_list.extend(["--name", saved_config["name"]])
    if saved_config.get("run_mode"):
        args_list.extend(["--run-mode", saved_config["run_mode"]])
    if saved_config.get("interval"):
        args_list.extend(["--interval", str(saved_config["interval"])])
    if saved_config.get("schedule_time"):
        args_list.extend(["--schedule-time", saved_config["schedule_time"]])
    if saved_config.get("schedule_days"):
        args_list.extend(["--schedule-days", saved_config["schedule_days"]])
    if saved_config.get("custom_every"):
        args_list.extend(["--custom-every", str(saved_config["custom_every"])])
    if saved_config.get("geo"):
        args_list.extend(["--geo", saved_config["geo"]])
    args_list.extend(["--monitor-id", monitor_id])
    
    log_file = os.path.join(root_dir, f"{monitor_id}.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_handle = open(log_file, "ab", buffering=0)
    proc = subprocess.Popen(
        args_list,
        cwd=root_dir,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    actual_pid = str(proc.pid)
    time.sleep(0.5)
    
    if actual_pid and actual_pid.isdigit() and proc.poll() is None:
        config[monitor_id]["pid"] = actual_pid
        config[monitor_id]["start_time"] = datetime.now(timezone.utc).isoformat()
        config[monitor_id]["end_time"] = None
        save_monitors_config(config)
        
        log(f"Monitor {monitor_id} resumed with PID {actual_pid}")
        return jsonify({"success": True, "monitor_id": monitor_id, "pid": int(actual_pid)})
    
    return jsonify({"success": False, "error": "Failed to resume monitor"})


@monitor_bp.route("/api/monitor/remove-service", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_remove_service():
    data = request.json or {}
    monitor_id = data.get("monitor_id")
    
    if not monitor_id:
        return jsonify({"success": False, "error": "monitor_id required"})
    
    config = load_monitors_config()
    
    if monitor_id in config:
        service_name = config[monitor_id].get("service")
        if service_name:
            try:
                subprocess.run(["systemctl", "stop", service_name], capture_output=True)
                subprocess.run(["systemctl", "disable", service_name], capture_output=True)
                service_file = f"/etc/systemd/system/{service_name}.service"
                if os.path.exists(service_file):
                    os.remove(service_file)
                subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
                del config[monitor_id]["service"]
                save_monitors_config(config)
                log(f"Service {service_name} removed")
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})
        return jsonify({"success": False, "error": "No service for this monitor"})
    return jsonify({"success": False, "error": "Monitor not found"})


@monitor_bp.route("/api/monitor/delete", methods=["POST"])
@login_required
@require_permission("monitor.control")
def api_monitor_delete():
    data = request.json or {}
    monitor_id = data.get("monitor_id")
    
    if not monitor_id:
        return jsonify({"success": False, "error": "monitor_id required"})
    
    config = load_monitors_config()
    
    if monitor_id in config:
        pid = config[monitor_id].get("pid")
        if pid and psutil.pid_exists(int(pid)):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except:
                pass
        
        service_name = config[monitor_id].get("service")
        if service_name:
            try:
                subprocess.run(["systemctl", "stop", service_name], capture_output=True)
                subprocess.run(["systemctl", "disable", service_name], capture_output=True)
                service_file = f"/etc/systemd/system/{service_name}.service"
                if os.path.exists(service_file):
                    os.remove(service_file)
                subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
            except:
                pass
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(base_dir))
        delete_progress(root_dir, monitor_id)
        
        with db.session() as dbs:
            dbs.query(MonitorTested).filter_by(session_id=monitor_id).delete()
            dbs.query(MonitorSession).filter_by(id=monitor_id).delete()
        
        del config[monitor_id]
        save_monitors_config(config)
        log(f"Monitor {monitor_id} deleted")
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Monitor not found"})


@monitor_bp.route("/api/monitor/log", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_log():
    monitor_id = request.args.get("monitor_id", "monitor_all")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    log_file = os.path.join(root_dir, f"{monitor_id}.log")
    lines = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()[-100:]
    return jsonify({"lines": lines, "monitor_id": monitor_id})


@monitor_bp.route("/api/monitor/log/stream", methods=["GET"])
@login_required
@require_permission("monitor.view")
def api_monitor_log_stream():
    import time
    monitor_id = request.args.get("monitor_id", "monitor_all")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    log_file = os.path.join(root_dir, f"{monitor_id}.log")
    
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
    
    from flask import Response
    return Response(generate(), mimetype='text/event-stream')
