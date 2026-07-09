import signal
import threading
import time

STOP = False
PAUSED = threading.Event()
log_lock = threading.Lock()


def log(fmt: str, *args):
    with log_lock:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts} {fmt.format(*args)}", flush=True)


def handle_sigint(sig, frame):
    global STOP
    STOP = True
    log("[!] Received Ctrl+C, stopping...")


def init_signals():
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)
