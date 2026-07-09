import os
import json
import threading
from datetime import datetime, timezone

_lock = threading.Lock()


def get_progress_dir(root_dir):
    return os.path.join(root_dir, "progress")


def write_progress(root_dir, monitor_id, data):
    progress_dir = get_progress_dir(root_dir)
    os.makedirs(progress_dir, exist_ok=True)
    
    temp_file = os.path.join(progress_dir, f".{monitor_id}.json.tmp")
    final_file = os.path.join(progress_dir, f"{monitor_id}.json")
    
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    with _lock:
        try:
            with open(temp_file, 'w') as f:
                json.dump(data, f)
            os.rename(temp_file, final_file)
        except Exception:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass


def read_progress(root_dir, monitor_id):
    progress_file = os.path.join(get_progress_dir(root_dir), f"{monitor_id}.json")
    try:
        with _lock:
            if os.path.exists(progress_file):
                with open(progress_file, 'r') as f:
                    return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return None


def delete_progress(root_dir, monitor_id):
    progress_file = os.path.join(get_progress_dir(root_dir), f"{monitor_id}.json")
    with _lock:
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
            except:
                pass


def cleanup_old_progress(root_dir, max_age_hours=24):
    progress_dir = get_progress_dir(root_dir)
    if not os.path.exists(progress_dir):
        return
    
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (max_age_hours * 3600)
    
    with _lock:
        for filename in os.listdir(progress_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(progress_dir, filename)
                try:
                    if os.path.getmtime(filepath) < cutoff:
                        os.remove(filepath)
                except:
                    pass
