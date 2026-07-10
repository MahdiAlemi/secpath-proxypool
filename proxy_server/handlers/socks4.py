from __future__ import annotations

import hmac
import socket

from proxy_server.handlers.common import connect_selected_upstream, safe_peer_key
from proxy_server.protocol import ProtocolError, recv_cstring, recv_exact
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log
from proxy_server.utils.network import forward_bidirectional


def _reply(sock: socket.socket, granted: bool):
    code = 0x5A if granted else 0x5B
    try:
        sock.sendall(bytes([0x00, code, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
    except OSError:
        pass


def handle_socks4_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    args = store.args
    client_sock.settimeout(float(getattr(args, "timeout", 10)))
    client_key = safe_peer_key(client_sock)
    upstream_sock = None
    try:
        header = recv_exact(client_sock, 8)
        version, command = header[0], header[1]
        if version != 4 or command != 1:
            _reply(client_sock, False)
            return
        dest_port = int.from_bytes(header[2:4], "big")
        if not 1 <= dest_port <= 65535:
            raise ProtocolError("invalid SOCKS4 destination port")
        dest_ip = header[4:8]
        user_id = recv_cstring(client_sock, 255).decode("utf-8", errors="replace")

        expected_user = getattr(args, "username", None)
        if expected_user and not hmac.compare_digest(user_id, str(expected_user)):
            log("[CONN#{0}] SOCKS4 authentication failed", cid)
            _reply(client_sock, False)
            return

        # SOCKS4a: 0.0.0.x followed by a zero-terminated domain name.
        if dest_ip[:3] == b"\x00\x00\x00" and dest_ip[3] != 0:
            dest_host = recv_cstring(client_sock, 253).decode("idna")
            if not dest_host:
                raise ProtocolError("empty SOCKS4a destination")
        else:
            dest_host = socket.inet_ntoa(dest_ip)

        try:
            upstream_sock, _ = connect_selected_upstream(store, client_key, dest_host, dest_port, cid)
        except Exception:
            _reply(client_sock, False)
            return

        _reply(client_sock, True)
        forward_bidirectional(client_sock, upstream_sock)
        upstream_sock = None
    except ProtocolError as exc:
        log("[CONN#{0}] invalid SOCKS4 request: {1}", cid, exc)
        _reply(client_sock, False)
    except Exception as exc:
        log("[CONN#{0}] SOCKS4 handler error: {1}", cid, exc)
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
