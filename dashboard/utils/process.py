import os
import signal
import psutil
import time

from dashboard.config import (
    load_monitors_config, save_monitors_config,
    load_servers_config, save_servers_config
)


def get_process_pid(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                return pid
        except:
            pass
    return None


def is_process_running(pid_file):
    pid = get_process_pid(pid_file)
    if pid:
        try:
            p = psutil.Process(pid)
            return p.is_running()
        except:
            pass
    return False


def stop_process(pid_file):
    pid = get_process_pid(pid_file)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if psutil.pid_exists(pid):
                os.kill(pid, signal.SIGKILL)
        except:
            pass
    try:
        if os.path.exists(pid_file):
            os.unlink(pid_file)
    except:
        pass
    return True


def get_monitor_status(monitor_id):
    config = load_monitors_config()
    if monitor_id in config:
        pid = config[monitor_id].get("pid")
        if pid:
            try:
                if psutil.pid_exists(int(pid)):
                    p = psutil.Process(int(pid))
                    if p.status() == psutil.STATUS_ZOMBIE:
                        return {"running": False, "pid": None, "memory_mb": 0}
                    return {"running": p.is_running(), "pid": pid, "memory_mb": round(p.memory_info().rss / 1024 / 1024, 1)}
            except:
                pass
    return {"running": False, "pid": None, "memory_mb": 0}


def get_server_status(port):
    config = load_servers_config()
    port_str = str(port)
    if port_str in config:
        pid = config[port_str].get("pid")
        if pid:
            try:
                if psutil.pid_exists(int(pid)):
                    p = psutil.Process(int(pid))
                    if p.status() == psutil.STATUS_ZOMBIE:
                        return {"running": False, "pid": None, "memory_mb": 0, "connections": 0}
                    return {"running": p.is_running(), "pid": pid, "memory_mb": round(p.memory_info().rss / 1024 / 1024, 1), "connections": len(p.net_connections())}
            except:
                pass
    return {"running": False, "pid": None, "memory_mb": 0, "connections": 0}
