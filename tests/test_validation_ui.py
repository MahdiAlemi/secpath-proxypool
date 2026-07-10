import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from config import config
from dashboard import create_app
from database import MonitorSession, MonitorTested, Proxy, db
from tests.test_ui_foundation import _HtmlDocument


class ValidationUIRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-validation-ui-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(Path(cls.temp_dir.name) / "validation.sqlite")
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
            session.query(MonitorTested).delete()
            session.query(MonitorSession).delete()
            session.query(Proxy).delete()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def test_validation_workspace_uses_dedicated_assets_and_compact_structure(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=monitor")
        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        styles = {item.get("href") for item in document.find_all(tag="link")}
        scripts = {item.get("src") for item in document.find_all(tag="script")}
        self.assertIn("/static/css/validation.css", styles)
        self.assertIn("/static/js/validation.js", scripts)
        self.assertIsNotNone(document.find(element_id="validation-profile-list"))
        self.assertIsNotNone(document.find(element_id="validation-detail"))
        self.assertIsNotNone(document.find(element_id="validation-results-body"))
        self.assertIsNotNone(document.find(element_id="validation-log-output"))
        html = response.get_data(as_text=True)
        self.assertIn("Know what each proxy can actually do", html)
        self.assertNotIn("monitors-grid", html)

        project_root = Path(__file__).resolve().parents[1]
        base_script = (project_root / "dashboard/static/js/base.js").read_text(encoding="utf-8")
        self.assertNotIn("function updateMonitorOverview", base_script)
        self.assertNotIn("async function checkMonitorStatus", base_script)
        self.assertLess(
            len((project_root / "dashboard/templates/pages/monitor.html").read_text(encoding="utf-8").splitlines()),
            180,
        )

    def test_preview_is_non_mutating_and_reports_candidate_mix(self):
        hosts = [f"candidate-{index}-{uuid4().hex[:7]}.example" for index in range(3)]
        with db.session() as session:
            session.add_all(
                [
                    Proxy(protocol="http", ip=hosts[0], port=8000, status="untested", web_https_ok=False),
                    Proxy(protocol="http", ip=hosts[1], port=8001, status="alive", web_https_ok=True, remote_dns_ok=True),
                    Proxy(protocol="socks5", ip=hosts[2], port=1080, status="alive", telegram_ok=True),
                ]
            )
            before = session.query(Proxy).count()

        with self.admin_client() as client:
            response = client.post(
                "/api/monitor/preview",
                json={
                    "name": "HTTP readiness",
                    "protocol": "http",
                    "status": "alive,untested",
                    "threads": 20,
                    "timeout": 5,
                    "probes": 2,
                    "run_mode": "once",
                    "geo": "true",
                    "create_service": "no",
                },
            )
        self.assertEqual(response.status_code, 200)
        preview = response.get_json()["preview"]
        self.assertEqual(preview["total"], 2)
        self.assertEqual(preview["protocols"], {"http": 2})
        self.assertEqual(preview["statuses"]["alive"], 1)
        self.assertEqual(preview["statuses"]["untested"], 1)
        self.assertEqual(preview["capabilities"]["web_https"], 1)
        self.assertEqual(len(preview["samples"]), 2)
        with db.session() as session:
            self.assertEqual(session.query(Proxy).count(), before)

    def test_preview_rejects_invalid_profile_without_creating_runtime_state(self):
        with self.admin_client() as client:
            response = client.post(
                "/api/monitor/preview",
                json={"name": "Bad profile", "threads": 999, "run_mode": "once"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_monitor_config")
        with db.session() as session:
            self.assertEqual(session.query(MonitorSession).count(), 0)

    def test_recent_results_are_redacted_and_limited_to_profile(self):
        monitor_id = "monitor_ui-results"
        other_id = "monitor_other-results"
        with db.session() as session:
            first = Proxy(
                protocol="socks5",
                ip=f"result-{uuid4().hex[:8]}.example",
                port=1080,
                username="private-user",
                password="private-password",
                status="alive",
                speed_ms=42,
                countryCode="DE",
                web_https_ok=True,
                remote_dns_ok=True,
                telegram_ok=True,
                last_checked=datetime.now(timezone.utc),
            )
            second = Proxy(protocol="http", ip=f"other-{uuid4().hex[:8]}.example", port=8080, status="dead")
            session.add_all([first, second])
            session.flush()
            session.add(MonitorSession(id=monitor_id, total_proxies=1, tested_count=1, alive_count=1, status="completed"))
            session.add(MonitorTested(session_id=monitor_id, proxy_id=first.id))
            session.add(MonitorTested(session_id=other_id, proxy_id=second.id))

        registry = {monitor_id: {"name": "UI results", "config": {"name": "UI results"}}}
        with patch("dashboard.routes.monitor.load_monitors_config", return_value=registry):
            with self.admin_client() as client:
                response = client.get(f"/api/monitor/{monitor_id}/results?limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["speed_ms"], 42)
        self.assertTrue(result["telegram_ok"])
        self.assertNotIn("username", result)
        self.assertNotIn("password", result)
        self.assertNotIn("private-password", response.get_data(as_text=True))
        self.assertEqual(payload["session"]["tested"], 1)

    def test_recent_results_validate_profile_and_limit(self):
        registry = {"monitor_known": {"name": "Known", "config": {}}}
        with patch("dashboard.routes.monitor.load_monitors_config", return_value=registry):
            with self.admin_client() as client:
                missing = client.get("/api/monitor/monitor_missing/results")
                oversized = client.get("/api/monitor/monitor_known/results?limit=1000")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(oversized.get_json()["code"], "invalid_limit")

    def test_validation_profile_modal_has_accessible_status_controls_and_preview(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=monitor")
        document = _HtmlDocument(response.data)
        self.assertIsNotNone(document.find(element_id="validation-profile-modal-title"))
        self.assertIsNotNone(document.find(element_id="validation-preview-total"))
        for status in ("untested", "alive", "soft", "flaky", "cooling", "revived", "semi-revived", "dead"):
            element = document.find(element_id=f"monitor-status-{status}")
            self.assertIsNotNone(element)
            self.assertEqual(element.get("type"), "button")


if __name__ == "__main__":
    unittest.main()
