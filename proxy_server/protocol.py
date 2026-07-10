from __future__ import annotations

import ipaddress
import socket
from typing import Tuple


class ProtocolError(ValueError):
    """Raised when a client or upstream sends an invalid proxy protocol frame."""


def recv_exact(sock: socket.socket, size: int) -> bytes:
    if size < 0:
        raise ProtocolError("negative receive size")
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ProtocolError("connection closed before frame completed")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_until(sock: socket.socket, marker: bytes, limit: int) -> Tuple[bytes, bytes]:
    if not marker or limit <= 0:
        raise ProtocolError("invalid receive boundary")
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(min(4096, limit - len(data)))
        if not chunk:
            raise ProtocolError("connection closed before headers completed")
        data.extend(chunk)
        if len(data) >= limit and marker not in data:
            raise ProtocolError("frame exceeds configured limit")
    head, tail = bytes(data).split(marker, 1)
    return head, tail


def recv_cstring(sock: socket.socket, limit: int = 255) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        value = recv_exact(sock, 1)
        if value == b"\x00":
            return bytes(data)
        data.extend(value)
    raise ProtocolError("zero-terminated field exceeds configured limit")


def parse_authority(value: str, default_port: int | None = None) -> tuple[str, int]:
    raw = (value or "").strip()
    if not raw:
        raise ProtocolError("destination is empty")

    host: str
    port_value: str | int | None
    if raw.startswith("["):
        closing = raw.find("]")
        if closing < 0:
            raise ProtocolError("invalid bracketed IPv6 destination")
        host = raw[1:closing]
        remainder = raw[closing + 1 :]
        if remainder:
            if not remainder.startswith(":"):
                raise ProtocolError("invalid bracketed destination")
            port_value = remainder[1:]
        else:
            port_value = default_port
    elif raw.count(":") == 1:
        host, port_value = raw.rsplit(":", 1)
    elif ":" in raw:
        # Unbracketed IPv6 is accepted only when a default port is available.
        try:
            ipaddress.IPv6Address(raw)
        except ValueError as exc:
            raise ProtocolError("IPv6 destinations with a port must be bracketed") from exc
        host, port_value = raw, default_port
    else:
        host, port_value = raw, default_port

    host = host.strip()
    if not host or len(host) > 253 or any(ord(char) < 33 for char in host):
        raise ProtocolError("invalid destination host")
    try:
        port = int(port_value) if port_value is not None else 0
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid destination port") from exc
    if not 1 <= port <= 65535:
        raise ProtocolError("destination port must be between 1 and 65535")
    return host, port


def socks5_bound_address(sock: socket.socket) -> bytes:
    try:
        host, port = sock.getsockname()[:2]
        parsed = ipaddress.ip_address(host)
        if parsed.version == 6:
            return b"\x04" + parsed.packed + int(port).to_bytes(2, "big")
        return b"\x01" + parsed.packed + int(port).to_bytes(2, "big")
    except Exception:
        return b"\x01\x00\x00\x00\x00\x00\x00"
