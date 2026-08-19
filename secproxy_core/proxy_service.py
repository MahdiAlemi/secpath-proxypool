from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import or_

from secproxy_core.errors import ConflictError
from secproxy_core.net import validate_public_http_url

PROTOCOLS = ("http", "https", "socks4", "socks5")
STATUSES = (
    "untested",
    "alive",
    "soft",
    "flaky",
    "cooling",
    "revived",
    "semi-revived",
    "dead",
)


def _protocol(value: str) -> str:
    result = str(value or "").strip().lower()
    if result not in PROTOCOLS:
        raise ValueError("protocol must be one of: " + ", ".join(PROTOCOLS))
    return result


def _status(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    result = str(value).strip().lower()
    if result not in STATUSES:
        raise ValueError("status must be one of: " + ", ".join(STATUSES))
    return result


def _ip(value: str) -> str:
    raw = str(value or "").strip().strip("[]")
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError as exc:
        raise ValueError("ip must be a valid IPv4 or IPv6 address") from exc


def _port(value: int | str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    if not 1 <= result <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return result


def _credential(value: str | None, field: str) -> str:
    if value in (None, ""):
        return ""
    result = str(value)
    if len(result) > 255 or any(ord(char) < 32 for char in result):
        raise ValueError(f"{field} is invalid")
    return result


def _apply_filters(
    query,
    Proxy,
    *,
    protocol: str | None = None,
    status: str | None = None,
    country: str | None = None,
    https_only: bool = False,
    remote_dns_only: bool = False,
    telegram_only: bool = False,
):
    if protocol:
        query = query.filter(Proxy.protocol == _protocol(protocol))
    normalized_status = _status(status)
    if normalized_status:
        if normalized_status == "untested":
            query = query.filter(or_(Proxy.status == "untested", Proxy.status.is_(None)))
        else:
            query = query.filter(Proxy.status == normalized_status)
    if country:
        code = str(country).strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country must be a two-letter ISO country code")
        query = query.filter(Proxy.countryCode == code)
    if https_only:
        query = query.filter(Proxy.web_https_ok.is_(True))
    if remote_dns_only:
        query = query.filter(Proxy.remote_dns_ok.is_(True))
    if telegram_only:
        query = query.filter(Proxy.telegram_ok.is_(True))
    return query


def _public_proxy_dict(proxy: Any, *, detailed: bool = False) -> dict[str, Any]:
    item = {
        "id": proxy.id,
        "protocol": proxy.protocol,
        "ip": proxy.ip,
        "port": proxy.port,
        "status": proxy.status or "untested",
        "speed_ms": proxy.speed_ms,
        "country": proxy.countryCode,
        "web_http_ok": bool(proxy.web_http_ok),
        "web_https_ok": bool(proxy.web_https_ok),
        "remote_dns_ok": bool(proxy.remote_dns_ok),
        "telegram_ok": bool(proxy.telegram_ok),
        "has_auth": bool(getattr(proxy, "username", "") or getattr(proxy, "password", "")),
    }
    if detailed:
        item.update(
            {
                "resolved_ip": proxy.resolved_ip,
                "cost": proxy.cost,
                "alive_hits": proxy.alive_hits,
                "fail_hits": proxy.fail_hits,
                "total_checks": proxy.total_checks,
                "reliability": proxy.reliability,
                "last_alive": proxy.last_alive.isoformat() if proxy.last_alive else None,
                "last_checked": proxy.last_checked.isoformat() if proxy.last_checked else None,
                "last_fail": proxy.last_fail.isoformat() if proxy.last_fail else None,
                "city": proxy.city,
                "isp": proxy.isp,
                "org": proxy.org,
                "asn": proxy.asn,
                "exit_ip": proxy.exit_ip,
                "validation_profile": proxy.validation_profile,
                "validation_summary": proxy.validation_summary,
            }
        )
    return item


def list_proxies(
    *,
    protocol: str | None = None,
    status: str | None = None,
    country: str | None = None,
    https_only: bool = False,
    remote_dns_only: bool = False,
    telegram_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    from database import Proxy, db

    if not 1 <= int(limit) <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    if int(offset) < 0:
        raise ValueError("offset cannot be negative")

    with db.session() as session:
        query = _apply_filters(
            session.query(Proxy),
            Proxy,
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns_only,
            telegram_only=telegram_only,
        )
        rows = query.order_by(Proxy.id.asc()).offset(int(offset)).limit(int(limit)).all()
        return [_public_proxy_dict(row) for row in rows]


def get_proxy(proxy_id: int) -> dict[str, Any] | None:
    from database import Proxy, db

    with db.session() as session:
        row = session.query(Proxy).filter(Proxy.id == int(proxy_id)).first()
        return _public_proxy_dict(row, detailed=True) if row is not None else None


def count_proxies(
    *,
    protocol: str | None = None,
    status: str | None = None,
    country: str | None = None,
    https_only: bool = False,
    remote_dns_only: bool = False,
    telegram_only: bool = False,
) -> int:
    from database import Proxy, db

    with db.session() as session:
        query = _apply_filters(
            session.query(Proxy),
            Proxy,
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns_only,
            telegram_only=telegram_only,
        )
        return int(query.count())


def add_proxy(
    *,
    protocol: str,
    ip: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    from database import Proxy, db

    normalized = {
        "protocol": _protocol(protocol),
        "ip": _ip(ip),
        "port": _port(port),
        "username": _credential(username, "username"),
        "password": _credential(password, "password"),
    }
    with db.session() as session:
        duplicate = session.query(Proxy).filter_by(**normalized).first()
        if duplicate is not None:
            raise ConflictError(f"proxy already exists as id {duplicate.id}")
        row = Proxy(**normalized)
        session.add(row)
        session.flush()
        return _public_proxy_dict(row, detailed=True)


def update_proxy(proxy_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    from database import Proxy, db

    allowed = {"protocol", "ip", "port", "username", "password", "clear_credentials"}
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise ValueError("unsupported proxy fields: " + ", ".join(unknown))

    with db.session() as session:
        row = session.query(Proxy).filter(Proxy.id == int(proxy_id)).first()
        if row is None:
            return None

        protocol = _protocol(changes.get("protocol", row.protocol))
        ip = _ip(changes.get("ip", row.ip))
        port = _port(changes.get("port", row.port))

        if changes.get("clear_credentials"):
            username = ""
            password = ""
        else:
            username = _credential(
                row.username if changes.get("username") is None else changes.get("username"),
                "username",
            )
            password = _credential(
                row.password if changes.get("password") is None else changes.get("password"),
                "password",
            )

        duplicate = (
            session.query(Proxy)
            .filter(
                Proxy.id != row.id,
                Proxy.protocol == protocol,
                Proxy.ip == ip,
                Proxy.port == port,
                Proxy.username == username,
                Proxy.password == password,
            )
            .first()
        )
        if duplicate is not None:
            raise ConflictError(f"updated identity duplicates proxy id {duplicate.id}")

        identity_changed = any(
            (
                row.protocol != protocol,
                row.ip != ip,
                int(row.port) != int(port),
                (row.username or "") != username,
                (row.password or "") != password,
            )
        )

        row.protocol = protocol
        row.ip = ip
        row.port = port
        row.username = username
        row.password = password

        # A changed endpoint/credential identity has never been validated in its new form.
        if identity_changed:
            row.resolved_ip = None
            row.status = "untested"
            row.speed_ms = None
            row.web_http_ok = False
            row.web_https_ok = False
            row.remote_dns_ok = False
            row.telegram_ok = False
            row.exit_ip = None
            row.validation_profile = None
            row.validation_summary = None
            row.last_checked = None
            row.last_alive = None
            row.last_fail = None
            row.alive_hits = 0
            row.fail_hits = 0
            row.total_checks = 0
            row.consecutive_fails = 0
            row.is_cooling = 0
            row.previous_state = None
            row.last_transition = None

        session.flush()
        return _public_proxy_dict(row, detailed=True)


def delete_proxy(proxy_id: int) -> dict[str, Any] | None:
    from database import Proxy, db

    with db.session() as session:
        row = session.query(Proxy).filter(Proxy.id == int(proxy_id)).first()
        if row is None:
            return None
        result = _public_proxy_dict(row)
        session.delete(row)
        return result


def purge_proxies(
    *,
    protocol: str | None = None,
    status: str | None = None,
    country: str | None = None,
    dry_run: bool = True,
    max_delete: int = 100000,
) -> dict[str, Any]:
    from database import Proxy, db

    if not any((protocol, status, country)):
        raise ValueError("purge requires at least one of --protocol, --status, or --country")

    with db.session() as session:
        query = _apply_filters(
            session.query(Proxy),
            Proxy,
            protocol=protocol,
            status=status,
            country=country,
        )
        count = int(query.count())
        if count > int(max_delete):
            raise ConflictError(
                f"purge matched {count} proxies, above safety limit {max_delete}"
            )
        sample = [
            _public_proxy_dict(row)
            for row in query.order_by(Proxy.id.asc()).limit(10).all()
        ]
        if not dry_run:
            query.delete(synchronize_session=False)
        return {
            "matched": count,
            "deleted": 0 if dry_run else count,
            "dry_run": bool(dry_run),
            "sample": sample,
            "filters": {
                "protocol": protocol,
                "status": status,
                "country": country,
            },
        }


def _row_with_credentials(proxy: Any) -> dict[str, Any]:
    data = _public_proxy_dict(proxy, detailed=False)
    data["username"] = proxy.username or ""
    data["password"] = proxy.password or ""
    return data


def export_rows(
    *,
    protocol: str | None = None,
    status: str | None = None,
    country: str | None = None,
    https_only: bool = False,
    remote_dns_only: bool = False,
    telegram_only: bool = False,
    include_credentials: bool = False,
    limit: int = 100000,
) -> list[dict[str, Any]]:
    from database import Proxy, db

    if not 1 <= int(limit) <= 1000000:
        raise ValueError("limit must be between 1 and 1000000")

    with db.session() as session:
        query = _apply_filters(
            session.query(Proxy),
            Proxy,
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns_only,
            telegram_only=telegram_only,
        )
        proxies = query.order_by(Proxy.id.asc()).limit(int(limit)).all()
        encode = _row_with_credentials if include_credentials else _public_proxy_dict
        return [encode(row) for row in proxies]


def _proxy_uri(row: dict[str, Any], *, include_credentials: bool = False) -> str:
    protocol = row["protocol"]
    host = row["ip"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    auth = ""
    if include_credentials and (row.get("username") or row.get("password")):
        user = quote(str(row.get("username") or ""), safe="")
        password = quote(str(row.get("password") or ""), safe="")
        auth = f"{user}:{password}@"
    return f"{protocol}://{auth}{host}:{row['port']}"


def render_export(
    rows: list[dict[str, Any]],
    *,
    format: str,
    include_credentials: bool = False,
) -> str:
    fmt = str(format).lower()
    if fmt not in {"txt", "urls", "csv", "json"}:
        raise ValueError("format must be one of: txt, urls, csv, json")

    if fmt == "json":
        return json.dumps(rows, indent=2, sort_keys=True, default=str) + "\n"

    if fmt == "urls":
        return "".join(
            _proxy_uri(row, include_credentials=include_credentials) + "\n"
            for row in rows
        )

    if fmt == "txt":
        lines = []
        for row in rows:
            host = row["ip"]
            if ":" in host:
                host = f"[{host}]"
            if include_credentials and (row.get("username") or row.get("password")):
                lines.append(
                    f"{row['protocol']}://"
                    f"{quote(str(row.get('username') or ''), safe='')}:"
                    f"{quote(str(row.get('password') or ''), safe='')}@"
                    f"{host}:{row['port']}"
                )
            else:
                lines.append(f"{row['protocol']}://{host}:{row['port']}")
        return "\n".join(lines) + ("\n" if lines else "")

    output = io.StringIO()
    fieldnames = [
        "id",
        "protocol",
        "ip",
        "port",
        "status",
        "speed_ms",
        "country",
        "web_http_ok",
        "web_https_ok",
        "remote_dns_ok",
        "telegram_ok",
        "has_auth",
    ]
    if include_credentials:
        fieldnames.extend(["username", "password"])
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def write_export(path: str | Path, content: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".secproxy.tmp")
    temp.write_text(content, encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    os.chmod(target, 0o600)
    return {
        "path": str(target.resolve()),
        "bytes": target.stat().st_size,
    }


def _upstream_uri(proxy: Any) -> str:
    host = proxy.ip
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    auth = ""
    if proxy.username or proxy.password:
        auth = (
            f"{quote(str(proxy.username or ''), safe='')}:"
            f"{quote(str(proxy.password or ''), safe='')}@"
        )
    scheme = proxy.protocol
    if scheme == "socks5":
        scheme = "socks5h"
    return f"{scheme}://{auth}{host}:{proxy.port}"


def test_proxy(
    proxy_id: int,
    *,
    url: str = "https://example.com/",
    connect_timeout: float = 3.0,
    read_timeout: float = 5.0,
) -> dict[str, Any] | None:
    import requests
    from database import Proxy, db

    target = validate_public_http_url(url)

    connect_timeout_value = float(connect_timeout)
    read_timeout_value = float(read_timeout)
    if not 0.5 <= connect_timeout_value <= 30.0:
        raise ValueError("connect timeout must be between 0.5 and 30 seconds")
    if not 1.0 <= read_timeout_value <= 60.0:
        raise ValueError("read timeout must be between 1 and 60 seconds")

    with db.session() as session:
        proxy = session.query(Proxy).filter(Proxy.id == int(proxy_id)).first()
        if proxy is None:
            return None
        uri = _upstream_uri(proxy)
        public = _public_proxy_dict(proxy)

    started = time.perf_counter()
    request_session = requests.Session()
    request_session.trust_env = False

    try:
        response = request_session.get(
            target,
            proxies={"http": uri, "https": uri},
            timeout=(connect_timeout_value, read_timeout_value),
            allow_redirects=False,
            stream=True,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status_code = int(response.status_code)
        response.close()
        return {
            "ok": 200 <= status_code < 500,
            "stage": "response",
            "proxy": public,
            "target": target,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "error": None,
            "error_type": None,
            "mutated": False,
        }
    except requests.exceptions.ConnectTimeout as exc:
        stage = "connect"
        error_type = "connect_timeout"
        error_text = str(exc)[:500]
    except requests.exceptions.ReadTimeout as exc:
        stage = "read"
        error_type = "read_timeout"
        error_text = str(exc)[:500]
    except requests.exceptions.ProxyError as exc:
        stage = "proxy_connect"
        error_type = "proxy_error"
        error_text = str(exc)[:500]
    except requests.exceptions.SSLError as exc:
        stage = "tls"
        error_type = "tls_error"
        error_text = str(exc)[:500]
    except requests.RequestException as exc:
        stage = "request"
        error_type = exc.__class__.__name__
        error_text = str(exc)[:500]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": False,
        "stage": stage,
        "proxy": public,
        "target": target,
        "status_code": None,
        "elapsed_ms": elapsed_ms,
        "error": error_text,
        "error_type": error_type,
        "mutated": False,
    }
