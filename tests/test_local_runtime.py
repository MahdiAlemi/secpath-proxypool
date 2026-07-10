import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import create_app
from dashboard.runtime import dashboard_bind_from_env
from database import db
from scripts.rotate_local_secrets import rotate_env_file


class LocalRuntimeRegressionTest(unittest.TestCase):
    def test_favicon_root_route_is_available_without_login(self):
        app = create_app()
        app.config["TESTING"] = True
        response = None
        try:
            with app.test_client() as client:
                response = client.get("/favicon.ico")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "image/vnd.microsoft.icon")
                self.assertGreater(len(response.data), 100)
        finally:
            if response is not None:
                response.close()
            if getattr(db, "Session", None) is not None:
                db.Session.remove()
            if getattr(db, "engine", None) is not None:
                db.engine.dispose()

    def test_dashboard_bind_defaults_to_loopback(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_HOST": "",
                "DASHBOARD_PORT": "",
                "DASHBOARD_ALLOW_PUBLIC": "false",
            },
            clear=False,
        ):
            self.assertEqual(dashboard_bind_from_env(), ("127.0.0.1", 5003))

    def test_non_loopback_bind_requires_explicit_override(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_HOST": "0.0.0.0",
                "DASHBOARD_PORT": "5003",
                "DASHBOARD_ALLOW_PUBLIC": "false",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "Refusing to expose"):
                dashboard_bind_from_env()

        with patch.dict(
            os.environ,
            {
                "DASHBOARD_HOST": "0.0.0.0",
                "DASHBOARD_PORT": "5003",
                "DASHBOARD_ALLOW_PUBLIC": "true",
            },
            clear=False,
        ):
            self.assertEqual(dashboard_bind_from_env(), ("0.0.0.0", 5003))

    def test_dashboard_port_is_validated(self):
        with patch.dict(os.environ, {"DASHBOARD_PORT": "70000"}, clear=False):
            with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
                dashboard_bind_from_env()

    def test_secret_rotation_is_atomic_private_and_does_not_return_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "DB_TYPE=sqlite\nFLASK_SECRET_KEY=old-session\nJWT_SECRET=old-jwt\n",
                encoding="utf-8",
            )
            changed = rotate_env_file(env_path)
            content = env_path.read_text(encoding="utf-8")

            self.assertEqual(changed, ("FLASK_SECRET_KEY", "JWT_SECRET"))
            self.assertNotIn("old-session", content)
            self.assertNotIn("old-jwt", content)
            values = {
                line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in content.splitlines()
                if "=" in line
            }
            self.assertEqual(len(values["FLASK_SECRET_KEY"]), 64)
            self.assertEqual(len(values["JWT_SECRET"]), 64)
            self.assertNotEqual(values["FLASK_SECRET_KEY"], values["JWT_SECRET"])
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
