import csv
import io
from typing import Iterable

import requests
from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from dashboard.config import PROTOCOLS
from dashboard.decorators import has_permission, login_required, require_permission
from dashboard.proxy_scope import (
    SAFE_FILTER_COLUMNS,
    apply_proxy_scope,
    credential_proxy_dict,
    public_proxy_dict,
)
from dashboard.security import api_error, resolve_public_http_url, validate_public_peer
from database import Proxy
from proxy_importer.utils.importer import normalize_proxy_line

import_export_bp = Blueprint("import_export", __name__)

_MAX_SOURCE_BYTES = 2_000_000
_MAX_SOURCE_URLS = 100
_MAX_IMPORT_LINES = 100_000


def get_db():
    if "db_session" not in g:
        from database import db

        g.db_session = db.get_session()
    return g.db_session


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _response_peer_ip(response) -> str:
    """Best-effort extraction of the connected socket peer from requests/urllib3."""
    raw = response.raw
    connections = [
        getattr(raw, "_connection", None),
        getattr(raw, "connection", None),
    ]
    for connection in connections:
        sock = getattr(connection, "sock", None)
        if sock is not None:
            return sock.getpeername()[0]

    # urllib3 may hand the socket through the wrapped http.client response.
    wrapped = getattr(getattr(getattr(raw, "_fp", None), "fp", None), "raw", None)
    sock = getattr(wrapped, "_sock", None)
    if sock is not None:
        return sock.getpeername()[0]
    raise ValueError("Could not verify the source connection peer")


def _fetch_public_text(url: str) -> str:
    safe_url, resolved_ips = resolve_public_http_url(url)
    client = requests.Session()
    client.trust_env = False  # Ignore ambient HTTP(S)_PROXY values for SSRF checks.
    response = None
    try:
        response = client.get(
            safe_url,
            timeout=(5, 20),
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "ProxyPool-SourceFetcher/1.0"},
        )
        validate_public_peer(_response_peer_ip(response), resolved_ips)
        if 300 <= response.status_code < 400:
            raise ValueError("Source redirects are blocked; use the final public URL")
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except (TypeError, ValueError):
                declared_size = None
            if declared_size is not None and declared_size > _MAX_SOURCE_BYTES:
                raise ValueError("Source response is larger than 2 MB")

        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > _MAX_SOURCE_BYTES:
                raise ValueError("Source response is larger than 2 MB")
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")
    finally:
        if response is not None:
            response.close()
        client.close()


def _parse_link_config(content: str) -> list[tuple[str, str]]:
    protocol = None
    sources = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            candidate = line[1:-1].strip().lower()
            protocol = candidate if candidate in PROTOCOLS else None
            continue
        if protocol:
            sources.append((protocol, line))
            if len(sources) > _MAX_SOURCE_URLS:
                raise ValueError(f"At most {_MAX_SOURCE_URLS} source URLs are allowed")
    return sources


def _proxy_payload(line: str, default_protocol: str):
    parsed = normalize_proxy_line(line, default_protocol)
    if not parsed:
        return None
    protocol, host, port, username, password = parsed
    protocol = str(protocol or "").lower()
    host = str(host or "").strip()
    if protocol not in PROTOCOLS or not host or len(host) > 255:
        return None
    if any(char.isspace() for char in host):
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    username = str(username or "")
    password = str(password or "")
    if len(username) > 255 or len(password) > 255:
        return None
    return {
        "protocol": protocol,
        "ip": host,
        "port": port,
        "username": username,
        "password": password,
    }


def _import_lines(db_session, protocol: str, lines: Iterable[str]):
    added = 0
    skipped = 0
    seen = set()
    for index, raw in enumerate(lines):
        if index >= _MAX_IMPORT_LINES:
            skipped += 1
            break
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        payload = _proxy_payload(line, protocol)
        if not payload:
            skipped += 1
            continue
        key = tuple(payload[field] for field in ("protocol", "ip", "port", "username", "password"))
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        exists = db_session.query(Proxy.id).filter_by(**payload).first()
        if exists:
            skipped += 1
            continue
        db_session.add(Proxy(**payload, cost=1.0))
        added += 1
    return added, skipped


def _apply_export_filters(query):
    proto = request.args.get("proto", "all")
    status = request.args.get("status", "all")
    search = request.args.get("search", "").strip()[:255]
    ip_filter = request.args.get("ip", "").strip()[:255]
    country_filter = request.args.get("country", "").strip()[:32]
    isp_filter = request.args.get("isp", "").strip()[:255]

    if proto != "all" and proto in PROTOCOLS:
        query = query.filter(Proxy.protocol == proto)
    if status and status != "all":
        conditions = []
        for value in [part.strip() for part in status.split(",") if part.strip()]:
            if value == "untested":
                conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
            else:
                conditions.append(Proxy.status == value)
        if conditions:
            query = query.filter(or_(*conditions))
    if search:
        value = f"%{search}%"
        query = query.filter(
            or_(
                Proxy.ip.like(value),
                Proxy.countryCode.like(value),
                Proxy.isp.like(value),
                Proxy.city.like(value),
                Proxy.regionName.like(value),
            )
        )
    if ip_filter:
        query = query.filter(Proxy.ip.like(f"%{ip_filter}%"))
    if country_filter:
        query = query.filter(Proxy.countryCode.like(f"%{country_filter}%"))
    if isp_filter:
        query = query.filter(Proxy.isp.like(f"%{isp_filter}%"))

    capabilities = {item.strip() for item in request.args.get("capability", "").split(",") if item.strip()}
    if "web_https" in capabilities:
        query = query.filter(Proxy.web_https_ok.is_(True))
    if "remote_dns" in capabilities:
        query = query.filter(Proxy.remote_dns_ok.is_(True))
    if "telegram" in capabilities:
        query = query.filter(Proxy.telegram_ok.is_(True))
    return query


