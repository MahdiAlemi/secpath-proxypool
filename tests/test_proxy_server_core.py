from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dashboard import create_app
from dashboard.routes.server import _normalize_server_config
from proxy_server.config import parse_args
from proxy_server.handlers.socks5 import handle_socks5_client
from proxy_server.lifecycle import claim, process_matches, reserve_start, snapshot, terminate
from proxy_server.server.listener import ProxyListener
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.network import connect_via_upstream


def server_args(**overrides):
    values = {
        "protocol": "http",
        "bind": "127.0.0.1",
        "listen_port": 8080,
        "threads": 10,
        "timeout": 2,
        "header_limit": 65536,
        "w_latency": 0.4,
        "w_fail": 0.4,
        "rotate": "better_cost",
        "rotate_interval": 60,
        "min_cost": 0.0,
        "cost_threshold": None,
        "auth_required": None,
        "username": None,
        "password": None,
        "certfile": None,
        "keyfile": None,
        "insecure_upstream": False,
        "allow_public_no_auth": False,
        "sticky_upstream": None,
        "upstream_protocol": None,
        "candidate_statuses": "alive",
        "require_web_https": False,
        "require_remote_dns": False,
        "require_telegram": False,
        "countryCodes": None,
        "regions": None,
        "cities": None,
        "orgs": None,
        "isp": None,
        "asn": None,
        "continentCode": None,
        "zip_codes": None,
        "timezones": None,
        "mobile": None,
        "proxy": None,
        "hosting": None,
        "readonly": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, value):
        self.sent.append(value)

    def recv(self, _size):
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.closed = True


class RoutingStore:
    def __init__(self, args, upstream):
        self.args = args
        self.upstream = upstream
        self.alive = 0
        self.failed = 0

    def select(self, *args, **kwargs):
        return self.upstream

    def mark_alive(self, *_args, **_kwargs):
        self.alive += 1

    def mark_fail(self, *_args, **_kwargs):
        self.failed += 1


class LocalProxyHandler(socketserver.BaseRequestHandler):
    requests = []

    def handle(self):
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data.extend(chunk)
        header, remainder = bytes(data).split(b"\r\n\r\n", 1)
        type(self).requests.append(header)
        first = header.split(b"\r\n", 1)[0].decode("ascii")
        method, target, _ = first.split(None, 2)
        if method == "CONNECT":
            host, port = target.rsplit(":", 1)
            remote = socket.create_connection((host.strip("[]"), int(port)), timeout=2)
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if remainder:
                remote.sendall(remainder)
            try:
                payload = self.request.recv(4096)
                if payload:
                    remote.sendall(payload)
                    echoed = remote.recv(4096)
                    self.request.sendall(echoed)
            finally:
                remote.close()
            return
        body = b"proxypool-http-integration"
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        payload = self.request.recv(4096)
        if payload:
            self.request.sendall(payload)


def start_tcp_server(handler):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def start_listener(store):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    listener = ProxyListener("127.0.0.1", port, store)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    return listener, thread, port


class ProxyServerCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def test_public_listener_requires_auth_or_explicit_override(self):
        with self.assertRaisesRegex(ValueError, "beyond loopback"):
            _normalize_server_config({"protocol": "http", "bind": "0.0.0.0", "port": 8080})

        allowed = _normalize_server_config(
            {
                "protocol": "http",
                "bind": "192.168.1.10",
                "port": 8080,
                "allow_public_no_auth": True,
            }
        )
        self.assertTrue(allowed["allow_public_no_auth"])

        authenticated = _normalize_server_config(
            {
                "protocol": "socks5",
                "bind": "0.0.0.0",
                "port": 1080,
                "username": "listener",
                "password": "secret",
            }
        )
        self.assertEqual(authenticated["username"], "listener")

    def test_config_file_boolean_false_stays_false(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "protocol": "http",
                    "bind": "127.0.0.1",
                    "port": 8080,
                    "mobile": "false",
                    "proxy": "true",
                    "hosting": False,
                },
                handle,
            )
            filename = handle.name
        try:
            args = parse_args(["--config-file", filename, "--server-id", "8080"])
            self.assertIs(args.mobile, False)
            self.assertIs(args.proxy, True)
            self.assertIs(args.hosting, False)
        finally:
            os.unlink(filename)

    def test_proxy_store_boolean_filter_and_sticky_modes(self):
        candidates = [
            {"id": 1, "protocol": "http", "ip": "one.example", "port": 8001, "cost": 0.1, "mobile": 0},
            {"id": 2, "protocol": "socks5", "ip": "two.example", "port": 8002, "cost": 0.2, "mobile": 1},
        ]
        args = server_args(rotate="sticky", mobile=False)
        store = ProxyStore(args)
        store._candidates = candidates
        store._last_load = time.time()
        filtered = store.fetch_candidates()
        self.assertEqual([row["id"] for row in filtered], [1])
        first = store.select(client_key="203.0.113.10")
        second = store.select(client_key="203.0.113.10")
        self.assertEqual(first["id"], second["id"])

        store.args.mobile = None
        store.args.sticky_upstream = "id:2"
        self.assertEqual(store.select(client_key="anything")["id"], 2)

    def test_https_upstream_uses_proxy_sni_not_destination(self):
        raw = FakeSocket([])
        wrapped = FakeSocket([b"HTTP/1.1 200 Connection Established\r\n\r\n"])
        context = Mock()
        context.wrap_socket.return_value = wrapped
        with (
            patch("proxy_server.utils.network.socket.create_connection", return_value=raw),
            patch("proxy_server.utils.network._tls_context", return_value=context),
        ):
            result = connect_via_upstream(
                "proxy.example",
                8443,
                "https",
                "destination.example",
                443,
                upstream_server_name="proxy.example",
            )
        self.assertIs(result, wrapped)
        context.wrap_socket.assert_called_once_with(raw, server_hostname="proxy.example")
        self.assertIn(b"CONNECT destination.example:443", wrapped.sent[0])

    def test_http_connect_requires_real_2xx_status(self):
        fake = FakeSocket([b"HTTP/1.1 1200 Not-A-Success\r\n\r\n"])
        with patch("proxy_server.utils.network.socket.create_connection", return_value=fake):
            with self.assertRaisesRegex(Exception, "rejected CONNECT"):
                connect_via_upstream("proxy.example", 8080, "http", "target.example", 443)
        self.assertTrue(fake.closed)

    def test_socks5_rejects_unsupported_auth_method_without_reading_request(self):
        client, server = socket.socketpair()
        store = SimpleNamespace(args=server_args(username=None, password=None))
        thread = threading.Thread(target=handle_socks5_client, args=(server, store, 1))
        thread.start()
        try:
            # Deliberately split the greeting to exercise recv_exact.
            client.sendall(b"\x05")
            client.sendall(b"\x01")
            client.sendall(b"\x02")
            self.assertEqual(client.recv(2), b"\x05\xff")
            self.assertEqual(client.recv(1), b"")
        finally:
            client.close()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_http_listener_forwards_absolute_request_through_http_upstream(self):
        LocalProxyHandler.requests = []
        upstream_server, upstream_thread = start_tcp_server(LocalProxyHandler)
        upstream = {
            "id": 1,
            "protocol": "http",
            "ip": "127.0.0.1",
            "port": upstream_server.server_address[1],
            "cost": 0.1,
        }
        store = RoutingStore(server_args(protocol="http", threads=4), upstream)
        listener, listener_thread, port = start_listener(store)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                client.sendall(b"GET http://example.test/demo HTTP/1.1\r\nHost: example.test\r\n\r\n")
                response = bytearray()
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
            self.assertIn(b"proxypool-http-integration", response)
            self.assertTrue(LocalProxyHandler.requests)
            self.assertTrue(LocalProxyHandler.requests[-1].startswith(b"GET http://example.test/demo HTTP/1.1"))
            self.assertGreaterEqual(store.alive, 1)
        finally:
            listener.shutdown()
            listener_thread.join(timeout=3)
            upstream_server.shutdown()
            upstream_server.server_close()
            upstream_thread.join(timeout=3)

    def test_http_connect_tunnels_bytes_through_http_upstream(self):
        echo_server, echo_thread = start_tcp_server(EchoHandler)
        upstream_server, upstream_thread = start_tcp_server(LocalProxyHandler)
        upstream = {
            "id": 2,
            "protocol": "http",
            "ip": "127.0.0.1",
            "port": upstream_server.server_address[1],
            "cost": 0.1,
        }
        store = RoutingStore(server_args(protocol="http", threads=4), upstream)
        listener, listener_thread, port = start_listener(store)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                target = f"127.0.0.1:{echo_server.server_address[1]}".encode()
                client.sendall(b"CONNECT " + target + b" HTTP/1.1\r\nHost: " + target + b"\r\n\r\n")
                header = bytearray()
                while b"\r\n\r\n" not in header:
                    header.extend(client.recv(4096))
                self.assertTrue(header.startswith(b"HTTP/1.1 200"))
                client.sendall(b"tunnel-payload")
                self.assertEqual(client.recv(64), b"tunnel-payload")
        finally:
            listener.shutdown()
            listener_thread.join(timeout=3)
            upstream_server.shutdown()
            upstream_server.server_close()
            upstream_thread.join(timeout=3)
            echo_server.shutdown()
            echo_server.server_close()
            echo_thread.join(timeout=3)

    def test_server_lifecycle_rejects_pid_reuse_and_terminates_owned_process(self):
        with tempfile.TemporaryDirectory(prefix="server-life-") as root:
            server_id = "18080"
            token = reserve_start(root, server_id)
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)", "--server-id", server_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                claim(root, server_id, pid=process.pid, token=token)
                self.assertTrue(process_matches(process.pid, server_id))
                self.assertTrue(snapshot(root, server_id)["running"])
                self.assertFalse(process_matches(os.getpid(), server_id))
                result = terminate(root, server_id, grace_seconds=2)
                process.wait(timeout=5)
                self.assertTrue(result["found"])
                self.assertTrue(result["stopped"])
                self.assertFalse(snapshot(root, server_id)["running"])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_dashboard_start_keeps_listener_secret_out_of_process_arguments(self):
        captured = {}
        fake_process = SimpleNamespace(pid=43210, poll=lambda: None)

        def fake_popen(command, **_kwargs):
            captured["command"] = command
            return fake_process

        config = {
            "18081": {
                "pid": None,
                "protocol": "http",
                "config": {
                    "protocol": "http",
                    "bind": "0.0.0.0",
                    "port": 18081,
                    "username": "listener-user",
                    "password": "listener-secret",
                },
            }
        }
        with tempfile.TemporaryDirectory(prefix="server-route-") as root:
            with (
                patch("dashboard.routes.server._project_root", return_value=root),
                patch("dashboard.routes.server.load_servers_config", return_value=config),
                patch("dashboard.routes.server.save_servers_config"),
                patch("dashboard.routes.server.reserve_server_start", return_value="claim-token"),
                patch("dashboard.routes.server.write_runtime_json"),
                patch("dashboard.routes.server.subprocess.Popen", side_effect=fake_popen),
                patch(
                    "dashboard.routes.server.wait_until_claimed",
                    return_value={"process_create_time": 123.0, "state": "running"},
                ),
                self.admin_client() as client,
            ):
                response = client.post("/api/server/start", json={"port": 18081})
        self.assertEqual(response.status_code, 200)
        command = captured["command"]
        joined = " ".join(command)
        self.assertNotIn("listener-user", joined)
        self.assertNotIn("listener-secret", joined)
        self.assertIn("--config-file", command)
        self.assertIn("--server-id", command)


if __name__ == "__main__":
    unittest.main()
