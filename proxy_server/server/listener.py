import socket
import ssl
import threading

from proxy_server.handlers import handle_socks5_client, handle_socks4_client, handle_http_client
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.logging import log


_conn_id = 0
_conn_lock = threading.Lock()


def next_conn_id():
    global _conn_id
    with _conn_lock:
        _conn_id += 1
        return _conn_id


def handle_client(client_sock: socket.socket, addr, store: ProxyStore):
    cid = next_conn_id()
    log("[CONN#{0}] accepted from {1}", cid, addr[0])
    protocol = store.args.protocol
    try:
        if protocol == "socks5":
            handle_socks5_client(client_sock, store, cid)
        elif protocol == "socks4":
            handle_socks4_client(client_sock, store, cid)
        elif protocol in ("http", "https"):
            handle_http_client(client_sock, store, cid)
        else:
            log("[CONN#{0}] Unsupported listening protocol: {1}", cid, protocol)
            try:
                client_sock.close()
            except:
                pass
    except Exception as e:
        log("[CONN#{0}] error in handle_client wrapper: {1}", cid, e)
        try:
            client_sock.close()
        except:
            pass


def start_listener(bind_addr: str, port: int, store: ProxyStore):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((bind_addr, port))
    s.listen(256)
    log("[+] Listening on {0}:{1} as {2}", bind_addr, port, store.args.protocol)

    args = store.args
    if args.certfile and args.keyfile:
        log("[+] TLS enabled")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.certfile, args.keyfile)
        s = ctx.wrap_socket(s, server_side=True)

    while True:
        try:
            client_sock, addr = s.accept()
            thread = threading.Thread(target=handle_client, args=(client_sock, addr, store), daemon=True)
            thread.start()
        except KeyboardInterrupt:
            log("[!] Shutting down")
            break
        except Exception as e:
            log("[!] Accept error: {0}", e)