def _csv_value(value):
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@import_export_bp.route("/api/import", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    mode = str(data.get("mode", ""))
    db_session = get_db()

    try:
        if mode == "manual":
            content = str(data.get("proxies", ""))
            if len(content.encode("utf-8")) > _MAX_SOURCE_BYTES:
                return api_error("Manual import is larger than 2 MB", 413, "payload_too_large")
            added, skipped = _import_lines(db_session, "http", content.splitlines())
        elif mode == "url":
            protocol = str(data.get("protocol", "http")).lower()
            if protocol not in PROTOCOLS:
                return api_error("Invalid protocol", 400, "invalid_protocol")
            text = _fetch_public_text(str(data.get("url", "")))
            added, skipped = _import_lines(db_session, protocol, text.splitlines())
        elif mode == "links":
            content = str(data.get("content", ""))
            if len(content.encode("utf-8")) > 128_000:
                return api_error("Source configuration is too large", 413, "payload_too_large")
            sources = _parse_link_config(content)
            if not sources:
                return api_error("No valid source URLs found", 400, "invalid_sources")
            added = skipped = 0
            for protocol, url in sources:
                text = _fetch_public_text(url)
                source_added, source_skipped = _import_lines(db_session, protocol, text.splitlines())
                added += source_added
                skipped += source_skipped
        else:
            return api_error("mode must be manual, url, or links", 400, "invalid_mode")

        db_session.commit()
        return jsonify({"success": True, "added": added, "skipped": skipped})
    except IntegrityError:
        db_session.rollback()
        return api_error("Import contained conflicting rows", 409, "duplicate_proxy")
    except (requests.RequestException, ValueError) as exc:
        db_session.rollback()
        return api_error(str(exc), 400, "source_fetch_failed")
    except Exception:
        db_session.rollback()
        return api_error("Import failed", 500, "import_failed")


@import_export_bp.route("/api/import/count-url", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_count_url():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    protocol = str(data.get("protocol", "http")).lower()
    if protocol not in PROTOCOLS:
        return api_error("Invalid protocol", 400, "invalid_protocol")
    try:
        text = _fetch_public_text(str(data.get("url", "")))
        count = sum(
            1
            for index, line in enumerate(text.splitlines())
            if index < _MAX_IMPORT_LINES and _proxy_payload(line.strip(), protocol)
        )
        return jsonify({"success": True, "count": count})
    except (requests.RequestException, ValueError) as exc:
        return api_error(str(exc), 400, "source_fetch_failed")
    except Exception:
        return api_error("Could not inspect source", 500, "source_fetch_failed")


@import_export_bp.route("/api/export", methods=["GET"])
@login_required
@require_permission("proxies.export")
def api_export():
    fmt = request.args.get("format", "txt").lower()
    if fmt not in {"txt", "csv", "json"}:
        return api_error("format must be txt, csv, or json", 400, "invalid_format")

    include_credentials = request.args.get("include_credentials", "false").lower() in {"1", "true", "yes"}
    if include_credentials and not has_permission("proxies.credentials"):
        return api_error("Credential export requires proxies.credentials", 403, "permission_denied")

    db_session = get_db()
    rows = _apply_export_filters(apply_proxy_scope(db_session.query(Proxy))).all()
    serializer = credential_proxy_dict if include_credentials else public_proxy_dict

    requested = [item.strip() for item in request.args.get("columns", "").split(",") if item.strip()]
    column_map = {
        "protocol": "protocol",
        "port": "port",
        "cost": "cost",
        "speed": "speed_ms",
        "alive": "alive_hits",
        "fails": "fail_hits",
        "country": "countryCode",
        "region": "regionName",
        "city": "city",
        "isp": "isp",
        "asn": "asn",
        "org": "org",
        "mobile": "mobile",
        "hosting": "hosting",
        "lastalive": "last_alive",
        "lastcheck": "last_checked",
    }
    selected = ["ip"] + [column_map[item] for item in requested if item in column_map] if requested else None

    data = []
    for proxy in rows:
        item = serializer(proxy)
        if selected:
            item = {key: item.get(key) for key in selected if key in SAFE_FILTER_COLUMNS or key == "ip"}
        if include_credentials and proxy.username and proxy.password:
            item["proxy_url"] = f"{proxy.protocol}://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        data.append(item)

    if fmt == "json":
        return jsonify({"success": True, "count": len(data), "proxies": data})

    if not data:
        return Response("", mimetype="text/csv" if fmt == "csv" else "text/plain")

    output = io.StringIO(newline="")
    fields = list(data[0].keys())
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if fmt == "csv":
        writer.writeheader()
    for item in data:
        writer.writerow({key: _csv_value(item.get(key)) for key in fields})

    content_type = "text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8"
    response = Response(output.getvalue(), content_type=content_type)
    response.headers["Content-Disposition"] = f'attachment; filename="proxies.{fmt}"'
    return response
