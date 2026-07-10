from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path

BUFFER_SIZE = 64 * 1024
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_ROTATE = "better_cost"
DEFAULT_THREADS = 100
DEFAULT_TIMEOUT = 10
DEFAULT_HEADER_LIMIT = 64 * 1024
DEFAULT_COST_THRESHOLD = None
PROTOCOLS = {"http", "https", "socks4", "socks5"}
ROTATE_MODES = {"fixed", "per_connection", "better_cost", "time", "sticky"}

HAVE_CRYPTO = True
try:
    import cryptography  # noqa: F401
except Exception:
    HAVE_CRYPTO = False


def _as_bool(value, *, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _optional_bool(value):
    if value in (None, ""):
        return None
    return _as_bool(value)


def _is_local_bind(value: str) -> bool:
    normalized = (value or "").strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _load_profile(path: str | None) -> dict:
    if not path:
        return {}
    profile_path = Path(path).expanduser().resolve()
    with profile_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("server config file must contain a JSON object")
    return payload


def _parser(defaults: dict | None = None) -> argparse.ArgumentParser:
    defaults = defaults or {}
    parser = argparse.ArgumentParser(description="Proxy Pool serving process")
    parser.add_argument("--config-file", help="Read server profile from a protected JSON file")
    parser.add_argument("--server-id", default=defaults.get("server_id"), help="Stable server identity")
    parser.add_argument("--claim-token", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--protocol", default=defaults.get("protocol", "http"), choices=sorted(PROTOCOLS))
    parser.add_argument("--bind", default=defaults.get("bind", DEFAULT_BIND))
    parser.add_argument("--listen_port", type=int, default=defaults.get("port", defaults.get("listen_port", DEFAULT_PORT)))
    parser.add_argument("--threads", type=int, default=defaults.get("threads", DEFAULT_THREADS))
    parser.add_argument("--timeout", type=float, default=defaults.get("timeout", DEFAULT_TIMEOUT))
    parser.add_argument("--header-limit", type=int, default=defaults.get("header_limit", DEFAULT_HEADER_LIMIT))
    parser.add_argument("--w_latency", type=float, default=defaults.get("w_latency", 0.4))
    parser.add_argument("--w_fail", type=float, default=defaults.get("w_fail", 0.4))
    parser.add_argument("--rotate", default=defaults.get("rotate", DEFAULT_ROTATE), choices=sorted(ROTATE_MODES))
    parser.add_argument("--rotate_interval", type=int, default=defaults.get("rotate_interval", 60))
    parser.add_argument("--min_cost", type=float, default=defaults.get("min_cost", 0.0))
    parser.add_argument("--cost_threshold", type=float, default=defaults.get("cost_threshold", DEFAULT_COST_THRESHOLD))
    parser.add_argument("--auth_required", default=defaults.get("auth_required"))
    parser.add_argument("--username", default=defaults.get("username"))
    parser.add_argument("--password", default=defaults.get("password"))
    parser.add_argument("--certfile", default=defaults.get("certfile"))
    parser.add_argument("--keyfile", default=defaults.get("keyfile"))
    parser.add_argument("--insecure_upstream", action="store_true", default=_as_bool(defaults.get("insecure_upstream"), default=False))
    parser.add_argument("--allow-public-no-auth", action="store_true", default=_as_bool(defaults.get("allow_public_no_auth"), default=False))
    parser.add_argument("--sticky_upstream", default=defaults.get("sticky_upstream"))
    parser.add_argument("--upstream_protocol", default=defaults.get("upstream_protocol"))
    parser.add_argument("--candidate_statuses", default=defaults.get("candidate_statuses", "alive"))
    parser.add_argument("--require_web_https", action="store_true", default=_as_bool(defaults.get("require_web_https"), default=False))
    parser.add_argument("--require_remote_dns", action="store_true", default=_as_bool(defaults.get("require_remote_dns"), default=False))
    parser.add_argument("--require_telegram", action="store_true", default=_as_bool(defaults.get("require_telegram"), default=False))
    parser.add_argument("--countryCodes", default=defaults.get("countryCodes"))
    parser.add_argument("--regions", default=defaults.get("regions"))
    parser.add_argument("--cities", default=defaults.get("cities"))
    parser.add_argument("--orgs", default=defaults.get("orgs"))
    parser.add_argument("--isp", default=defaults.get("isp"))
    parser.add_argument("--asn", default=defaults.get("asn"))
    parser.add_argument("--continentCode", default=defaults.get("continentCode"))
    parser.add_argument("--zip_codes", default=defaults.get("zip_codes"))
    parser.add_argument("--timezones", default=defaults.get("timezones"))
    parser.add_argument("--mobile", default=defaults.get("mobile"))
    parser.add_argument("--proxy", default=defaults.get("proxy"))
    parser.add_argument("--hosting", default=defaults.get("hosting"))
    parser.add_argument("--readonly", action="store_true", default=_as_bool(defaults.get("readonly"), default=False))
    return parser


def validate_args(args):
    if not 1 <= int(args.listen_port) <= 65535:
        raise ValueError("listen_port must be between 1 and 65535")
    if not 1 <= int(args.threads) <= 1000:
        raise ValueError("threads must be between 1 and 1000")
    if not 1 <= float(args.timeout) <= 300:
        raise ValueError("timeout must be between 1 and 300 seconds")
    if not 4096 <= int(args.header_limit) <= 1024 * 1024:
        raise ValueError("header_limit must be between 4096 and 1048576")
    if not 1 <= int(args.rotate_interval) <= 86400:
        raise ValueError("rotate_interval must be between 1 and 86400")
    if args.cost_threshold is not None and float(args.cost_threshold) < float(args.min_cost):
        raise ValueError("cost_threshold cannot be lower than min_cost")
    if bool(args.certfile) != bool(args.keyfile):
        raise ValueError("certfile and keyfile must be configured together")
    if bool(args.username) != bool(args.password) and args.protocol != "socks4":
        raise ValueError("username and password must be configured together")
    if args.protocol == "socks4" and args.password:
        raise ValueError("SOCKS4 listener authentication supports UserID only; password authentication is unavailable")
    if not _is_local_bind(args.bind) and not (args.username or args.allow_public_no_auth):
        raise ValueError(
            "refusing to expose an unauthenticated proxy beyond loopback; "
            "configure listener credentials or explicitly enable allow_public_no_auth"
        )
    args.mobile = _optional_bool(args.mobile)
    args.proxy = _optional_bool(args.proxy)
    args.hosting = _optional_bool(args.hosting)
    args.server_id = str(args.server_id or args.listen_port)
    return args


def parse_args(argv=None):
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config-file")
    known, _ = bootstrap.parse_known_args(argv)
    defaults = _load_profile(known.config_file)
    args = _parser(defaults).parse_args(argv)
    return validate_args(args)
