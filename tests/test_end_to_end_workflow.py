import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from config import config
from dashboard import create_app
from database import ImportRun, ImportSource, Proxy, Token, User, db
from tests.test_ui_foundation import _HtmlDocument


class EndToEndWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-e2e-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(Path(cls.temp_dir.name) / "workflow.sqlite")
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
            session.query(ImportRun).delete()
            session.query(ImportSource).delete()
            session.query(Proxy).delete()
            session.query(User).delete()
            session.commit()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def test_operator_workflow_from_source_to_serving_preflight(self):
        host = f"workflow-{uuid4().hex[:10]}.example"
        source = f"http {host}:8080 workflow-user workflow-secret"

        with self.admin_client() as client:
            dashboard = client.get("/index?tab=import")
            self.assertEqual(dashboard.status_code, 200)
            document = _HtmlDocument(dashboard.data)
            self.assertIsNotNone(document.find(element_id="source-manual-content"))
            self.assertIsNotNone(document.find(element_id="tab-proxies"))
            self.assertIsNotNone(document.find(element_id="tab-monitor"))
            self.assertIsNotNone(document.find(element_id="tab-server"))

            preview = client.post(
                "/api/import/preview",
                json={"mode": "manual", "protocol": "http", "proxies": source},
            )
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.get_json()["summary"]["new"], 1)
            self.assertNotIn("workflow-secret", preview.get_data(as_text=True))

            imported = client.post(
                "/api/import",
                json={
                    "mode": "manual",
                    "protocol": "http",
                    "proxies": source,
                    "source_name": "End-to-end fixture",
                },
            )
            self.assertEqual(imported.status_code, 200)
            self.assertEqual(imported.get_json()["added"], 1)

            inventory = client.get("/api/proxies?page=1&page_size=10")
            self.assertEqual(inventory.status_code, 200)
            row = inventory.get_json()["proxies"][0]
            self.assertEqual(row["ip"], host)
            self.assertNotIn("username", row)
            self.assertNotIn("password", row)

            monitor_preview = client.post(
                "/api/monitor/preview",
                json={
                    "name": "End-to-end validation",
                    "protocol": "http",
                    "status": "untested",
                    "threads": 4,
                    "timeout": 5,
                    "probes": 1,
                    "run_mode": "once",
                    "geo": "false",
                    "create_service": "no",
                },
            )
            self.assertEqual(monitor_preview.status_code, 200)
            self.assertEqual(monitor_preview.get_json()["preview"]["total"], 1)

            with db.session() as session:
                proxy = session.query(Proxy).filter_by(ip=host).one()
                proxy.status = "alive"
                proxy.web_https_ok = True
                proxy.remote_dns_ok = True
                proxy.telegram_ok = True
                proxy.speed_ms = 85
                proxy.reliability = 0.99
                session.commit()

            serving_preview = client.post(
                "/api/server/preview-candidates",
                json={
                    "name": "End-to-end local route",
                    "use_case": "web",
                    "protocol": "http",
                    "bind": "127.0.0.1",
                    "port": 18080,
                    "candidate_statuses": "alive",
                    "upstream_protocol": "http",
                    "require_web_https": True,
                    "require_remote_dns": True,
                    "require_telegram": True,
                    "rotate": "better_cost",
                },
            )
            self.assertEqual(serving_preview.status_code, 200)
            self.assertEqual(serving_preview.get_json()["total"], 1)
            self.assertNotIn("workflow-secret", serving_preview.get_data(as_text=True))

            stats = client.get("/api/stats")
            self.assertEqual(stats.status_code, 200)
            payload = stats.get_json()
            self.assertEqual(payload["total"], 1)
            self.assertEqual(payload["alive"], 1)
            self.assertEqual(payload["full_capability"], 1)

            history = client.get("/api/import/runs")
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.get_json()["runs"][0]["source_name"], "End-to-end fixture")
            self.assertNotIn("workflow-secret", history.get_data(as_text=True))

    def test_final_ui_has_no_compatibility_layer_or_inline_template_styles(self):
        root = Path(__file__).resolve().parents[1]
        base_template = (root / "dashboard/templates/base.html").read_text(encoding="utf-8")
        modal_template = (root / "dashboard/templates/partials/modals.html").read_text(encoding="utf-8")
        monitor_template = (root / "dashboard/templates/pages/monitor.html").read_text(encoding="utf-8")
        base_script = (root / "dashboard/static/js/base.js").read_text(encoding="utf-8")

        self.assertFalse((root / "dashboard/static/css/compat.css").exists())
        self.assertNotIn("compat.css", base_template)
        self.assertIn("img/favicon.svg", base_template)
        self.assertNotIn("modal-adv-search", modal_template)
        self.assertNotIn("style=", modal_template)
        self.assertNotIn("style=", monitor_template)
        self.assertLess(len(base_script.splitlines()), 650)
        self.assertNotIn("function loadUsers", base_script)
        self.assertNotIn("function loadStats", base_script)
        self.assertNotIn("function loadSettings", base_script)
        self.assertNotIn("function loadProxies", base_script)


if __name__ == "__main__":
    unittest.main()
