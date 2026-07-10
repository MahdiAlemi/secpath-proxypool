import unittest
from uuid import uuid4

import bcrypt
from sqlalchemy import inspect

from dashboard import create_app
from database import Proxy, User, db


class FoundationRegressionTest(unittest.TestCase):
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

    def test_fresh_startup_creates_required_tables(self):
        tables = set(inspect(db.engine).get_table_names())
        self.assertTrue(
            {"proxies", "users", "tokens", "monitor_sessions", "monitor_tested"}
            <= tables
        )

    def test_delete_user_uses_browser_session_not_database_session(self):
        username = f"delete-{uuid4().hex[:10]}"
        with db.session() as db_session:
            user = User(
                username=username,
                password_hash=bcrypt.hashpw(b"test-password", bcrypt.gensalt()).decode(
                    "utf-8"
                ),
                role="user",
            )
            db_session.add(user)
            db_session.commit()
            user_id = user.id

        with self.admin_client() as client:
            response = client.delete(f"/api/users/{user_id}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        with db.session() as db_session:
            self.assertIsNone(db_session.query(User).filter_by(id=user_id).first())

    def test_proxy_add_rejects_missing_identity_without_sql_leak(self):
        with self.admin_client() as client:
            response = client.post("/api/proxies", json={})

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertNotIn("INSERT INTO", payload["error"])
        self.assertNotIn("sqlalchemy", payload["error"].lower())

    def test_proxy_add_returns_conflict_for_duplicate(self):
        host = f"proxy-{uuid4().hex[:10]}.example"
        proxy_data = {"protocol": "http", "ip": host, "port": 8080}

        with self.admin_client() as client:
            first = client.post("/api/proxies", json=proxy_data)
            second = client.post("/api/proxies", json=proxy_data)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.get_json()["error"], "Proxy already exists")

        with db.session() as db_session:
            db_session.query(Proxy).filter_by(ip=host, port=8080).delete()
            db_session.commit()


if __name__ == "__main__":
    unittest.main()
