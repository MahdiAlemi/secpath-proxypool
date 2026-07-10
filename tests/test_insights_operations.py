import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bcrypt

from config import config
from dashboard import create_app
from database import Proxy, Token, User, db
from tests.test_ui_foundation import _HtmlDocument


class InsightsOperationsRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-admin-ui-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(Path(cls.temp_dir.name) / "admin.sqlite")
        db._init_engine()
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        db.close()
        for name, value in cls.original_database_config.items():
            setattr(cls.config_type, name, value)
        db._init_engine()
        cls.temp_dir.cleanup()

    def setUp(self):
        with db.session() as session:
            session.query(Token).delete()
            session.query(User).delete()
            session.query(Proxy).delete()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
            browser_session["_csrf_token"] = "test-csrf"
        return client

    @staticmethod
    def csrf_headers():
        return {"X-CSRF-Token": "test-csrf"}

    def create_user(self, username, role="user", active=True, custom=None):
        with db.session() as session:
            user = User(
                username=username,
                password_hash=bcrypt.hashpw(b"correct-horse-battery", bcrypt.gensalt()).decode("utf-8"),
                role=role,
                custom_permissions=custom or {},
                is_active=active,
            )
            session.add(user)
            session.commit()
            return user.id

    def test_stats_returns_decision_oriented_quality_bands(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with db.session() as session:
            session.add_all(
                [
                    Proxy(protocol="http", ip="198.51.100.1", port=8001, status="alive", speed_ms=120, reliability=0.98, last_checked=now - timedelta(minutes=10), web_https_ok=True, remote_dns_ok=True, telegram_ok=True, countryCode="DE", isp="ISP A"),
                    Proxy(protocol="socks5", ip="198.51.100.2", port=8002, status="alive", speed_ms=650, reliability=0.75, last_checked=now - timedelta(hours=4), web_https_ok=True, remote_dns_ok=True, countryCode="DE", isp="ISP A"),
                    Proxy(protocol="http", ip="198.51.100.3", port=8003, status="flaky", speed_ms=900, reliability=0.45, last_checked=now - timedelta(days=2), countryCode="US", isp="ISP B"),
                    Proxy(protocol="https", ip="198.51.100.4", port=8004, status="untested", last_checked=None),
                ]
            )
        with self.admin_client() as client:
            response = client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["quality"]["tested"], 3)
        self.assertEqual(payload["quality"]["stable"], 2)
        self.assertEqual(payload["freshness"]["under_1h"], 1)
        self.assertEqual(payload["freshness"]["never"], 1)
        self.assertEqual(payload["latency_bands"]["fast"], 1)
        self.assertEqual(payload["latency_bands"]["balanced"], 1)
        self.assertEqual(payload["reliability_bands"]["high"], 1)
        self.assertIn("concentration", payload)

    def test_operations_and_access_use_dedicated_pages_and_assets(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=operations")
        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        styles = {item.get("href") for item in document.find_all(tag="link")}
        scripts = {item.get("src") for item in document.find_all(tag="script")}
        self.assertIn("/static/css/insights.css", styles)
        self.assertIn("/static/css/operations.css", styles)
        self.assertIn("/static/js/insights.js", scripts)
        self.assertIn("/static/js/operations.js", scripts)
        self.assertIn("/static/js/access.js", scripts)
        self.assertIsNotNone(document.find(element_id="tab-operations"))
        self.assertIsNotNone(document.find(element_id="tab-users"))
        html = response.get_data(as_text=True)
        self.assertNotIn('id="modal-settings"', html)
        self.assertNotIn('id="modal-users"', html)

    def test_diagnostics_reports_security_runtime_backup_and_access_shape(self):
        self.create_user("operator")
        with self.admin_client() as client:
            response = client.get("/api/settings/diagnostics")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("security", payload)
        self.assertIn("backups", payload)
        self.assertIn("access", payload)
        self.assertIn("running_monitors", payload["runtime"])
        self.assertEqual(payload["access"]["users"], 1)
        self.assertNotIn("correct-horse-battery", response.get_data(as_text=True))

    def test_runtime_cleanup_refuses_to_run_while_owned_process_is_active(self):
        with (
            patch("dashboard.config.load_monitors_config", return_value={"monitor_live": {"pid": 123, "process_create_time": 1}}),
            patch("dashboard.config.load_servers_config", return_value={}),
            patch("proxy_monitor.lifecycle.process_matches", return_value=True),
        ):
            with self.admin_client() as client:
                response = client.post("/api/settings/cleanup/runtime", headers=self.csrf_headers())
        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["code"], "runtime_active")
        self.assertEqual(payload["active"]["monitors"], ["monitor_live"])


    def test_runtime_cleanup_detects_orphaned_active_server_state(self):
        with tempfile.TemporaryDirectory(prefix="proxypool-runtime-state-") as runtime_root:
            state_dir = Path(runtime_root) / ".runtime" / "servers"
            state_dir.mkdir(parents=True)
            (state_dir / "9090.json").write_text(
                '{"state":"running","pid":321,"process_create_time":1}',
                encoding="utf-8",
            )
            with (
                patch("dashboard.routes.settings.BASE_DIR", runtime_root),
                patch("dashboard.config.load_monitors_config", return_value={}),
                patch("dashboard.config.load_servers_config", return_value={}),
                patch("proxy_server.lifecycle.process_matches", return_value=True),
            ):
                with self.admin_client() as client:
                    response = client.post("/api/settings/cleanup/runtime", headers=self.csrf_headers())
        self.assertEqual(response.status_code, 409)
        payload = response.get_json()
        self.assertEqual(payload["code"], "runtime_active")
        self.assertEqual(payload["active"]["servers"], ["9090"])

    def test_user_directory_enriches_permissions_scope_and_session_count(self):
        user_id = self.create_user(
            "scoped-user",
            custom={"add": ["stats.view"], "remove": [], "proxy_filters": {"statuses": ["alive"], "protocols": ["http"]}},
        )
        with db.session() as session:
            session.add(Token(user_id=user_id, token="token-value", expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)))
        with self.admin_client() as client:
            listing = client.get("/api/users")
            detail = client.get(f"/api/users/{user_id}")
        self.assertEqual(listing.status_code, 200)
        row = listing.get_json()[0]
        self.assertIn("stats.view", row["effective_permissions"])
        self.assertEqual(row["proxy_scope"]["statuses"], ["alive"])
        self.assertEqual(row["token_count"], 1)
        self.assertEqual(detail.get_json()["username"], "scoped-user")
        self.assertNotIn("password_hash", detail.get_json())

    def test_last_active_administrator_cannot_be_demoted_or_deleted(self):
        admin_id = self.create_user("only-admin", role="admin")
        with self.admin_client() as client:
            demote = client.put(
                f"/api/users/{admin_id}",
                headers={**self.csrf_headers(), "Content-Type": "application/json"},
                json={"role": "user"},
            )
            delete = client.delete(f"/api/users/{admin_id}", headers=self.csrf_headers())
        self.assertEqual(demote.status_code, 409)
        self.assertEqual(demote.get_json()["code"], "last_administrator")
        self.assertEqual(delete.status_code, 409)
        self.assertEqual(delete.get_json()["code"], "last_administrator")

    def test_named_backup_download_rejects_untrusted_name(self):
        with self.admin_client() as client:
            response = client.get("/api/settings/backups/not-a-backup.sqlite")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_backup_name")


if __name__ == "__main__":
    unittest.main()
