from __future__ import annotations

import hmac
import ipaddress
import socket

from proxy_server.handlers.common import connect_selected_upstream, safe_peer_key
from proxy_server.protocol import ProtocolError, recv_exact, socks5_bound_address
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log
from proxy_server.utils.network import forward_bidirectional


def _reply(sock: socket.socket, code: int, bound: bytes | None = None):
    try:
        sock.sendall(bytes([0x05, code, 0x00]) + (bound or b"\x01\x00\x00\x00\x00\x00\x00"))
    except OSError:
        pass


def _read_destination(sock: socket.socket, address_type: int):
    if address_type == 0x01:
        host = str(ipaddress.IPv4Address(recv_exact(sock, 4)))
    elif address_type == 0x03:
        length = recv_exact(sock, 1)[0]
        if length == 0:
            raise ProtocolError("empty SOCKS5 domain")
        host = recv_exact(sock, length).decode("idna")
    elif address_type == 0x04:
        host = str(ipaddress.IPv6Address(recv_exact(sock, 16)))
    else:
        raise ProtocolError("unsupported SOCKS5 address type")
    port = int.from_bytes(recv_exact(sock, 2), "big")
    if not 1 <= port <= 65535:
        raise ProtocolError("invalid SOCKS5 destination port")
    return host, port


def handle_socks5_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    args = store.args
    client_sock.settimeout(float(getattr(args, "timeout", 10)))
    client_key = safe_peer_key(client_sock)
    upstream_sock = None
    try:
        version, method_count = recv_exact(client_sock, 2)
        if version != 5 or method_count == 0:
            raise ProtocolError("invalid SOCKS5 greeting")
        methods = set(recv_exact(client_sock, method_count))
        requires_auth = bool(getattr(args, "username", None) or getattr(args, "password", None))
        selected = 0x02 if requires_auth and 0x02 in methods else 0x00 if not requires_auth and 0x00 in methods else 0xFF
        client_sock.sendall(bytes([0x05, selected]))
        if selected == 0xFF:
            return

        if selected == 0x02:
            auth_version, username_length = recv_exact(client_sock, 2)
            if auth_version != 1:
                client_sock.sendall(b"\x01\x01")
                return
            username = recv_exact(client_sock, username_length).decode("utf-8", errors="replace")
            password_length = recv_exact(client_sock, 1)[0]
            password = recv_exact(client_sock, password_length).decode("utf-8", errors="replace")
            valid = hmac.compare_digest(username, str(getattr(args, "username", "") or "")) and hmac.compare_digest(
                password, str(getattr(args, "password", "") or "")
            )
            client_sock.sendall(b"\x01\x00" if valid else b"\x01\x01")
            if not valid:
                return

        version, command, reserved, address_type = recv_exact(client_sock, 4)
        if version != 5 or reserved != 0:
            raise ProtocolError("invalid SOCKS5 request")
        if command != 1:
            _reply(client_sock, 0x07)
            return
        try:
            dest_host, dest_port = _read_destination(client_sock, address_type)
        except ProtocolError:
            _reply(client_sock, 0x08)
            return

        try:
            upstream_sock, _ = connect_selected_upstream(store, client_key, dest_host, dest_port, cid)
        except OSError as exc:
            code = 0x05 if getattr(exc, "errno", None) in {111, 61, 10061} else 0x04
            _reply(client_sock, code)
            return
        except Exception:
            _reply(client_sock, 0x04)
            return

        _reply(client_sock, 0x00, socks5_bound_address(upstream_sock))
        forward_bidirectional(client_sock, upstream_sock)
        upstream_sock = None
    except ProtocolError as exc:
        log("[CONN#{0}] invalid SOCKS5 request: {1}", cid, exc)
    except Exception as exc:
        log("[CONN#{0}] SOCKS5 handler error: {1}", cid, exc)
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
