"""Import collection, preview, and commit helpers.

The module keeps source fetching and parsing outside Flask route handlers so the
same rules power quick imports, saved sources, previews, and regression tests.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from sqlalchemy import and_, or_

from dashboard.config import PROTOCOLS
from dashboard.security import resolve_public_http_url, validate_public_peer
from database import Proxy
from proxy_importer.utils.importer import normalize_proxy_line

MAX_SOURCE_BYTES = 2_000_000
MAX_BATCH_BYTES = 10_000_000
MAX_SOURCE_CONFIG_BYTES = 128_000
MAX_SOURCE_URLS = 100
MAX_IMPORT_LINES = 100_000
MAX_PREVIEW_SAMPLES = 10


class ImportInputError(ValueError):
    """Raised when an import request cannot be processed safely."""


@dataclass
class SourceText:
    text: str
    size: int


def _response_peer_ip(response) -> str:
    """Best-effort extraction of the connected socket peer from requests."""
    raw = response.raw
    for connection in (getattr(raw, "_connection", None), getattr(raw, "connection", None)):
        sock = getattr(connection, "sock", None)
        if sock is not None:
            return sock.getpeername()[0]

    wrapped = getattr(getattr(getattr(raw, "_fp", None), "fp", None), "raw", None)
    sock = getattr(wrapped, "_sock", None)
    if sock is not None:
        return sock.getpeername()[0]
    raise ImportInputError("Could not verify the source connection peer")


def fetch_public_text(url: str) -> SourceText:
    safe_url, resolved_ips = resolve_public_http_url(url)
    client = requests.Session()
    client.trust_env = False
    response = None
    try:
        response = client.get(
            safe_url,
            timeout=(5, 20),
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "ProxyPool-SourceFetcher/2.0"},
        )
        validate_public_peer(_response_peer_ip(response), resolved_ips)
        if 300 <= response.status_code < 400:
            raise ImportInputError("Source redirects are blocked; use the final public URL")
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except (TypeError, ValueError):
                declared_size = None
            if declared_size is not None and declared_size > MAX_SOURCE_BYTES:
                raise ImportInputError("Source response is larger than 2 MB")

        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise ImportInputError("Source response is larger than 2 MB")
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        return SourceText(b"".join(chunks).decode(encoding, errors="replace"), size)
    finally:
        if response is not None:
            response.close()
        client.close()


def redact_source_url(url: str) -> str:
    """Return a display-safe URL without credentials, query, or fragment."""
    try:
        parsed = urlsplit(str(url or "").strip())
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = parsed.path or "/"
        return urlunsplit((parsed.scheme, host, path, "", ""))
    except (TypeError, ValueError):
        return "invalid source"


def safe_source_error(error, url: str) -> str:
    """Remove URL credentials and query tokens from fetch errors."""
    message = str(error or "Source fetch failed")
    raw = str(url or "").strip()
    if raw:
        message = message.replace(raw, redact_source_url(raw))
    return message[:1000]


def parse_link_config(content: str) -> list[tuple[str, str]]:
    protocol = None
    sources: list[tuple[str, str]] = []
    for raw in str(content or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            candidate = line[1:-1].strip().lower()
            protocol = candidate if candidate in PROTOCOLS else None
            continue
        if protocol:
            sources.append((protocol, line))
            if len(sources) > MAX_SOURCE_URLS:
                raise ImportInputError(f"At most {MAX_SOURCE_URLS} source URLs are allowed")
    return sources


def proxy_payload(line: str, default_protocol: str):
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


def proxy_key(payload: dict) -> tuple:
    return tuple(payload[field] for field in ("protocol", "ip", "port", "username", "password"))


def display_endpoint(payload: dict) -> str:
    host = payload["ip"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{payload['protocol']}://{host}:{payload['port']}"


def _base_collection(mode: str) -> dict:
    return {
        "mode": mode,
        "total_lines": 0,
        "ignored": 0,
        "invalid": 0,
        "input_duplicates": 0,
        "truncated": False,
        "protocols": Counter(),
        "payloads": [],
        "samples": [],
        "sources": [],
        "errors": [],
    }


def _parse_batch(
    collection: dict,
    *,
    label: str,
    protocol: str,
    lines: Iterable[str],
    remaining_lines: int,
) -> int:
    source = {
        "label": label,
        "protocol": protocol,
        "status": "ready",
        "total_lines": 0,
        "valid": 0,
        "invalid": 0,
        "input_duplicates": 0,
        "new": 0,
        "existing": 0,
        "error": None,
        "_keys": set(),
    }
    collection["sources"].append(source)
    seen = collection.setdefault("_seen", set())
    consumed = 0

    for raw in lines:
        if consumed >= remaining_lines:
            collection["truncated"] = True
            break
        consumed += 1
        source["total_lines"] += 1
        collection["total_lines"] += 1
        line = str(raw or "").strip()
        if not line or line.startswith(("#", ";")):
            collection["ignored"] += 1
            continue
        payload = proxy_payload(line, protocol)
        if not payload:
            source["invalid"] += 1
            collection["invalid"] += 1
            continue
        key = proxy_key(payload)
        if key in seen:
            source["input_duplicates"] += 1
            collection["input_duplicates"] += 1
            continue
        seen.add(key)
        source["_keys"].add(key)
        source["valid"] += 1
        collection["protocols"][payload["protocol"]] += 1
        collection["payloads"].append(payload)
        if len(collection["samples"]) < MAX_PREVIEW_SAMPLES:
            collection["samples"].append(
                {
                    "endpoint": display_endpoint(payload),
                    "protocol": payload["protocol"],
                    "has_auth": bool(payload["username"] or payload["password"]),
                    "key": key,
                }
            )
    return consumed


def collect_import(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ImportInputError("A JSON object is required")
    mode = str(data.get("mode", "")).strip().lower()
    if mode not in {"manual", "url", "links"}:
        raise ImportInputError("mode must be manual, url, or links")

    collection = _base_collection(mode)
    remaining = MAX_IMPORT_LINES

    if mode == "manual":
        content = str(data.get("proxies", data.get("content", "")))
        if not content.strip():
            raise ImportInputError("Paste or upload at least one proxy")
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ImportInputError("Manual import is larger than 2 MB")
        protocol = str(data.get("protocol", "http")).lower()
        if protocol not in PROTOCOLS:
            raise ImportInputError("Invalid protocol")
        _parse_batch(
            collection,
            label="Manual input",
            protocol=protocol,
            lines=content.splitlines(),
            remaining_lines=remaining,
        )

    elif mode == "url":
        protocol = str(data.get("protocol", "http")).lower()
        if protocol not in PROTOCOLS:
            raise ImportInputError("Invalid protocol")
        url = str(data.get("url", "")).strip()
        if not url:
            raise ImportInputError("Source URL is required")
        try:
            fetched = fetch_public_text(url)
        except (requests.RequestException, ImportInputError, ValueError) as exc:
            raise ImportInputError(safe_source_error(exc, url)) from exc
        _parse_batch(
            collection,
            label=redact_source_url(url),
            protocol=protocol,
            lines=fetched.text.splitlines(),
            remaining_lines=remaining,
        )

    else:
        content = str(data.get("content", ""))
        if not content.strip():
            raise ImportInputError("Source configuration is required")
        if len(content.encode("utf-8")) > MAX_SOURCE_CONFIG_BYTES:
            raise ImportInputError("Source configuration is too large")
        sources = parse_link_config(content)
        if not sources:
            raise ImportInputError("No valid source URLs found")
        total_bytes = 0
        for protocol, url in sources:
            if remaining <= 0:
                collection["truncated"] = True
                break
            try:
                fetched = fetch_public_text(url)
                total_bytes += fetched.size
                if total_bytes > MAX_BATCH_BYTES:
                    raise ImportInputError("Combined source responses are larger than 10 MB")
                consumed = _parse_batch(
                    collection,
                    label=redact_source_url(url),
                    protocol=protocol,
                    lines=fetched.text.splitlines(),
                    remaining_lines=remaining,
                )
                remaining -= consumed
            except (requests.RequestException, ImportInputError, ValueError) as exc:
                error = safe_source_error(exc, url)
                collection["errors"].append(error)
                collection["sources"].append(
                    {
                        "label": redact_source_url(url),
                        "protocol": protocol,
                        "status": "failed",
                        "total_lines": 0,
                        "valid": 0,
                        "invalid": 0,
                        "input_duplicates": 0,
                        "new": 0,
                        "existing": 0,
                        "error": error,
                        "_keys": set(),
                    }
                )

    collection.pop("_seen", None)
    return collection


def _existing_proxy_keys(db_session, payloads: list[dict]) -> set[tuple]:
    keys = [proxy_key(payload) for payload in payloads]
    existing: set[tuple] = set()
    batch_size = 100
    for start in range(0, len(keys), batch_size):
        clauses = [
            and_(
                Proxy.protocol == key[0],
                Proxy.ip == key[1],
                Proxy.port == key[2],
                Proxy.username == key[3],
                Proxy.password == key[4],
            )
            for key in keys[start : start + batch_size]
        ]
        if not clauses:
            continue
        rows = (
            db_session.query(Proxy.protocol, Proxy.ip, Proxy.port, Proxy.username, Proxy.password)
            .filter(or_(*clauses))
            .all()
        )
        existing.update(tuple(row) for row in rows)
    return existing


def _finalize_collection(collection: dict, existing_keys: set[tuple]) -> dict:
    for source in collection["sources"]:
        keys = source.pop("_keys", set())
        source["existing"] = len(keys & existing_keys)
        source["new"] = len(keys - existing_keys)
    for sample in collection["samples"]:
        key = sample.pop("key")
        sample["state"] = "existing" if key in existing_keys else "new"

    valid = len(collection["payloads"])
    existing = len(existing_keys)
    collection["summary"] = {
        "total_lines": collection["total_lines"],
        "valid": valid,
        "new": max(0, valid - existing),
        "existing": existing,
        "invalid": collection["invalid"],
        "input_duplicates": collection["input_duplicates"],
        "ignored": collection["ignored"],
        "truncated": bool(collection["truncated"]),
    }
    collection["protocols"] = dict(collection["protocols"])
    return collection


def preview_import(db_session, data: dict) -> dict:
    collection = collect_import(data)
    existing = _existing_proxy_keys(db_session, collection["payloads"])
    _finalize_collection(collection, existing)
    collection.pop("payloads", None)
    return collection


def execute_import(db_session, data: dict) -> dict:
    collection = collect_import(data)
    existing = _existing_proxy_keys(db_session, collection["payloads"])
    _finalize_collection(collection, existing)

    added = 0
    for payload in collection["payloads"]:
        if proxy_key(payload) in existing:
            continue
        db_session.add(Proxy(**payload, cost=1.0))
        added += 1

    summary = collection["summary"]
    summary["added"] = added
    summary["skipped"] = (
        summary["existing"] + summary["invalid"] + summary["input_duplicates"]
    )
    collection["status"] = "partial" if collection["errors"] else "completed"
    collection.pop("payloads", None)
    return collection
