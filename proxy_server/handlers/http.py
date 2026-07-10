from __future__ import annotations

import base64
import hmac
import socket
from urllib.parse import urlsplit

from proxy_server.handlers.common import connect_selected_upstream, safe_peer_key
from proxy_server.protocol import ProtocolError, parse_authority, recv_until
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log
from proxy_server.utils.network import forward_bidirectional, open_upstream_proxy


_HOP_BY_HOP = {
    "proxy-authorization",
    "proxy-authenticate",
    "proxy-connection",
    "connection",
    "keep-alive",
    "te",
    "upgrade",
}


def _parse_headers(header_bytes: bytes):
    text = header_bytes.decode("iso-8859-1", errors="strict")
    lines = text.split("\r\n")
    if not lines or not lines[0]:
        raise ProtocolError("empty HTTP request")
    request_parts = lines[0].split(None, 2)
    if len(request_parts) != 3 or request_parts[2] not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ProtocolError("invalid HTTP request line")
    headers = []
    lookup = {}
    for line in lines[1:]:
        if not line:
            continue
        if line[:1] in {" ", "\t"} or ":" not in line:
            raise ProtocolError("invalid HTTP header")
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or any(ord(char) <= 32 or ord(char) >= 127 for char in name):
            raise ProtocolError("invalid HTTP header name")
        headers.append((name, value))
        lookup[name.lower()] = value
    return request_parts, headers, lookup


def _send_response(sock, status: int, reason: str, extra_headers=None):
    lines = [f"HTTP/1.1 {status} {reason}", "Content-Length: 0", "Connection: close"]
    for name, value in extra_headers or []:
        lines.append(f"{name}: {value}")
    try:
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    except OSError:
        pass


def _check_listener_auth(headers: dict, args) -> bool:
    expected_user = getattr(args, "username", None)
    expected_password = getattr(args, "password", None)
    if not expected_user and not expected_password:
        return True
    auth = headers.get("proxy-authorization")
    if not auth:
        return False
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeError):
        return False
    return hmac.compare_digest(username, str(expected_user or "")) and hmac.compare_digest(
        password, str(expected_password or "")
    )


def _clean_headers(headers, *, upstream_authorization=None):
    connection_tokens = set()
    for name, value in headers:
        if name.lower() == "connection":
            connection_tokens.update(token.strip().lower() for token in value.split(","))
    result = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP or lowered in connection_tokens:
            continue
        result.append((name, value))
    if upstream_authorization:
        result.append(("Proxy-Authorization", upstream_authorization))
    result.append(("Connection", "close"))
    return result


def _serialize_request(method, target, version, headers, body):
    lines = [f"{method} {target} {version}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + body


def _destination(method, target, headers):
    if method == "CONNECT":
        host, port = parse_authority(target)
        return host, port, target, True

    parsed = urlsplit(target)
    if parsed.scheme:
        if parsed.scheme.lower() != "http":
            raise ProtocolError("HTTPS requests must use CONNECT")
        if not parsed.hostname:
            raise ProtocolError("absolute HTTP target has no host")
        host = parsed.hostname
        port = parsed.port or 80
        origin_target = parsed.path or "/"
        if parsed.query:
            origin_target += "?" + parsed.query
        return host, port, origin_target, False

    host_header = headers.get("host")
    if not host_header:
        raise ProtocolError("Host header is required")
    host, port = parse_authority(host_header, default_port=80)
    return host, port, target or "/", False


def _upstream_proxy_auth(upstream):
    username = upstream.get("username") or ""
    password = upstream.get("password") or ""
    if not username and not password:
        return None
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def handle_http_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    args = store.args
    client_sock.settimeout(float(getattr(args, "timeout", 10)))
    client_key = safe_peer_key(client_sock)
    upstream_sock = None
    try:
        header_bytes, body = recv_until(client_sock, b"\r\n\r\n", int(getattr(args, "header_limit", 65536)))
        (method, target, version), headers, lookup = _parse_headers(header_bytes)
        method = method.upper()

        if not _check_listener_auth(lookup, args):
            _send_response(
                client_sock,
                407,
                "Proxy Authentication Required",
                [("Proxy-Authenticate", 'Basic realm="SecPath ProxyPool"')],
            )
            return

        dest_host, dest_port, origin_target, is_connect = _destination(method, target, lookup)
        if is_connect:
            try:
                upstream_sock, _ = connect_selected_upstream(store, client_key, dest_host, dest_port, cid)
            except Exception:
                _send_response(client_sock, 502, "Bad Gateway")
                return
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if body:
                upstream_sock.sendall(body)
            forward_bidirectional(client_sock, upstream_sock)
            upstream_sock = None
            return

        # Normal HTTP requests either traverse a SOCKS tunnel to the destination
        # or are forwarded in absolute-form to an HTTP(S) upstream proxy.
        upstream = store.select(client_key=client_key)
        if upstream is None:
            _send_response(client_sock, 503, "Service Unavailable")
            return
        up_protocol = str(upstream.get("protocol") or "").lower()

        if up_protocol in {"socks4", "socks5"}:
            try:
                upstream_sock, _ = connect_selected_upstream(store, client_key, dest_host, dest_port, cid)
            except Exception:
                _send_response(client_sock, 502, "Bad Gateway")
                return
            clean = _clean_headers(headers)
            upstream_sock.sendall(_serialize_request(method, origin_target, version, clean, body))
        elif up_protocol in {"http", "https"}:
            try:
                upstream_sock = open_upstream_proxy(
                    upstream.get("ip"),
                    int(upstream.get("port")),
                    up_protocol,
                    timeout=float(getattr(args, "timeout", 10)),
                    insecure_upstream=bool(getattr(args, "insecure_upstream", False)),
                    server_hostname=upstream.get("ip"),
                )
                if target.startswith("http://"):
                    absolute_target = target
                else:
                    authority = f"[{dest_host}]" if ":" in dest_host else dest_host
                    if dest_port != 80:
                        authority += f":{dest_port}"
                    absolute_target = f"http://{authority}{origin_target}"
                clean = _clean_headers(headers, upstream_authorization=_upstream_proxy_auth(upstream))
                upstream_sock.sendall(_serialize_request(method, absolute_target, version, clean, body))
                store.mark_alive(upstream)
            except Exception as exc:
                log("[CONN#{0}] HTTP upstream request failed: {1}", cid, exc)
                store.mark_fail(upstream)
                _send_response(client_sock, 502, "Bad Gateway")
                return
        else:
            _send_response(client_sock, 502, "Bad Gateway")
            return

        forward_bidirectional(client_sock, upstream_sock)
        upstream_sock = None
    except ProtocolError as exc:
        log("[CONN#{0}] invalid HTTP request: {1}", cid, exc)
        _send_response(client_sock, 400, "Bad Request")
    except Exception as exc:
        log("[CONN#{0}] HTTP handler error: {1}", cid, exc)
    finally:
        if upstream_sock is not None:
            try:
                upstream_sock.close()
            except OSError:
                pass
        try:
            client_sock.close()
        except OSError:
            pass
