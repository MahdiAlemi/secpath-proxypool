import socket
import select
import ssl

from proxy_server.config import BUFFER_SIZE
from proxy_server.utils.logging import log


def forward_bidirectional(a: socket.socket, b: socket.socket):
    sockets = [a, b]
    while True:
        r, _, x = select.select(sockets, [], sockets, 3)
        if x:
            break
        for sock in r:
            try:
                data = sock.recv(BUFFER_SIZE)
                if not data:
                    return
                other = a if sock is b else b
                other.sendall(data)
            except Exception:
                return


def connect_via_upstream(up_ip, up_port, up_proto, dest_host: str, dest_port: int, timeout: int = 10, up_user: str = "", up_pass: str = "") -> socket.socket:
    import socks
    
    log("[UPSTREAM] Connecting to {}://{}:{} -> {}:{}", up_proto, up_ip, up_port, dest_host, dest_port)

    try:
        if up_proto == "socks5":
            s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            s.set_proxy(socks.SOCKS5, up_ip, up_port, username=up_user, password=up_pass)
            s.settimeout(timeout)
            s.connect((dest_host, dest_port))
        elif up_proto == "socks4":
            s = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
            s.set_proxy(socks.SOCKS4, up_ip, up_port, username=up_user)
            s.settimeout(timeout)
            s.connect((dest_host, dest_port))
        elif up_proto in ("http", "https"):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((up_ip, up_port))
            if up_proto == "https" and up_port == 443:
                context = ssl.create_default_context()
                s = context.wrap_socket(s, server_hostname=dest_host)
            host_header = f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\nHost: {dest_host}:{dest_port}\r\n"
            if up_user and up_pass:
                import base64
                creds = base64.b64encode(f"{up_user}:{up_pass}".encode()).decode()
                host_header += f"Proxy-Authorization: Basic {creds}\r\n"
            host_header += "\r\n"
            s.sendall(host_header.encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = s.recv(1024)
                if not chunk:
                    break
                resp += chunk
            if b"200" not in resp.split(b"\r\n")[0]:
                raise Exception(f"Upstream HTTP proxy rejected: {resp[:100]}")
        else:
            raise ValueError(f"Unsupported upstream protocol: {up_proto}")
        
        log("[UPSTREAM] Connected")
        return s

    except Exception as e:
        log("[UPSTREAM] Failed: {}", e)
        raise
