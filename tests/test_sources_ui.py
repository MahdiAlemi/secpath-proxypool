import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import inspect

from config import config
from dashboard import create_app
from dashboard.imports import ImportInputError, SourceText
from database import ImportRun, ImportSource, Proxy, db
from tests.test_ui_foundation import _HtmlDocument


class SourcesUIRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-sources-")
        cls.config_type = type(config)
        cls.original_database_config = {
            "DB_TYPE": cls.config_type.DB_TYPE,
            "DATABASE_URL": cls.config_type.DATABASE_URL,
            "SQLITE_DB_PATH": cls.config_type.SQLITE_DB_PATH,
        }
        db.close()
        cls.config_type.DB_TYPE = "sqlite"
        cls.config_type.DATABASE_URL = ""
        cls.config_type.SQLITE_DB_PATH = str(Path(cls.temp_dir.name) / "sources.sqlite")
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
            session.query(ImportRun).delete()
            session.query(ImportSource).delete()
            session.query(Proxy).delete()
            session.commit()

    def admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"
            browser_session["user_id"] = 0
        return client

    def test_sources_workspace_uses_dedicated_assets_and_schema(self):
        with self.admin_client() as client:
            response = client.get("/index?tab=import")
        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        styles = {item.get("href") for item in document.find_all(tag="link")}
        scripts = {item.get("src") for item in document.find_all(tag="script")}
        self.assertIn("/static/css/sources.css", styles)
        self.assertIn("/static/js/sources.js", scripts)
        self.assertIsNotNone(document.find(element_id="source-manual-content"))
        self.assertIsNotNone(document.find(element_id="source-url-input"))
        self.assertIsNotNone(document.find(element_id="source-links-content"))
        self.assertIsNotNone(document.find(element_id="source-dialog-url"))
        self.assertIsNotNone(document.find(element_id="source-dialog-content"))
        html = response.get_data(as_text=True)
        self.assertIn("Inspect candidates before they touch inventory", html)
        self.assertNotIn("showImportTab(", html)

        project_root = Path(__file__).resolve().parents[1]
        base_script = (project_root / "dashboard/static/js/base.js").read_text(encoding="utf-8")
        self.assertNotIn("function doImportUrl", base_script)
        self.assertNotIn("function countImportManual", base_script)
        self.assertLess(
            len((project_root / "dashboard/templates/pages/import.html").read_text(encoding="utf-8").splitlines()),
            210,
        )
        tables = set(inspect(db.engine).get_table_names())
        self.assertTrue({"import_sources", "import_runs"} <= tables)

    def test_manual_preview_is_non_mutating_and_redacts_credentials(self):
        existing_host = f"existing-{uuid4().hex[:8]}.example"
        new_host = f"new-{uuid4().hex[:8]}.example"
        with db.session() as session:
            session.add(Proxy(protocol="http", ip=existing_host, port=8080, username="", password=""))
            session.commit()
            before = session.query(Proxy).count()

        content = "\n".join(
            [
                f"http {existing_host}:8080",
                f"http {new_host}:8081 private-user private-secret",
                f"http {new_host}:8081 private-user private-secret",
                "not-a-proxy",
            ]
        )
        with self.admin_client() as client:
            response = client.post(
                "/api/import/preview",
                json={"mode": "manual", "protocol": "http", "proxies": content},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["summary"]["valid"], 2)
        self.assertEqual(payload["summary"]["new"], 1)
        self.assertEqual(payload["summary"]["existing"], 1)
        self.assertEqual(payload["summary"]["invalid"], 1)
        self.assertEqual(payload["summary"]["input_duplicates"], 1)
        self.assertNotIn("private-secret", response.get_data(as_text=True))
        self.assertTrue(any(sample["has_auth"] for sample in payload["samples"]))
        with db.session() as session:
            self.assertEqual(session.query(Proxy).count(), before)
            self.assertEqual(session.query(ImportRun).count(), 0)

    def test_manual_import_records_sanitized_history(self):
        host = f"manual-{uuid4().hex[:8]}.example"
        with self.admin_client() as client:
            response = client.post(
                "/api/import",
                json={
                    "mode": "manual",
                    "protocol": "http",
                    "proxies": f"http {host}:8080 user-for-db secret-for-db",
                    "source_name": "Private batch",
                },
            )
            history = client.get("/api/import/runs")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["status"], "completed")
        history_payload = history.get_json()
        self.assertEqual(len(history_payload["runs"]), 1)
        self.assertEqual(history_payload["runs"][0]["source_name"], "Private batch")
        self.assertNotIn("secret-for-db", history.get_data(as_text=True))
        with db.session() as session:
            proxy = session.query(Proxy).filter_by(ip=host).one()
            self.assertEqual(proxy.password, "secret-for-db")
            self.assertEqual(session.query(ImportRun).count(), 1)

    def test_saved_source_crud_keeps_config_out_of_collection_response(self):
        with self.admin_client() as client:
            created = client.post(
                "/api/import/sources",
                json={
                    "name": "Daily HTTP",
                    "mode": "url",
                    "protocol": "http",
                    "url": "https://token@example.org/list.txt?secret=hidden",
                    "is_active": True,
                },
            )
            self.assertEqual(created.status_code, 201)
            source_id = created.get_json()["source"]["id"]
            collection = client.get("/api/import/sources")
            detail = client.get(f"/api/import/sources/{source_id}")
            updated = client.put(
                f"/api/import/sources/{source_id}",
                json={
                    "name": "Daily HTTP disabled",
                    "mode": "url",
                    "protocol": "https",
                    "url": "https://example.org/next.txt",
                    "is_active": False,
                },
            )
            deleted = client.delete(f"/api/import/sources/{source_id}")

        self.assertEqual(collection.status_code, 200)
        listed = collection.get_json()["sources"][0]
        self.assertNotIn("url", listed)
        self.assertNotIn("content", listed)
        self.assertEqual(detail.get_json()["source"]["url"], "https://token@example.org/list.txt?secret=hidden")
        self.assertFalse(updated.get_json()["source"]["is_active"])
        self.assertEqual(deleted.status_code, 200)

    def test_saved_source_preview_and_run_update_source_and_history(self):
        host = f"saved-{uuid4().hex[:8]}.example"
        with self.admin_client() as client:
            created = client.post(
                "/api/import/sources",
                json={
                    "name": "Repeatable source",
                    "mode": "url",
                    "protocol": "socks5",
                    "url": "https://sources.example/proxies.txt",
                },
            )
            source_id = created.get_json()["source"]["id"]
            with patch(
                "dashboard.imports.fetch_public_text",
                return_value=SourceText(f"{host}:1080\n{host}:1080", 40),
            ):
                preview = client.post(f"/api/import/sources/{source_id}/preview")
                run = client.post(f"/api/import/sources/{source_id}/run")
            detail = client.get(f"/api/import/sources/{source_id}")
            history = client.get("/api/import/runs")

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()["summary"]["new"], 1)
        self.assertEqual(preview.get_json()["summary"]["input_duplicates"], 1)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.get_json()["added"], 1)
        saved = detail.get_json()["source"]
        self.assertEqual(saved["last_status"], "completed")
        self.assertEqual(saved["last_added"], 1)
        self.assertEqual(history.get_json()["runs"][0]["source_id"], source_id)

    def test_grouped_source_reports_partial_failure_without_losing_successes(self):
        host = f"partial-{uuid4().hex[:8]}.example"
        content = "\n".join(
            [
                "[http]",
                "https://good.example/http.txt",
                "[socks5]",
                "https://bad.example/socks.txt",
            ]
        )

        def fake_fetch(url):
            if "bad.example" in url:
                raise ImportInputError("simulated source failure")
            return SourceText(f"{host}:8080", 24)

        with self.admin_client() as client, patch(
            "dashboard.imports.fetch_public_text", side_effect=fake_fetch
        ):
            preview = client.post(
                "/api/import/preview", json={"mode": "links", "content": content}
            )
            run = client.post(
                "/api/import", json={"mode": "links", "content": content}
            )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(len(preview.get_json()["errors"]), 1)
        self.assertEqual(preview.get_json()["summary"]["new"], 1)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.get_json()["status"], "partial")
        self.assertEqual(run.get_json()["added"], 1)
        with db.session() as session:
            self.assertIsNotNone(session.query(Proxy).filter_by(ip=host).first())
            self.assertEqual(session.query(ImportRun).one().status, "partial")

    def test_disabled_source_cannot_run(self):
        with self.admin_client() as client:
            created = client.post(
                "/api/import/sources",
                json={
                    "name": "Disabled source",
                    "mode": "url",
                    "protocol": "http",
                    "url": "https://example.org/list.txt",
                    "is_active": False,
                },
            )
            source_id = created.get_json()["source"]["id"]
            response = client.post(f"/api/import/sources/{source_id}/run")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "source_disabled")


if __name__ == "__main__":
    unittest.main()
