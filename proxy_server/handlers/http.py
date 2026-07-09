import base64
import socket
import ssl
from urllib.parse import urlsplit

from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.network import connect_via_upstream, forward_bidirectional
from proxy_server.utils.logging import log


def _parse_http_headers(hdr_text: str):
    headers = {}
    for line in hdr_text.splitlines()[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return headers


def _check_http_proxy_auth(headers: dict, args):
    if args.username is None or args.password is None:
        return True
    auth = headers.get("proxy-authorization")
    if not auth:
        return False
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return False
    scheme, token = parts
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(token).decode(errors="ignore")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    u, p = decoded.split(":", 1)
    return (u == args.username and p == args.password)


def handle_http_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    client_sock.settimeout(10)
    args = store.args
    try:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = client_sock.recv(4096)
            if not chunk:
                client_sock.close()
                return
            data += chunk
            if len(data) > 64 * 1024:
                break

        header = data.split(b"\r\n\r\n", 1)[0].decode(errors="ignore")
        lines = header.splitlines()
        first = lines[0] if lines else ""
        parts = first.split()
        if len(parts) < 2:
            client_sock.close()
            return
        method = parts[0].upper()
        target = parts[1]
        headers = _parse_http_headers(header)

        if not _check_http_proxy_auth(headers, args):
            resp = "HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm=\"proxy\"\r\nContent-Length:0\r\n\r\n"
            try:
                client_sock.sendall(resp.encode())
            except:
                pass
            client_sock.close()
            return

        up = store.select()
        if up is None:
            client_sock.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length:0\r\n\r\n")
            client_sock.close()
            return

        up_ip = up.get("ip")
        up_port = int(up.get("port"))
        up_proto = (up.get("protocol") or "").lower()
        up_user = up.get("username") or None
        up_pass = up.get("password") or None

        try:
            peer = client_sock.getpeername()[0]
        except Exception:
            peer = "?"
        log("[CONN#{0}] {1} -> upstream {2} {3}:{4} (cost={5})", cid, peer, up_proto, up_ip, up_port, up.get("cost"))

        if method == "CONNECT":
            if ":" in target:
                dest_host, dest_port_s = target.split(":", 1)
                dest_port = int(dest_port_s)
            else:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length:0\r\n\r\n")
                client_sock.close()
                return

            try:
                upstream_sock = connect_via_upstream(up_ip, up_port, up_proto, dest_host, dest_port, timeout=10, up_user=up_user, up_pass=up_pass)
            except Exception as e:
                log("[CONN#{0}] http upstream (CONNECT) failed: {1}", cid, e)
                store.mark_fail(up)
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length:0\r\n\r\n")
                client_sock.close()
                return

            try:
                client_sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            except Exception:
                upstream_sock.close()
                client_sock.close()
                return

            store.mark_alive(up)
            forward_bidirectional(client_sock, upstream_sock)
            return

        dest_host = None
        dest_port = 80
        path = target
        if target.startswith("http://") or target.startswith("https://"):
            parsed = urlsplit(target)
            dest_host = parsed.hostname
            dest_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
        else:
            host_hdr = headers.get("host")
            if host_hdr:
                if ":" in host_hdr:
                    h, p = host_hdr.split(":", 1)
                    dest_host = h
                    try:
                        dest_port = int(p)
                    except Exception:
                        dest_port = 80
                else:
                    dest_host = host_hdr
            else:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length:0\r\n\r\n")
                client_sock.close()
                return

        if up_proto in ("socks4", "socks5"):
            try:
                upstream_sock = connect_via_upstream(up_ip, up_port, up_proto, dest_host, dest_port, timeout=10, up_user=up_user, up_pass=up_pass)
            except Exception as e:
                log("[CONN#{0}] upstream (socks -> dest) failed: {1}", cid, e)
                store.mark_fail(up)
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length:0\r\n\r\n")
                client_sock.close()
                return

            try:
                rest = header.splitlines()[1:]
                req_bytes = (f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(rest) + "\r\n\r\n").encode()
                body = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
                upstream_sock.sendall(req_bytes + body)
            except Exception as e:
                upstream_sock.close()
                client_sock.close()
                log("[CONN#{0}] send to upstream failed: {1}", cid, e)
                return

            store.mark_alive(up)
            forward_bidirectional(client_sock, upstream_sock)
            return

        if up_proto in ("http", "https", ""):
            try:
                upstream_sock = socket.create_connection((up_ip, up_port), timeout=10)
                upstream_sock.settimeout(10)
                if up_proto == "https":
                    if getattr(args, "insecure_upstream", False):
                        ctx = ssl.create_default_context()
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl.CERT_NONE
                    else:
                        ctx = ssl.create_default_context()
                    upstream_sock = ctx.wrap_socket(upstream_sock, server_hostname=up_ip)
                    upstream_sock.settimeout(10)
            except Exception as e:
                log("[CONN#{0}] upstream connect failed: {1}", cid, e)
                store.mark_fail(up)
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length:0\r\n\r\n")
                client_sock.close()
                return

            proxy_auth_hdr = b""
            if up_user and up_pass:
                token = base64.b64encode(f"{up_user}:{up_pass}".encode()).decode()
                proxy_auth_hdr = f"Proxy-Authorization: Basic {token}\r\n".encode()

            if not (target.startswith("http://") or target.startswith("https://")):
                scheme = "http"
                absolute = f"{scheme}://{dest_host}"
                if dest_port not in (80, 443):
                    absolute += f":{dest_port}"
                absolute += path
                first_line = f"{method} {absolute} HTTP/1.1\r\n"
            else:
                first_line = f"{method} {target} HTTP/1.1\r\n"

            rest_lines = header.splitlines()[1:]
            cleaned = []
            for ln in rest_lines:
                if ln.lower().startswith("proxy-authorization:"):
                    continue
                cleaned.append(ln)
            header_bytes = (first_line + "\r\n".join(cleaned) + "\r\n").encode()
            header_bytes = header_bytes + proxy_auth_hdr + b"\r\n"

            body = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
            to_send = header_bytes + body

            try:
                upstream_sock.sendall(to_send)
            except Exception as e:
                upstream_sock.close()
                client_sock.close()
                log("[CONN#{0}] send to upstream failed: {1}", cid, e)
                return

            store.mark_alive(up)
            forward_bidirectional(client_sock, upstream_sock)
            return

        client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length:0\r\n\r\n")
        client_sock.close()
        return

    except Exception as e:
        log("[CONN#{0}] http handler error: {1}", cid, e)
        try:
            client_sock.close()
        except:
            pass
