"""Security primitives for the Flask dashboard.

The module intentionally has no optional third-party dependency. It provides
CSRF protection for cookie-authenticated browser requests, conservative
security headers, small in-process login throttling, and URL validation for
remote proxy-source imports.
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
import threading
import time
from collections import defaultdict, deque
from typing import Iterable
from urllib.parse import urlparse

from flask import current_app, jsonify, request, session

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def api_error(message: str, status: int = 400, code: str = "request_error"):
    """Return the backward-compatible API error shape with a stable code."""
    return jsonify({"success": False, "error": message, "code": code}), status


def ensure_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _is_bearer_request() -> bool:
    value = request.headers.get("Authorization", "")
    return value.startswith("Bearer ") and len(value) > len("Bearer ")


def _csrf_exempt_endpoint() -> bool:
    return request.endpoint in {"api_login"}


def _remote_identity() -> str:
    # Do not trust X-Forwarded-For unless a trusted proxy is configured in a
    # later deployment-specific phase.
    return request.remote_addr or "unknown"


def rate_limited(bucket: str, *, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    key = (bucket, _remote_identity())
    with _RATE_LOCK:
        entries = _RATE_BUCKETS[key]
        cutoff = now - window_seconds
        while entries and entries[0] < cutoff:
            entries.popleft()
        return len(entries) >= limit


def record_rate_limit_hit(bucket: str) -> None:
    with _RATE_LOCK:
        _RATE_BUCKETS[(bucket, _remote_identity())].append(time.monotonic())


def clear_rate_limit(bucket: str) -> None:
    with _RATE_LOCK:
        _RATE_BUCKETS.pop((bucket, _remote_identity()), None)


def _is_forbidden_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def resolve_public_http_url(url: str) -> tuple[str, frozenset[str]]:
    """Validate a source URL and return its initially resolved public IPs."""
    value = str(url or "").strip()
    if not value or len(value) > 2048:
        raise ValueError("A valid URL is required")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL hostname is required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials in source URLs are not allowed")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc

    try:
        addresses: Iterable[tuple] = socket.getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc

    resolved = {
        str(ipaddress.ip_address(entry[4][0].split("%", 1)[0]))
        for entry in addresses
    }
    if not resolved:
        raise ValueError("URL hostname did not resolve")
    if any(_is_forbidden_ip(address) for address in resolved):
        raise ValueError("Local, private, reserved, and link-local URLs are blocked")

    return value, frozenset(resolved)


def validate_public_http_url(url: str) -> str:
    """Backward-compatible URL validator used by non-fetching callers."""
    return resolve_public_http_url(url)[0]


def validate_public_peer(peer_ip: str, allowed_ips: Iterable[str]) -> None:
    """Reject private peers and DNS-rebinding/mismatched connections."""
    try:
        normalized = str(ipaddress.ip_address(str(peer_ip).split("%", 1)[0]))
    except ValueError as exc:
        raise ValueError("Source connection peer is invalid") from exc
    if _is_forbidden_ip(normalized):
        raise ValueError("Source connection reached a blocked network address")
    if normalized not in {str(ipaddress.ip_address(item)) for item in allowed_ips}:
        raise ValueError("Source connection did not match validated DNS results")


def init_security(app) -> None:
    app.jinja_env.globals["csrf_token"] = ensure_csrf_token

    @app.before_request
    def _csrf_protect():
        ensure_csrf_token()
        if current_app.config.get("TESTING") and not current_app.config.get("TEST_CSRF_ENABLED"):
            return None
        if request.method in _SAFE_METHODS or _csrf_exempt_endpoint():
            return None
        if _is_bearer_request():
            return None

        expected = session.get("_csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if expected and supplied and secrets.compare_digest(expected, supplied):
            return None
        if request.path.startswith("/api/"):
            return api_error("CSRF token is missing or invalid", 403, "csrf_failed")
        return "CSRF token is missing or invalid", 403

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        # Compatible with the legacy inline-heavy dashboard. Phase 2 will
        # remove inline handlers and tighten script-src/style-src.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        )
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            # Older routes may still return {success: false} with HTTP 200.
            # Preserve their payload while enforcing a usable API contract.
            if response.status_code < 400 and response.is_json:
                payload = response.get_json(silent=True)
                if isinstance(payload, dict) and payload.get("success") is False:
                    payload.setdefault("code", "request_failed")
                    response.set_data(current_app.json.dumps(payload))
                    response.mimetype = "application/json"
                    response.status_code = 400
        return response

    @app.errorhandler(413)
    def _payload_too_large(_error):
        if request.path.startswith("/api/"):
            return api_error("Request body is too large", 413, "payload_too_large")
        return "Request body is too large", 413

    @app.errorhandler(404)
    def _not_found(_error):
        if request.path.startswith("/api/"):
            return api_error("API endpoint not found", 404, "not_found")
        return "Not found", 404

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        if request.path.startswith("/api/"):
            return api_error("Method not allowed", 405, "method_not_allowed")
        return "Method not allowed", 405
