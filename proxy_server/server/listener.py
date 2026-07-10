from __future__ import annotations

import contextlib
import signal
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor

from proxy_server.handlers import handle_http_client, handle_socks4_client, handle_socks5_client
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log


class ProxyListener:
    def __init__(self, bind_addr: str, port: int, store: ProxyStore):
        self.bind_addr = bind_addr
        self.port = int(port)
        self.store = store
        self.stop_event = threading.Event()
        self.listener = None
        self.executor = ThreadPoolExecutor(max_workers=int(store.args.threads), thread_name_prefix="proxy-client")
        self.capacity = threading.BoundedSemaphore(max(1, int(store.args.threads) * 2))
        self._conn_id = 0
        self._conn_lock = threading.Lock()
        self._tls_context = None
        if store.args.certfile and store.args.keyfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(store.args.certfile, store.args.keyfile)
            self._tls_context = context

    def next_conn_id(self):
        with self._conn_lock:
            self._conn_id += 1
            return self._conn_id

    def _create_socket(self):
        infos = socket.getaddrinfo(self.bind_addr, self.port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
        last_error = None
        for family, socktype, protocol, _, sockaddr in infos:
            candidate = socket.socket(family, socktype, protocol)
            try:
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    with contextlib.suppress(OSError):
                        candidate.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                candidate.bind(sockaddr)
                candidate.listen(256)
                candidate.settimeout(1.0)
                return candidate
            except OSError as exc:
                last_error = exc
                candidate.close()
        raise last_error or OSError("could not bind listener")

    def _dispatch(self, client_sock, address):
        cid = self.next_conn_id()
        try:
            if self._tls_context is not None:
                client_sock = self._tls_context.wrap_socket(client_sock, server_side=True)
            log("[CONN#{0}] accepted from {1}", cid, address[0])
            protocol = self.store.args.protocol
            if protocol == "socks5":
                handle_socks5_client(client_sock, self.store, cid)
            elif protocol == "socks4":
                handle_socks4_client(client_sock, self.store, cid)
            elif protocol in {"http", "https"}:
                handle_http_client(client_sock, self.store, cid)
            else:
                client_sock.close()
        except ssl.SSLError as exc:
            log("[CONN#{0}] TLS handshake failed: {1}", cid, exc)
            with contextlib.suppress(OSError):
                client_sock.close()
        except Exception as exc:
            log("[CONN#{0}] client handler failed: {1}", cid, exc)
            with contextlib.suppress(OSError):
                client_sock.close()
        finally:
            self.capacity.release()

    def shutdown(self, *_):
        self.stop_event.set()
        if self.listener is not None:
            with contextlib.suppress(OSError):
                self.listener.close()

    def serve_forever(self):
        self.listener = self._create_socket()
        log("[+] Listening on {0}:{1} as {2}", self.bind_addr, self.port, self.store.args.protocol)
        if self._tls_context:
            log("[+] Listener TLS enabled")
        while not self.stop_event.is_set():
            try:
                client_sock, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stop_event.is_set():
                    break
                raise
            if not self.capacity.acquire(blocking=False):
                log("[!] Connection rejected: worker capacity reached")
                with contextlib.suppress(OSError):
                    client_sock.close()
                continue
            self.executor.submit(self._dispatch, client_sock, address)
        self.executor.shutdown(wait=True, cancel_futures=True)


def start_listener(bind_addr: str, port: int, store: ProxyStore):
    listener = ProxyListener(bind_addr, port, store)
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError):
            signal.signal(signum, listener.shutdown)
    listener.serve_forever()
