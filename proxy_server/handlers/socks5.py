import socket

from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.network import connect_via_upstream, forward_bidirectional
from proxy_server.utils.logging import log


def handle_socks5_client(client_sock: socket.socket, store: ProxyStore, cid: int):
    client_sock.settimeout(10)
    try:
        hdr = client_sock.recv(2)
        if len(hdr) < 2:
            client_sock.close()
            return
        ver, nmethods = hdr[0], hdr[1]
        if ver != 5:
            client_sock.close()
            return
        methods = client_sock.recv(nmethods)

        args = store.args
        server_requires_auth = (args.username is not None and args.password is not None)
        method = 0xFF
        if server_requires_auth:
            if 0x02 in methods:
                method = 0x02
            else:
                client_sock.sendall(bytes([5, 0xFF]))
                client_sock.close()
                return
        else:
            if 0x00 in methods:
                method = 0x00
            elif 0x02 in methods:
                method = 0x02

        client_sock.sendall(bytes([5, method]))

        if method == 0x02:
            hdr2 = client_sock.recv(2)
            if len(hdr2) < 2:
                client_sock.close()
                return
            ver2, ulen = hdr2[0], hdr2[1]
            uname = client_sock.recv(ulen).decode(errors="ignore")
            plen_b = client_sock.recv(1)
            plen = plen_b[0] if plen_b else 0
            passwd = client_sock.recv(plen).decode(errors="ignore")

            if server_requires_auth:
                if (uname == args.username) and (passwd == args.password):
                    client_sock.sendall(b"\x01\x00")
                else:
                    client_sock.sendall(b"\x01\x01")
                    client_sock.close()
                    return
            else:
                client_sock.sendall(b"\x01\x00")

        req_head = client_sock.recv(4)
        if len(req_head) < 4:
            client_sock.close()
            return
        ver, cmd, rsv, atyp = req_head[0], req_head[1], req_head[2], req_head[3]
        if ver != 5 or cmd != 1:
            client_sock.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            client_sock.close()
            return

        if atyp == 1:
            addr = client_sock.recv(4)
            dest_host = socket.inet_ntoa(addr)
        elif atyp == 3:
            alen_b = client_sock.recv(1)
            alen = alen_b[0]
            domain = client_sock.recv(alen).decode(errors="ignore")
            dest_host = domain
        elif atyp == 4:
            addr = client_sock.recv(16)
            dest_host = socket.inet_ntop(socket.AF_INET6, addr)
        else:
            client_sock.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            client_sock.close()
            return
        port_bytes = client_sock.recv(2)
        dest_port = int.from_bytes(port_bytes, "big")

        up = store.select()
        if up is None:
            client_sock.sendall(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            client_sock.close()
            return

        up_ip, up_port, up_proto = up.get("ip"), up.get("port"), up.get("protocol")
        up_user = up.get("username") or ""
        up_pass = up.get("password") or ""
        log("[CONN#{0}] {1} -> upstream {2} {3}:{4} (cost={5})", cid, client_sock.getpeername()[0], up_proto, up_ip, up_port, up.get("cost"))

        try:
            upstream_sock = connect_via_upstream(up_ip, up_port, up_proto, dest_host, dest_port, timeout=10, up_user=up_user, up_pass=up_pass)
        except Exception as e:
            log("[CONN#{0}] upstream connect failed: {1}", cid, e)
            store.mark_fail(up)
            if store.args.rotate == "better_cost":
                retry = store.select(force=True)
                if retry and retry.get("id") != up.get("id"):
                    try:
                        r_ip = retry.get("ip")
                        r_port = retry.get("port")
                        r_proto = retry.get("protocol")
                        r_user = retry.get("username") or ""
                        r_pass = retry.get("password") or ""
                        upstream_sock = connect_via_upstream(r_ip, r_port, r_proto, dest_host, dest_port, timeout=10, up_user=r_user, up_pass=r_pass)
                        store.mark_alive(retry)
                        up = retry
                        log("[CONN#{0}] retry succeeded -> {1}:{2}", cid, retry.get("ip"), retry.get("port"))
                    except Exception as e2:
                        log("[CONN#{0}] retry failed: {1}", cid, e2)
                        try:
                            client_sock.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                        except:
                            pass
                        client_sock.close()
                        return
                else:
                    try:
                        client_sock.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                    except:
                        pass
                    client_sock.close()
                    return
            else:
                try:
                    client_sock.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                except:
                    pass
                client_sock.close()
                return

        try:
            client_sock.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + (0).to_bytes(2, "big"))
        except Exception:
            upstream_sock.close()
            client_sock.close()
            return

        store.mark_alive(up)
        forward_bidirectional(client_sock, upstream_sock)

    except Exception as e:
        log("[CONN#{0}] socks5 handler error: {1}", cid, e)
        try:
            client_sock.close()
        except:
            pass
