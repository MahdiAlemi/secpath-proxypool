import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import bcrypt

from config import config
from dashboard import create_app
from database import Proxy, User, db
from tests.test_ui_foundation import _HtmlDocument


class InventoryUIRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-inventory-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(
            Path(cls.temp_dir.name) / "inventory.sqlite"
        )
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

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def restricted_client(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "inventory-user"
            browser_session["user_id"] = user_id
        return client

    def create_restricted_user(self, filters):
        username = f"inventory-{uuid4().hex[:10]}"
        with db.session() as session:
            user = User(
                username=username,
                password_hash=bcrypt.hashpw(
                    b"inventory-test-password", bcrypt.gensalt()
                ).decode("utf-8"),
                role="user",
                custom_permissions={
                    "add": ["proxies.delete", "proxies.export"],
                    "remove": [],
                    "proxy_filters": filters,
                },
                is_active=True,
            )
            session.add(user)
            session.commit()
            return user.id

    def test_inventory_uses_dedicated_compact_ui_assets(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=proxies")

        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        styles = {item.get("href") for item in document.find_all(tag="link")}
        scripts = {item.get("src") for item in document.find_all(tag="script")}

        self.assertIn("/static/css/inventory.css", styles)
        self.assertIn("/static/js/inventory.js", scripts)
        self.assertIsNotNone(document.find(element_id="inventory-search-input"))
        self.assertIsNotNone(document.find(element_id="inventory-selection-bar"))
        self.assertIsNotNone(document.find(element_id="inventory-drawer"))
        self.assertIsNotNone(document.find(element_id="inventory-select-page"))

        html = response.get_data(as_text=True)
        self.assertIn("Inspect the proxies that can actually carry traffic.", html)
        self.assertNotIn('id="columns-menu"', html)

    def test_inventory_module_is_separate_from_legacy_base_script(self):
        project_root = Path(__file__).resolve().parents[1]
        inventory_script = project_root / "dashboard" / "static" / "js" / "inventory.js"
        inventory_template = project_root / "dashboard" / "templates" / "pages" / "inventory.html"
        self.assertTrue(inventory_script.is_file())
        self.assertTrue(inventory_template.is_file())
        self.assertGreater(len(inventory_script.read_text(encoding="utf-8")), 10000)
        self.assertLess(len(inventory_template.read_text(encoding="utf-8").splitlines()), 190)

    def test_proxy_detail_respects_scope_and_redacts_credentials(self):
        suffix = uuid4().hex[:8]
        host = f"detail-{suffix}.example"
        with db.session() as session:
            proxy = Proxy(
                protocol="http",
                ip=host,
                port=8080,
                username="hidden-user",
                password="hidden-password",
                status="alive",
                web_https_ok=True,
            )
            session.add(proxy)
            session.commit()
            proxy_id = proxy.id
        try:
            with self.admin_client() as client:
                response = client.get(f"/api/proxies/{proxy_id}")
            self.assertEqual(response.status_code, 200)
            row = response.get_json()["proxy"]
            self.assertEqual(row["ip"], host)
            self.assertTrue(row["has_auth"])
            self.assertNotIn("username", row)
            self.assertNotIn("password", row)
        finally:
            with db.session() as session:
                session.query(Proxy).filter_by(id=proxy_id).delete()
                session.commit()

    def test_selection_delete_only_removes_scoped_proxies(self):
        suffix = uuid4().hex[:8]
        allowed_host = f"selected-{suffix}.example"
        hidden_host = f"hidden-selected-{suffix}.example"
        user_id = self.create_restricted_user(
            {"statuses": ["alive"], "protocols": ["http"]}
        )
        with db.session() as session:
            allowed = Proxy(
                protocol="http", ip=allowed_host, port=8080, status="alive"
            )
            hidden = Proxy(
                protocol="socks5", ip=hidden_host, port=1080, status="alive"
            )
            session.add_all([allowed, hidden])
            session.commit()
            allowed_id, hidden_id = allowed.id, hidden.id
        try:
            with self.restricted_client(user_id) as client:
                response = client.post(
                    "/api/proxies/selection/delete",
                    json={"ids": [allowed_id, hidden_id]},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["deleted"], 1)
            with db.session() as session:
                self.assertIsNone(session.query(Proxy).filter_by(id=allowed_id).first())
                self.assertIsNotNone(session.query(Proxy).filter_by(id=hidden_id).first())
        finally:
            with db.session() as session:
                session.query(Proxy).filter(Proxy.ip.in_([allowed_host, hidden_host])).delete(
                    synchronize_session=False
                )
                session.query(User).filter_by(id=user_id).delete()
                session.commit()

    def test_selection_delete_rejects_unbounded_or_invalid_ids(self):
        with self.admin_client() as client:
            missing = client.post("/api/proxies/selection/delete", json={})
            too_many = client.post(
                "/api/proxies/selection/delete", json={"ids": list(range(1, 502))}
            )
            invalid = client.post(
                "/api/proxies/selection/delete", json={"ids": [True]}
            )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["code"], "invalid_selection")

    def test_export_accepts_grouped_status_and_capability_filters(self):
        suffix = uuid4().hex[:8]
        hosts = [
            f"export-alive-{suffix}.example",
            f"export-flaky-{suffix}.example",
            f"export-dead-{suffix}.example",
        ]
        with db.session() as session:
            session.add_all(
                [
                    Proxy(
                        protocol="http",
                        ip=hosts[0],
                        port=8001,
                        status="alive",
                        web_https_ok=True,
                    ),
                    Proxy(
                        protocol="http",
                        ip=hosts[1],
                        port=8002,
                        status="flaky",
                        web_https_ok=True,
                    ),
                    Proxy(
                        protocol="http",
                        ip=hosts[2],
                        port=8003,
                        status="dead",
                        web_https_ok=True,
                    ),
                ]
            )
            session.commit()
        try:
            with self.admin_client() as client:
                response = client.get(
                    f"/api/export?format=json&search={suffix}&status=alive,flaky&capability=web_https"
                )
            self.assertEqual(response.status_code, 200)
            exported = {row["ip"] for row in response.get_json()["proxies"]}
            self.assertEqual(exported, {hosts[0], hosts[1]})
        finally:
            with db.session() as session:
                session.query(Proxy).filter(Proxy.ip.in_(hosts)).delete(
                    synchronize_session=False
                )
                session.commit()


if __name__ == "__main__":
    unittest.main()
