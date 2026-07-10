import unittest
from unittest.mock import patch
from uuid import uuid4

import bcrypt

from dashboard import create_app
from dashboard.security import validate_public_peer
from database import Proxy, User, db


class SecurityRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        if getattr(db, "Session", None) is not None:
            db.Session.remove()
        if getattr(db, "engine", None) is not None:
            db.engine.dispose()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def create_user(self, *, permissions=None, filters=None):
        username = f"security-{uuid4().hex[:10]}"
        custom_permissions = {
            "add": permissions or [],
            "remove": [],
            "proxy_filters": filters or {"statuses": [], "protocols": []},
        }
        with db.session() as db_session:
            user = User(
                username=username,
                password_hash=bcrypt.hashpw(b"a-secure-test-password", bcrypt.gensalt()).decode("utf-8"),
                role="user",
                custom_permissions=custom_permissions,
                is_active=True,
            )
            db_session.add(user)
            db_session.commit()
            return user.id

    def user_client(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "restricted"
            browser_session["user_id"] = user_id
        return client

    def test_csrf_blocks_cookie_authenticated_mutation(self):
        self.app.config["TEST_CSRF_ENABLED"] = True
        try:
            client = self.admin_client()
            blocked = client.post(
                "/api/proxies",
                json={"protocol": "http", "ip": "csrf.example", "port": 8080},
            )
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(blocked.get_json()["code"], "csrf_failed")

            with client.session_transaction() as browser_session:
                token = browser_session["_csrf_token"]
            allowed = client.post(
                "/api/proxies",
                json={"protocol": "http", "ip": "csrf.example", "port": 8080},
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(allowed.status_code, 201)
        finally:
            self.app.config["TEST_CSRF_ENABLED"] = False
            with db.session() as db_session:
                db_session.query(Proxy).filter_by(ip="csrf.example").delete()
                db_session.commit()

    def test_proxy_list_redacts_upstream_credentials(self):
        host = f"secret-{uuid4().hex[:8]}.example"
        with db.session() as db_session:
            db_session.add(
                Proxy(
                    protocol="http",
                    ip=host,
                    port=8080,
                    username="alice",
                    password="super-secret",
                    status="alive",
                )
            )
            db_session.commit()
        try:
            with self.admin_client() as client:
                response = client.get(f"/api/proxies?search={host}")
            self.assertEqual(response.status_code, 200)
            row = response.get_json()["proxies"][0]
            self.assertNotIn("username", row)
            self.assertNotIn("password", row)
            self.assertTrue(row["has_auth"])
        finally:
            with db.session() as db_session:
                db_session.query(Proxy).filter_by(ip=host).delete()
                db_session.commit()

    def test_proxy_scope_applies_to_list_mutation_stats_and_export(self):
        suffix = uuid4().hex[:8]
        http_host = f"allowed-{suffix}.example"
        socks_host = f"hidden-{suffix}.example"
        user_id = self.create_user(
            permissions=["proxies.delete", "proxies.export", "stats.view"],
            filters={"statuses": ["alive"], "protocols": ["http"]},
        )
        with db.session() as db_session:
            allowed = Proxy(protocol="http", ip=http_host, port=8080, status="alive")
            hidden = Proxy(protocol="socks5", ip=socks_host, port=1080, status="alive")
            db_session.add_all([allowed, hidden])
            db_session.commit()
            hidden_id = hidden.id
        try:
            with self.user_client(user_id) as client:
                listed = client.get(f"/api/proxies?search={suffix}")
                self.assertEqual([row["ip"] for row in listed.get_json()["proxies"]], [http_host])

                denied_delete = client.delete(f"/api/proxies/{hidden_id}")
                self.assertEqual(denied_delete.status_code, 404)

                exported = client.get(f"/api/export?format=json&search={suffix}")
                exported_rows = exported.get_json()["proxies"]
                self.assertEqual([row["ip"] for row in exported_rows], [http_host])

                stats = client.get("/api/stats")
                self.assertEqual(stats.status_code, 200)
                self.assertGreaterEqual(stats.get_json()["by_protocol"]["http"], 1)
                self.assertEqual(stats.get_json()["by_protocol"]["socks5"], 0)
        finally:
            with db.session() as db_session:
                db_session.query(Proxy).filter(Proxy.ip.in_([http_host, socks_host])).delete(synchronize_session=False)
                db_session.query(User).filter_by(id=user_id).delete()
                db_session.commit()

    def test_credential_export_requires_explicit_permission(self):
        host = f"export-{uuid4().hex[:8]}.example"
        user_id = self.create_user(permissions=["proxies.export"])
        with db.session() as db_session:
            db_session.add(
                Proxy(
                    protocol="http",
                    ip=host,
                    port=3128,
                    username="export-user",
                    password="export-password",
                )
            )
            db_session.commit()
        try:
            with self.user_client(user_id) as client:
                denied = client.get(f"/api/export?format=json&search={host}&include_credentials=true")
                self.assertEqual(denied.status_code, 403)

            with self.admin_client() as client:
                allowed = client.get(f"/api/export?format=json&search={host}&include_credentials=true")
                row = allowed.get_json()["proxies"][0]
                self.assertEqual(row["username"], "export-user")
                self.assertEqual(row["password"], "export-password")
        finally:
            with db.session() as db_session:
                db_session.query(Proxy).filter_by(ip=host).delete()
                db_session.query(User).filter_by(id=user_id).delete()
                db_session.commit()


    def test_server_status_redacts_listener_credentials(self):
        config = {
            "8080": {
                "pid": None,
                "protocol": "http",
                "config": {
                    "protocol": "http",
                    "bind": "127.0.0.1",
                    "port": 8080,
                    "username": "listener-user",
                    "password": "listener-password",
                },
            }
        }
        with (
            patch("dashboard.routes.server.load_servers_config", return_value=config),
            patch(
                "dashboard.routes.server.get_server_status",
                return_value={"running": False, "pid": None},
            ),
            self.admin_client() as client,
        ):
            response = client.get("/api/server")
        self.assertEqual(response.status_code, 200)
        public_config = response.get_json()["servers"]["8080"]["config"]
        self.assertNotIn("username", public_config)
        self.assertNotIn("password", public_config)
        self.assertTrue(public_config["has_auth"])

    def test_server_port_and_monitor_log_identifiers_are_validated(self):
        with self.admin_client() as client:
            bad_server = client.post(
                "/api/server/create",
                json={"port": "../../tmp/owned", "protocol": "http"},
            )
            bad_monitor_log = client.get(
                "/api/monitor/log?monitor_id=../../dashboard"
            )
        self.assertEqual(bad_server.status_code, 400)
        self.assertEqual(bad_server.get_json()["code"], "invalid_server_config")
        self.assertEqual(bad_monitor_log.status_code, 400)
        self.assertEqual(bad_monitor_log.get_json()["code"], "invalid_monitor_id")

    def test_backup_download_requires_credentials_permission(self):
        user_id = self.create_user(permissions=["settings.edit"])
        try:
            with self.user_client(user_id) as client:
                response = client.get("/api/settings/backup/download")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["code"], "permission_denied")
        finally:
            with db.session() as db_session:
                db_session.query(User).filter_by(id=user_id).delete()
                db_session.commit()

    def test_public_peer_must_match_validated_dns_results(self):
        validate_public_peer("93.184.216.34", {"93.184.216.34"})
        with self.assertRaises(ValueError):
            validate_public_peer("127.0.0.1", {"93.184.216.34"})
        with self.assertRaises(ValueError):
            validate_public_peer("93.184.216.35", {"93.184.216.34"})

    def test_url_import_rejects_loopback_target(self):
        with self.admin_client() as client:
            response = client.post(
                "/api/import/count-url",
                json={"url": "http://127.0.0.1:8080/proxies.txt", "protocol": "http"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "source_fetch_failed")


if __name__ == "__main__":
    unittest.main()
