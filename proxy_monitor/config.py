import argparse
import re

THREADS = 50
TIMEOUT = 5
PROBES_PER_PROXY = 2
CHECK_URLS = ["https://ident.me", "https://ifconfig.me"]
PROBE_JITTER = (0.1, 0.5)
SHUFFLE_BIAS = 0.0
SPEED_THRESHOLD_MS = 5000
RECENT_FAIL_SECONDS = 300

DEFAULT_PROTOCOL = "all"
DEFAULT_RUN_MODE = "once"
DEFAULT_INTERVAL = 60


def _bounded_int(minimum, maximum):
    def parse(value):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return number

    return parse


def _schedule_time(value):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value or ""):
        raise argparse.ArgumentTypeError("must use HH:MM in 24-hour format")
    return value


def parse_args():
    parser = argparse.ArgumentParser(description="Proxy Monitor")
    parser.add_argument("--protocol", help="Protocol filter (http,https,socks4,socks5, comma-separated)")
    parser.add_argument("--status", help="Status filter (alive,soft,flaky,cooling,dead,untested, comma-separated)")
    parser.add_argument("--check-urls", help="Comma-separated check URLs")
    parser.add_argument("--threads", type=_bounded_int(1, 200), default=THREADS, help="Number of threads")
    parser.add_argument("--timeout", type=_bounded_int(1, 60), default=TIMEOUT, help="Request timeout")
    parser.add_argument("--probes", type=_bounded_int(1, 5), default=PROBES_PER_PROXY, help="Number of probes per proxy")
    parser.add_argument("--name", help="Monitor name")
    parser.add_argument(
        "--run-mode",
        default=DEFAULT_RUN_MODE,
        choices=["once", "infinite", "restart", "schedule", "custom"],
        help="Run mode",
    )
    parser.add_argument("--interval", type=_bounded_int(10, 86400), default=DEFAULT_INTERVAL, help="Interval in seconds")
    parser.add_argument("--schedule-time", type=_schedule_time, help="Schedule time (HH:MM)")
    parser.add_argument(
        "--schedule-days",
        default="daily",
        help="daily, weekdays, weekends, or comma-separated mon..sun",
    )
    parser.add_argument("--custom-every", type=_bounded_int(1, 720), default=24, help="Custom interval in hours")
    parser.add_argument("--geo", default="true", choices=["true", "false"], help="Enable GEO extraction")
    parser.add_argument("--monitor-id", help="Unique monitor ID for progress tracking")
    parser.add_argument("--start-token", help=argparse.SUPPRESS)
    return parser.parse_args()
