from datetime import datetime, timezone


def clamp_int(val, default, minv=None, maxv=None):
    try:
        v = int(val)
    except Exception:
        return default
    if minv is not None and v < minv:
        v = minv
    if maxv is not None and v > maxv:
        v = maxv
    return v


def parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def format_time(ts):
    if not ts:
        return "unknown"
    dt = parse_iso(ts)
    if dt is None:
        return "unknown"
    try:
        return dt.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except:
        return "unknown"


def log(msg):
    from dashboard.config import log_file
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"{ts} {msg}\n")
