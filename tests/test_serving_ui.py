import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from config import config
from dashboard import create_app
from dashboard.routes.server import _normalize_server_config
from database import Proxy, db
from tests.test_ui_foundation import _HtmlDocument


class ServingUIRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-serving-ui-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(Path(cls.temp_dir.name) / "serving.sqlite")
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
            session.query(Proxy).delete()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    @staticmethod
    def profile_config(**overrides):
        value = {
            "name": "Local web route",
            "use_case": "web",
            "protocol": "http",
            "bind": "127.0.0.1",
            "port": 18080,
            "rotate": "better_cost",
            "rotate_interval": 60,
            "min_cost": 0,
            "cost_threshold": None,
            "threads": 100,
            "timeout": 10,
            "header_limit": 65536,
            "candidate_statuses": "alive",
            "upstream_protocol": "http,socks5",
            "require_web_https": True,
            "require_remote_dns": False,
            "require_telegram": False,
            "username": "listener-user",
            "password": "listener-password",
            "allow_public_no_auth": False,
            "insecure_upstream": False,
            "readonly": False,
        }
        value.update(overrides)
        return value

    def test_serving_workspace_uses_dedicated_assets_and_compact_structure(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=server")
        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        styles = {item.get("href") for item in document.find_all(tag="link")}
        scripts = {item.get("src") for item in document.find_all(tag="script")}
        self.assertIn("/static/css/serving.css", styles)
        self.assertIn("/static/js/serving.js", scripts)
        self.assertIsNotNone(document.find(element_id="serving-profile-list"))
        self.assertIsNotNone(document.find(element_id="serving-detail"))
        self.assertIsNotNone(document.find(element_id="serving-log-output"))
        self.assertIsNotNone(document.find(element_id="serving-preview-total"))
        html = response.get_data(as_text=True)
        self.assertIn("Build controlled local routes", html)
        self.assertNotIn("servers-grid", html)

        project_root = Path(__file__).resolve().parents[1]
        base_script = (project_root / "dashboard/static/js/base.js").read_text(encoding="utf-8")
        self.assertNotIn("async function checkServerStatus", base_script)
        self.assertNotIn("function collectServerFormData", base_script)
        self.assertLess(
            len((project_root / "dashboard/templates/pages/server.html").read_text(encoding="utf-8").splitlines()),
            150,
        )

    def test_detail_redacts_credentials_and_returns_scoped_preflight(self):
        host = f"serving-{uuid4().hex[:8]}.example"
        with db.session() as session:
            session.add_all(
                [
                    Proxy(
                        protocol="http",
                        ip=host,
                        port=8080,
                        status="alive",
                        cost=0.2,
                        username="upstream-user",
                        password="upstream-password",
                        web_https_ok=True,
                    ),
                    Proxy(protocol="socks5", ip=f"skip-{host}", port=1080, status="dead", web_https_ok=True),
                ]
            )
        registry = {"18080": {"pid": None, "protocol": "http", "config": self.profile_config()}}
        log_path = Path(self.temp_dir.name) / "server_18080.log"
        log_path.write_text("listener ready\n", encoding="utf-8")
        with (
            patch("dashboard.routes.server.load_servers_config", return_value=registry),
            patch("dashboard.routes.server.get_server_status", return_value={"running": False, "pid": None}),
            patch("dashboard.routes.server._project_root", return_value=self.temp_dir.name),
        ):
            with self.admin_client() as client:
                response = client.get("/api/server/18080")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["config"]["name"], "Local web route")
        self.assertTrue(payload["config"]["has_auth"])
        self.assertNotIn("username", payload["config"])
        self.assertNotIn("password", payload["config"])
        self.assertEqual(payload["candidates"]["total"], 1)
        self.assertEqual(payload["candidates"]["by_protocol"]["http"], 1)
        self.assertNotIn("username", payload["candidates"]["samples"][0])
        self.assertNotIn("listener-password", response.get_data(as_text=True))
        self.assertNotIn("upstream-password", response.get_data(as_text=True))
        self.assertEqual(payload["endpoint"]["uri"], "http://127.0.0.1:18080")
        self.assertEqual(payload["log"]["lines"], ["listener ready\n"])

    def test_preview_validates_statuses_and_upstream_protocols(self):
        with self.admin_client() as client:
            bad_status = client.post(
                "/api/server/preview-candidates",
                json={**self.profile_config(username=None, password=None), "candidate_statuses": "alive,unknown"},
            )
            bad_protocol = client.post(
                "/api/server/preview-candidates",
                json={**self.profile_config(username=None, password=None), "upstream_protocol": "http,ftp"},
            )
        self.assertEqual(bad_status.status_code, 400)
        self.assertEqual(bad_status.get_json()["code"], "invalid_server_config")
        self.assertEqual(bad_protocol.status_code, 400)
        self.assertEqual(bad_protocol.get_json()["code"], "invalid_server_config")

    def test_log_tail_is_bounded_and_requires_existing_profile(self):
        root = Path(self.temp_dir.name)
        (root / "server_18080.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
        registry = {"18080": {"pid": None, "protocol": "http", "config": self.profile_config()}}
        with (
            patch("dashboard.routes.server.load_servers_config", return_value=registry),
            patch("dashboard.routes.server._project_root", return_value=self.temp_dir.name),
        ):
            with self.admin_client() as client:
                response = client.get("/api/server/log?port=18080&limit=2")
                oversized = client.get("/api/server/log?port=18080&limit=501")
                missing = client.get("/api/server/log?port=18081")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["lines"], ["two\n", "three\n"])
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_edit_preview_preserves_existing_network_credentials_without_exposing_them(self):
        registry = {
            "18080": {
                "pid": None,
                "protocol": "http",
                "config": self.profile_config(bind="0.0.0.0"),
            }
        }
        with patch("dashboard.routes.server.load_servers_config", return_value=registry):
            with self.admin_client() as client:
                response = client.post(
                    "/api/server/preview-candidates",
                    json={
                        **self.profile_config(bind="0.0.0.0", username=None, password=None),
                        "existing_port": 18080,
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("listener-password", response.get_data(as_text=True))

    def test_profile_normalization_preserves_product_metadata_and_deduplicates_filters(self):
        normalized = _normalize_server_config(
            {
                **self.profile_config(username=None, password=None),
                "name": "  Telegram gateway  ",
                "use_case": "telegram",
                "candidate_statuses": "alive,alive,soft",
                "upstream_protocol": "socks5,http,socks5",
            }
        )
        self.assertEqual(normalized["name"], "Telegram gateway")
        self.assertEqual(normalized["use_case"], "telegram")
        self.assertEqual(normalized["candidate_statuses"], "alive,soft")
        self.assertEqual(normalized["upstream_protocol"], "socks5,http")

    def test_detail_and_log_reject_unknown_profiles(self):
        with patch("dashboard.routes.server.load_servers_config", return_value={}):
            with self.admin_client() as client:
                detail = client.get("/api/server/19090")
                log = client.get("/api/server/log?port=19090")
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(log.status_code, 404)


if __name__ == "__main__":
    unittest.main()
