from __future__ import annotations

import contextlib
import ipaddress
import os
from pathlib import Path
from typing import Any, Callable

from secproxy_core.config_store import PROTOCOLS, ROTATE_MODES

_BOOL_FIELDS = {
    "insecure_upstream",
    "require_web_https",
    "require_remote_dns",
    "require_telegram",
    "readonly",
    "allow_public_no_auth",
}
_OPTIONAL_BOOL_TEXT_FIELDS = {"mobile", "proxy", "hosting"}
_TEXT_FIELDS = {
    "name",
    "use_case",
    "auth_required",
    "username",
    "password",
    "certfile",
    "keyfile",
    "sticky_upstream",
    "upstream_protocol",
    "candidate_statuses",
    "countryCodes",
    "regions",
    "cities",
    "orgs",
    "isp",
    "asn",
    "continentCode",
    "zip_codes",
    "timezones",
}
_VALID_CANDIDATE_STATUSES = {
    "untested", "alive", "soft", "flaky", "cooling", "revived", "semi-revived", "dead"
}
_VALID_USE_CASES = {"web", "telegram", "scraping", "custom"}


def _parse_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return port


def _parse_bool(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"{field} must be a boolean")


def _is_local_bind(value):
    normalized = str(value or "").strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _normalize_server_config(data, *, existing=None):
    if not isinstance(data, dict):
        raise ValueError("A JSON object is required")
    normalized = dict(existing or {})
    normalized.update(data)

    port = _parse_port(normalized.get("port", 8080))
    protocol = str(normalized.get("protocol", "http")).strip().lower()
    if protocol not in PROTOCOLS:
        raise ValueError("protocol is invalid")
    rotate = str(normalized.get("rotate", "better_cost")).strip().lower()
    if rotate not in ROTATE_MODES:
        raise ValueError("rotate mode is invalid")
    bind = str(normalized.get("bind", "127.0.0.1")).strip()
    if not bind or len(bind) > 255 or any(char.isspace() for char in bind) or "/" in bind or "\\" in bind:
        raise ValueError("bind address is invalid")

    result = {
        "protocol": protocol,
        "bind": bind,
        "port": port,
        "rotate": rotate,
    }
    for field, default, minimum, maximum, cast in (
        ("rotate_interval", 60, 1, 86400, int),
        ("min_cost", 0.0, 0.0, 1_000_000.0, float),
        ("threads", 100, 1, 1000, int),
        ("timeout", 10.0, 1.0, 300.0, float),
        ("header_limit", 65536, 4096, 1048576, int),
    ):
        try:
            number = cast(normalized.get(field, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} is invalid") from exc
        if not minimum <= number <= maximum:
            raise ValueError(f"{field} is out of range")
        result[field] = number

    threshold = normalized.get("cost_threshold")
    if threshold not in (None, ""):
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError("cost_threshold is invalid") from exc
        if not 0.0 <= threshold <= 1_000_000.0:
            raise ValueError("cost_threshold is out of range")
        result["cost_threshold"] = threshold
    else:
        result["cost_threshold"] = None

    for field in _BOOL_FIELDS:
        result[field] = _parse_bool(normalized.get(field, False), field)

    for field in _OPTIONAL_BOOL_TEXT_FIELDS:
        value = normalized.get(field)
        if value in (None, ""):
            result[field] = None
        else:
            result[field] = "true" if _parse_bool(value, field) else "false"

    for field in _TEXT_FIELDS:
        value = normalized.get(field)
        if value in (None, ""):
            result[field] = None
            continue
        text = str(value).strip()
        if field == "name":
            max_length = 80
        elif field == "use_case":
            max_length = 32
        elif field in {"username", "password"}:
            max_length = 255
        else:
            max_length = 2048
        if len(text) > max_length or any(ord(char) < 32 for char in text):
            raise ValueError(f"{field} is invalid")
        result[field] = text

    use_case = str(result.get("use_case") or "custom").strip().lower()
    if use_case not in _VALID_USE_CASES:
        raise ValueError("use_case is invalid")
    result["use_case"] = use_case
    result["name"] = str(result.get("name") or f"{protocol.upper()} :{port}").strip()

    statuses = []
    for value in str(result.get("candidate_statuses") or "alive").split(","):
        status = value.strip().lower()
        if not status:
            continue
        if status not in _VALID_CANDIDATE_STATUSES:
            raise ValueError(f"candidate status is invalid: {status}")
        if status not in statuses:
            statuses.append(status)
    result["candidate_statuses"] = ",".join(statuses or ["alive"])

    upstream_protocols = []
    for value in str(result.get("upstream_protocol") or "").split(","):
        upstream = value.strip().lower()
        if not upstream:
            continue
        if upstream not in PROTOCOLS:
            raise ValueError(f"upstream protocol is invalid: {upstream}")
        if upstream not in upstream_protocols:
            upstream_protocols.append(upstream)
    result["upstream_protocol"] = ",".join(upstream_protocols) or None

    if data.get("clear_credentials") is True:
        result["username"] = None
        result["password"] = None
    elif existing:
        if data.get("username") in (None, ""):
            result["username"] = existing.get("username")
        if data.get("password") in (None, ""):
            result["password"] = existing.get("password")

    has_username = bool(result.get("username"))
    has_password = bool(result.get("password"))
    if protocol != "socks4" and has_username != has_password:
        raise ValueError("listener username and password must be configured together")
    if protocol == "socks4" and has_password:
        raise ValueError("SOCKS4 listener authentication supports UserID only; leave password empty")
    if bool(result.get("certfile")) != bool(result.get("keyfile")):
        raise ValueError("certfile and keyfile must be configured together")
    if result.get("cost_threshold") is not None and result["cost_threshold"] < result["min_cost"]:
        raise ValueError("cost_threshold cannot be lower than min_cost")
    if not _is_local_bind(bind) and not (has_username or result.get("allow_public_no_auth")):
        raise ValueError(
            "unauthenticated listeners beyond loopback are blocked; configure credentials or explicitly allow public no-auth"
        )
    return result


def _public_server_config(value):
    data = dict(value or {})
    had_credentials = bool(data.get("username") or data.get("password"))
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = had_credentials
    return data


def _public_proxy(proxy: Any) -> dict[str, Any]:
    data = proxy.to_dict()
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = bool(getattr(proxy, "username", None) or getattr(proxy, "password", None))
    return data


def _candidate_query(session, data, *, scope_query: Callable | None = None):
    from sqlalchemy import or_
    from database import Proxy

    query = session.query(Proxy)
    if scope_query is not None:
        query = scope_query(query)

    statuses = [item for item in str(data.get("candidate_statuses") or "alive").split(",") if item]
    if statuses:
        conditions = []
        for status in statuses:
            if status == "untested":
                conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
            else:
                conditions.append(Proxy.status == status)
        query = query.filter(or_(*conditions))

    if data.get("require_web_https"):
        query = query.filter(Proxy.web_https_ok.is_(True))
    if data.get("require_remote_dns"):
        query = query.filter(Proxy.remote_dns_ok.is_(True))
    if data.get("require_telegram"):
        query = query.filter(Proxy.telegram_ok.is_(True))

    protocols = [item for item in str(data.get("upstream_protocol") or "").split(",") if item]
    if protocols:
        query = query.filter(Proxy.protocol.in_(protocols))

    text_filters = {
        "countryCodes": Proxy.countryCode,
        "regions": Proxy.regionName,
        "cities": Proxy.city,
        "orgs": Proxy.org,
        "isp": Proxy.isp,
        "asn": Proxy.asn,
        "continentCode": Proxy.continentCode,
        "zip_codes": Proxy.zip,
        "timezones": Proxy.timezone,
    }
    for key, column in text_filters.items():
        values = [item.strip() for item in str(data.get(key) or "").split(",") if item.strip()]
        if values:
            query = query.filter(column.in_(values))

    for key, column in {"mobile": Proxy.mobile, "proxy": Proxy.proxy, "hosting": Proxy.hosting}.items():
        raw = data.get(key)
        if raw in ("true", "false"):
            query = query.filter(column == (1 if raw == "true" else 0))

    auth_filter = data.get("auth_required")
    if auth_filter == "auth":
        query = query.filter(Proxy.username.is_not(None), Proxy.username != "")
    elif auth_filter == "no_auth":
        query = query.filter(or_(Proxy.username.is_(None), Proxy.username == ""))

    return query


def _candidate_snapshot(
    session,
    data,
    *,
    sample_limit=5,
    scope_query: Callable | None = None,
    serializer: Callable[[Any], dict[str, Any]] | None = None,
):
    from sqlalchemy import or_
    from database import Proxy

    query = _candidate_query(session, data, scope_query=scope_query)
    total = query.count()
    by_protocol = {protocol: query.filter(Proxy.protocol == protocol).count() for protocol in PROTOCOLS}
    by_status = {}
    for status in _VALID_CANDIDATE_STATUSES:
        if status == "untested":
            count = query.filter(or_(Proxy.status == "untested", Proxy.status.is_(None))).count()
        else:
            count = query.filter(Proxy.status == status).count()
        if count:
            by_status[status] = count

    encode = serializer or _public_proxy
    samples = [
        encode(proxy)
        for proxy in query.order_by(Proxy.cost.asc(), Proxy.id.asc()).limit(sample_limit).all()
    ]
    return {
        "total": total,
        "by_protocol": by_protocol,
        "by_status": by_status,
        "samples": samples,
    }


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_log_tail(port, *, limit=100):
    log_file = Path(_project_root()) / f"server_{port}.log"
    if not log_file.exists() or not log_file.is_file():
        return []
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readlines()[-limit:]


def _remove_runtime_profile(port):
    from proxy_server.lifecycle import profile_path as server_profile_path

    with contextlib.suppress(FileNotFoundError, OSError, ValueError):
        os.unlink(server_profile_path(_project_root(), str(port)))
