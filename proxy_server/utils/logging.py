import threading
import time

log_lock = threading.Lock()

def log(fmt: str, *args):
    with log_lock:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts} {fmt.format(*args)}", flush=True)
