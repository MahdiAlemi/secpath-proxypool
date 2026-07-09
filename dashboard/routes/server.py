import os
import subprocess
import signal
import time
import glob
import psutil

from flask import Blueprint, request, jsonify, Response

from dashboard.decorators import login_required, require_permission
from dashboard.config import load_servers_config, save_servers_config
from dashboard.utils.process import get_server_status
from dashboard.utils.helpers import log

server_bp = Blueprint('server', __name__)


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
        print(f"[DEBUG] API /api/server called, config: {config}")
        servers = {}
        for port_key, conf in config.items():
            port = str(port_key)
            try:
                status = get_server_status(port)
                servers[port] = status
                servers[port]["protocol"] = conf.get("protocol", "http")
                servers[port]["config"] = conf.get("config", {})
                print(f"[DEBUG] Port {port}: running={status.get('running')}, pid={status.get('pid')}")
            except Exception as e:
                servers[port] = {"running": False, "error": str(e)}
        
        return jsonify({"servers": servers})
    except Exception as e:
        return jsonify({"error": str(e), "servers": {}})


@server_bp.route("/api/server/create", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_create():
    try:
        data = request.json or {}
        port = str(data.get("port", 8080))
        
        config = load_servers_config()
        
        if port in config:
            return jsonify({"success": False, "error": f"A server on port {port} already exists"})
        
        config[port] = {
            "pid": None,
            "protocol": data.get("protocol", "http"),
            "config": data
        }
        
        save_servers_config(config)
        log(f"Server profile created on port {port}")
        
        return jsonify({
            "success": True,
            "port": port,
            "protocol": data.get("protocol", "http")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@server_bp.route("/api/server/update", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_update():
    try:
        data = request.json or {}
        port = str(data.get("port", 8080))
        
        config = load_servers_config()
        
        if port not in config:
            return jsonify({"success": False, "error": f"No server profile on port {port}"})
        
        pid = config[port].get("pid")
        was_running = False
        if pid:
            try:
                was_running = psutil.pid_exists(int(pid))
            except:
                pass
        
        # Kill the running process if was running
        if was_running:
            old_pid = pid
            if old_pid:
                try:
                    os.kill(int(old_pid), signal.SIGTERM)
                    time.sleep(1)
                    if psutil.pid_exists(old_pid):
                        os.kill(int(old_pid), signal.SIGKILL)
                except:
                    pass
        
        config[port] = {
            "pid": None,
            "protocol": data.get("protocol", "http"),
            "config": data
        }
        
        save_servers_config(config)
        log(f"Server profile updated on port {port}")
        
        return jsonify({
            "success": True,
            "port": port,
            "protocol": data.get("protocol", "http"),
            "was_running": was_running
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@server_bp.route("/api/server/start", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_start():
    data = request.json or {}
    port = str(data.get("port", 8080))
    
    print(f"[DEBUG] Starting server on port: {port}")
    
    config = load_servers_config()
    print(f"[DEBUG] Current config before start: {config}")
    
    existing_config = config.get(port, {}).get("config", {})
    
    if existing_config and not data.get("config"):
        data = existing_config
        data["port"] = int(port)
    
    print(f"[DEBUG] Data being used to start: {data}")
    
    if port in config and config[port].get("pid"):
        pid = config[port]["pid"]
        try:
            pid_int = int(pid)
            if psutil.pid_exists(pid_int):
                os.kill(pid_int, signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(pid_int):
                    os.kill(pid_int, signal.SIGKILL)
        except:
            pass
    
    if port in config:
        del config[port]
    
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
        args_list.append("--insecure-upstream")
    if data.get("sticky_upstream"):
        args_list.extend(["--sticky_upstream", data["sticky_upstream"]])
    if data.get("upstream_protocol"):
        args_list.extend(["--upstream_protocol", data["upstream_protocol"]])

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
        subprocess.run(["bash", "-c", f"pkill -f 'server.py.*{data.get('port', 8080)}'"], capture_output=True)
        time.sleep(1)
        
        shell_cmd = f"nohup python3 -u {server_path} " + " ".join(args_list) + f" >> {log_file} 2>&1 & echo $!"
        
        proc = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            cwd=root_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, _ = proc.communicate()
        actual_pid = stdout.strip()
        
        if actual_pid and actual_pid.isdigit():
            config = load_servers_config()
            config[port] = {"pid": actual_pid, "protocol": data.get("protocol", "http"), "config": data}
            save_servers_config(config)
            log(f"Server started on port {port} with PID {actual_pid}")
            return jsonify({"success": True, "pid": int(actual_pid), "port": port})
        
        time.sleep(1)
        for p in glob.glob("/proc/*/cmdline"):
            try:
                with open(p, 'rb') as f:
                    cmd = f.read()
                    if b'server.py' in cmd and str(data.get('port', 8080)).encode() in cmd:
                        actual_pid = p.split('/')[2]
                        config = load_servers_config()
                        config[port] = {"pid": actual_pid, "protocol": data.get("protocol", "http"), "config": data}
                        save_servers_config(config)
                        log(f"Server started on port {port} with PID {actual_pid}")
                        return jsonify({"success": True, "pid": int(actual_pid), "port": port})
            except:
                pass
        
        return jsonify({"success": False, "error": "Failed to start server"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@server_bp.route("/api/server/stop", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_stop():
    data = request.get_json() or {}
    port = str(data.get("port")) if data.get("port") else None
    
    if not port:
        return jsonify({"success": False, "error": "Port required"})
    
    config = load_servers_config()
    
    if port in config:
        pid = config[port].get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(pid):
                    os.kill(int(pid), signal.SIGKILL)
            except Exception as e:
                pass
        config[port]["pid"] = None
        save_servers_config(config)
        log(f"Server stopped on port {port}")
        return jsonify({"success": True, "port": port})
    return jsonify({"success": False, "error": f"No server running on port {port}"})


@server_bp.route("/api/server/delete", methods=["POST"])
@login_required
@require_permission("server.control")
def api_server_delete():
    data = request.get_json() or {}
    port = str(data.get("port")) if data.get("port") else None
    
    if not port:
        return jsonify({"success": False, "error": "Port required"})
    
    config = load_servers_config()
    
    if port in config:
        pid = config[port].get("pid")
        if pid:
            try:
                if psutil.pid_exists(int(pid)):
                    return jsonify({"success": False, "error": "Server is running. Stop it first."})
            except:
                pass
        del config[port]
        save_servers_config(config)
        log(f"Server profile deleted on port {port}")
        return jsonify({"success": True, "port": port})
    return jsonify({"success": False, "error": f"No server profile on port {port}"})


@server_bp.route("/api/server/log", methods=["GET"])
@login_required
@require_permission("server.view")
def api_server_log():
    port = request.args.get("port", "8080")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(base_dir))
    log_file = os.path.join(root_dir, f"server_{port}.log")
    lines = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()[-100:]
    return jsonify({"lines": lines, "port": port})
