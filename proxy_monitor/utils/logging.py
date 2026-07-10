import signal
import threading
import time


class StopFlag:
    """A process-local stop flag that remains live across ``from ... import STOP``.

    Importing a plain boolean copies the current object reference. Rebinding that
    boolean in a signal handler therefore leaves other modules with a stale
    ``False`` value. This mutable wrapper keeps every importer synchronized.
    """

    def __init__(self):
        self._event = threading.Event()

    def __bool__(self):
        return self._event.is_set()

    def set(self):
        self._event.set()

    def clear(self):
        self._event.clear()

    def wait(self, timeout=None):
        return self._event.wait(timeout)

    @property
    def is_set(self):
        return self._event.is_set()


STOP = StopFlag()
PAUSED = threading.Event()
log_lock = threading.Lock()


def log(fmt: str, *args):
    with log_lock:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts} {fmt.format(*args)}", flush=True)


def request_stop(reason="signal"):
    if not STOP:
        STOP.set()
        log("[!] Stop requested ({})", reason)


def reset_stop():
    STOP.clear()


def wait_interruptible(seconds, step=1.0):
    """Wait up to ``seconds`` and return ``False`` if a stop was requested."""
    remaining = max(0.0, float(seconds))
    while remaining > 0 and not STOP:
        chunk = min(float(step), remaining)
        if STOP.wait(chunk):
            break
        remaining -= chunk
    return not bool(STOP)


def handle_stop_signal(sig, frame):
    del frame
    signal_name = getattr(signal.Signals(sig), "name", str(sig))
    request_stop(signal_name)


def init_signals():
    signal.signal(signal.SIGINT, handle_stop_signal)
    signal.signal(signal.SIGTERM, handle_stop_signal)
