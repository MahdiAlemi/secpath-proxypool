import socket

from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.network import connect_via_upstream, forward_bidirectional
from proxy_server.utils.logging import log


def handle_socks4_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    client_sock.settimeout(10)
    try:
        header = client_sock.recv(8)
        if len(header) < 8:
            client_sock.close()
            return
        vn = header[0]
        cd = header[1]
        dstport = int.from_bytes(header[2:4], "big")
        dstip = header[4:8]
        
        userid = b""
        while True:
            b1 = client_sock.recv(1)
            if not b1:
                client_sock.close()
                return
            if b1 == b"\x00":
                break
            userid += b1
        
        userid_str = userid.decode(errors="ignore")
        
        args = store.args
        if args.username is not None and args.password is not None:
            if userid_str != args.username:
                log("[CONN#{0}] socks4 auth failed: invalid username", cid)
                try:
                    client_sock.sendall(b"\x00\x5B\x00\x00\x00\x00\x00\x00")
                except:
                    pass
                client_sock.close()
                return
        
        dest_host = socket.inet_ntoa(dstip)
        dest_port = dstport
        
        if dstip[0:3] == b"\x00\x00\x00" and dstip[3] != 0:
            dom = b""
            while True:
                b1 = client_sock.recv(1)
                if not b1:
                    client_sock.close()
                    return
                if b1 == b"\x00":
                    break
                dom += b1
            try:
                dest_host = dom.decode(errors="ignore")
            except Exception:
                dest_host = dom.decode(errors="ignore")

        up = store.select()
        if up is None:
            try:
                client_sock.sendall(b"\x00\x5B\x00\x00\x00\x00\x00\x00")
            except:
                pass
            client_sock.close()
            return

        up_ip, up_port, up_proto = up.get("ip"), up.get("port"), up.get("protocol")
        log("[CONN#{0}] {1} -> upstream {2} {3}:{4} (cost={5})", cid, client_sock.getpeername()[0], up_proto, up_ip, up_port, up.get("cost"))

        try:
            upstream_sock = connect_via_upstream(up_ip, up_port, up_proto, dest_host, dest_port, timeout=10)
        except Exception as e:
            log("[CONN#{0}] socks4 upstream failed: {1}", cid, e)
            store.mark_fail(up)
            try:
                client_sock.sendall(b"\x00\x5B\x00\x00\x00\x00\x00\x00")
            except:
                pass
            client_sock.close()
            return

        try:
            client_sock.sendall(b"\x00\x5A" + (0).to_bytes(2, "big") + socket.inet_aton("0.0.0.0"))
        except Exception:
            upstream_sock.close()
            client_sock.close()
            return

        store.mark_alive(up)
        forward_bidirectional(client_sock, upstream_sock)

    except Exception as e:
        log("[CONN#{0}] socks4 handler error: {1}", cid, e)
        try:
            client_sock.close()
        except:
            pass
