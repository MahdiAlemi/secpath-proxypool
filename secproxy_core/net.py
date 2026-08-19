from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse


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
    """Validate an HTTP(S) URL and resolve it only to public addresses."""
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
    return resolve_public_http_url(url)[0]


def validate_public_peer(peer_ip: str, allowed_ips: Iterable[str]) -> None:
    try:
        normalized = str(ipaddress.ip_address(str(peer_ip).split("%", 1)[0]))
    except ValueError as exc:
        raise ValueError("Source connection peer is invalid") from exc
    if _is_forbidden_ip(normalized):
        raise ValueError("Source connection reached a blocked network address")
    allowed = {str(ipaddress.ip_address(item)) for item in allowed_ips}
    if normalized not in allowed:
        raise ValueError("Source connection did not match validated DNS results")
