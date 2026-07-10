from __future__ import annotations

import os
import signal
import time

import psutil

from dashboard.config import load_monitors_config


def get_process_pid(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, encoding="utf-8") as handle:
                pid = int(handle.read().strip())
            if psutil.pid_exists(pid):
                return pid
        except (OSError, TypeError, ValueError):
            pass
    return None


def is_process_running(pid_file):
    pid = get_process_pid(pid_file)
    if pid:
        try:
            return psutil.Process(pid).is_running()
        except psutil.Error:
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
        except (OSError, psutil.Error):
            pass
    try:
        if os.path.exists(pid_file):
            os.unlink(pid_file)
    except OSError:
        pass
    return True


def get_monitor_status(monitor_id):
    config = load_monitors_config()
    if monitor_id in config:
        pid = config[monitor_id].get("pid")
        if pid:
            try:
                process = psutil.Process(int(pid))
                if process.status() == psutil.STATUS_ZOMBIE:
                    return {"running": False, "pid": None, "memory_mb": 0}
                return {
                    "running": process.is_running(),
                    "pid": pid,
                    "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
                }
            except (TypeError, ValueError, psutil.Error):
                pass
    return {"running": False, "pid": None, "memory_mb": 0}


def get_server_status(port):
    from proxy_server.lifecycle import snapshot

    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return snapshot(root_dir, str(port))
