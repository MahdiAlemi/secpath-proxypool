from __future__ import annotations

import hmac
import socket
import time
from collections.abc import Callable

from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log
from proxy_server.utils.network import connect_via_upstream


def safe_peer_key(sock: socket.socket) -> str:
    try:
        peer = sock.getpeername()
        return str(peer[0])
    except Exception:
        return "unknown"


def credentials_match(actual_user: str, actual_password: str, expected_user, expected_password) -> bool:
    return hmac.compare_digest(str(actual_user), str(expected_user or "")) and hmac.compare_digest(
        str(actual_password), str(expected_password or "")
    )


def connect_selected_upstream(
    store: ProxyStore,
    client_key: str,
    dest_host: str,
    dest_port: int,
    cid: int,
    *,
    attempts: int = 2,
    connector: Callable | None = None,
):
    connector = connector or connect_via_upstream
    excluded = set()
    last_error = None
    for attempt in range(max(1, attempts)):
        upstream = store.select(force=attempt > 0, client_key=client_key, exclude_ids=excluded)
        if upstream is None:
            break
        excluded.add(upstream.get("id"))
        protocol = str(upstream.get("protocol") or "").lower()
        host = upstream.get("ip")
        port = int(upstream.get("port"))
        username = upstream.get("username") or ""
        password = upstream.get("password") or ""
        log(
            "[CONN#{0}] {1} -> upstream {2} {3}:{4} (cost={5})",
            cid,
            client_key,
            protocol,
            host,
            port,
            upstream.get("cost"),
        )
        started = time.monotonic()
        try:
            sock = connector(
                host,
                port,
                protocol,
                dest_host,
                dest_port,
                timeout=float(getattr(store.args, "timeout", 10)),
                up_user=username,
                up_pass=password,
                insecure_upstream=bool(getattr(store.args, "insecure_upstream", False)),
                upstream_server_name=host,
            )
            store.mark_alive(upstream, speed_ms=max(0, int((time.monotonic() - started) * 1000)))
            return sock, upstream
        except Exception as exc:
            last_error = exc
            store.mark_fail(upstream)
            log("[CONN#{0}] upstream attempt {1} failed: {2}", cid, attempt + 1, exc)
    if last_error:
        raise last_error
    raise ConnectionError("no matching upstream proxy is available")
