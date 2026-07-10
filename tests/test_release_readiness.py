from __future__ import annotations

import json
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from backup_utils import (
    create_sqlite_backup,
    replace_sqlite_database,
    stage_sqlite_copy,
    validate_sqlite_database,
)
from database import Base, Proxy

ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="proxypool-release-test-")
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source.sqlite"
        engine = create_engine(f"sqlite:///{self.source}")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    Proxy.__table__.insert().values(
                        protocol="http",
                        ip="203.0.113.77",
                        port=8080,
                        username="private-user",
                        password="private-password",
                        status="alive",
                        web_https_ok=True,
                        remote_dns_ok=True,
                        validation_summary={"profile": "release-test"},
                    )
                )
        finally:
            engine.dispose()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_private_backups_are_unique_valid_and_mode_0600(self):
        first = create_sqlite_backup(self.source, directory=self.root / "backups")
        second = create_sqlite_backup(self.source, directory=self.root / "backups")

        self.assertNotEqual(first.name, second.name)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o600)
        self.assertIn("proxies", validate_sqlite_database(first))
        self.assertIn("proxies", validate_sqlite_database(second))

    def test_atomic_restore_preserves_credentials_and_current_columns(self):
        backup = create_sqlite_backup(self.source, directory=self.root / "backups")
        destination = self.root / "restored.sqlite"
        staged = stage_sqlite_copy(backup, destination_directory=self.root)
        replace_sqlite_database(staged, destination)

        self.assertFalse(staged.exists())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        connection = sqlite3.connect(destination)
        try:
            row = connection.execute(
                "SELECT username, password, web_https_ok, remote_dns_ok, validation_summary "
                "FROM proxies"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[:4], ("private-user", "private-password", 1, 1))
        self.assertIn("release-test", row[4])

    def test_migration_is_dry_run_by_default_and_copies_current_columns(self):
        target = self.root / "target.sqlite"
        command = [
            sys.executable,
            str(ROOT / "migrate.py"),
            "--source",
            str(self.source),
            "--target-url",
            f"sqlite:///{target}",
        ]
        dry_run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("Dry-run only", dry_run.stdout)
        self.assertFalse(target.exists())

        execution = subprocess.run(
            [*command, "--execute"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(execution.returncode, 0, execution.stderr)
        payload_start = execution.stdout.find("{")
        payload_end = execution.stdout.rfind("}") + 1
        payload = json.loads(execution.stdout[payload_start:payload_end])
        self.assertEqual(payload["inserted_rows"], 1)
        self.assertIn("validation_summary", payload["copied_columns"])

        connection = sqlite3.connect(target)
        try:
            row = connection.execute(
                "SELECT username, password, web_https_ok, remote_dns_ok, validation_summary "
                "FROM proxies"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[:4], ("private-user", "private-password", 1, 1))
        self.assertIn("release-test", row[4])

    def test_migration_rejects_source_as_target(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "migrate.py"),
                "--source",
                str(self.source),
                "--target-url",
                f"sqlite:///{self.source}",
                "--execute",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("must be different", result.stderr)

    def test_replace_migration_requires_explicit_confirmation(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "migrate.py"),
                "--source",
                str(self.source),
                "--target-url",
                f"sqlite:///{self.root / 'target.sqlite'}",
                "--replace",
                "--execute",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--yes-replace", result.stderr)

    def test_release_assets_are_non_deploying_and_dev_tooling_is_explicit(self):
        release_script = (ROOT / "scripts" / "release_check.sh").read_text(encoding="utf-8")
        dev_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("scripts/health_check.sh", release_script)
        self.assertIn("scripts/repo_hygiene_check.sh", release_script)
        self.assertIn("scripts/sqlite_backup.py", release_script)
        self.assertNotIn("systemctl", release_script)
        self.assertNotIn("systemctl", release_script)
        self.assertNotIn("scp ", release_script)
        self.assertNotIn("ssh ", release_script)
        self.assertIn("ruff>=0.15,<0.16", dev_requirements)
        self.assertIn('target-version = "py311"', pyproject)

    def test_settings_backup_path_uses_private_helpers(self):
        source = (ROOT / "dashboard" / "routes" / "settings.py").read_text(encoding="utf-8")
        self.assertIn("create_sqlite_backup", source)
        self.assertIn("reserve_private_file", source)
        self.assertIn("stage_sqlite_copy", source)
        self.assertNotIn("f\"proxies_backup_{timestamp}", source)


if __name__ == "__main__":
    unittest.main()
