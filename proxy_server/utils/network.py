from __future__ import annotations

import base64
import select
import socket
import ssl
from dataclasses import dataclass

from proxy_server.config import BUFFER_SIZE
from proxy_server.protocol import ProtocolError, recv_until
from proxy_server.utils.logging import log


@dataclass(frozen=True)
class UpstreamEndpoint:
    host: str
    port: int
    protocol: str
    username: str = ""
    password: str = ""


def _tls_context(insecure: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def open_upstream_proxy(
    host: str,
    port: int,
    protocol: str,
    *,
    timeout: float = 10,
    insecure_upstream: bool = False,
    server_hostname: str | None = None,
) -> socket.socket:
    protocol = (protocol or "").lower()
    sock = socket.create_connection((host, int(port)), timeout=timeout)
    sock.settimeout(timeout)
    if protocol == "https":
        # SNI belongs to the HTTPS proxy itself, never to the final destination.
        sni = server_hostname or host
        try:
            sock = _tls_context(insecure_upstream).wrap_socket(sock, server_hostname=sni)
            sock.settimeout(timeout)
        except Exception:
            sock.close()
            raise
    return sock


def _http_connect_request(dest_host: str, dest_port: int, username: str, password: str) -> bytes:
    authority = f"[{dest_host}]:{dest_port}" if ":" in dest_host else f"{dest_host}:{dest_port}"
    lines = [
        f"CONNECT {authority} HTTP/1.1",
        f"Host: {authority}",
        "Proxy-Connection: Keep-Alive",
    ]
    if username or password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {token}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def connect_via_upstream(
    up_ip,
    up_port,
    up_proto,
    dest_host: str,
    dest_port: int,
    timeout: int = 10,
    up_user: str = "",
    up_pass: str = "",
    *,
    insecure_upstream: bool = False,
    upstream_server_name: str | None = None,
) -> socket.socket:
    import socks

    protocol = (up_proto or "").lower()
    log("[UPSTREAM] Connecting to {}://{}:{} -> {}:{}", protocol, up_ip, up_port, dest_host, dest_port)

    try:
        if protocol == "socks5":
            sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            sock.set_proxy(
                socks.SOCKS5,
                up_ip,
                int(up_port),
                rdns=True,
                username=up_user or None,
                password=up_pass or None,
            )
            sock.settimeout(timeout)
            sock.connect((dest_host, int(dest_port)))
        elif protocol == "socks4":
            sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            sock.set_proxy(
                socks.SOCKS4,
                up_ip,
                int(up_port),
                rdns=True,
                username=up_user or None,
            )
            sock.settimeout(timeout)
            sock.connect((dest_host, int(dest_port)))
        elif protocol in ("http", "https"):
            sock = open_upstream_proxy(
                up_ip,
                int(up_port),
                protocol,
                timeout=timeout,
                insecure_upstream=insecure_upstream,
                server_hostname=upstream_server_name or up_ip,
            )
            try:
                sock.sendall(_http_connect_request(dest_host, int(dest_port), up_user, up_pass))
                header, _ = recv_until(sock, b"\r\n\r\n", 64 * 1024)
                status_line = header.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
                parts = status_line.split(None, 2)
                if len(parts) < 2 or not parts[1].isdigit() or not 200 <= int(parts[1]) < 300:
                    raise ProtocolError(f"upstream HTTP proxy rejected CONNECT: {status_line[:200]}")
            except Exception:
                sock.close()
                raise
        else:
            raise ValueError(f"Unsupported upstream protocol: {protocol}")

        log("[UPSTREAM] Connected")
        return sock
    except Exception as exc:
        log("[UPSTREAM] Failed: {}", exc)
        raise


def forward_bidirectional(a: socket.socket, b: socket.socket, idle_timeout: float = 300.0):
    sockets = [a, b]
    try:
        for sock in sockets:
            sock.setblocking(False)
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, idle_timeout)
            if exceptional or not readable:
                return
            for sock in readable:
                try:
                    data = sock.recv(BUFFER_SIZE)
                except (BlockingIOError, InterruptedError):
                    continue
                if not data:
                    return
                other = b if sock is a else a
                view = memoryview(data)
                while view:
                    try:
                        sent = other.send(view)
                    except (BlockingIOError, InterruptedError):
                        select.select([], [other], [], 1)
                        continue
                    if sent <= 0:
                        return
                    view = view[sent:]
    finally:
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
