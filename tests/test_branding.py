from pathlib import Path
import unittest

from secpath_meta import DEVELOPER_CREDIT, PRODUCT_NAME, PUBLIC_SITE_NAME, VERSION_LABEL


class BrandingRegressionTest(unittest.TestCase):
    def test_central_product_metadata_is_release_v1(self):
        self.assertEqual(PRODUCT_NAME, "SecPath ProxyPool")
        self.assertEqual(PUBLIC_SITE_NAME, "SecPath Proxy Lists")
        self.assertEqual(VERSION_LABEL, "v1.0.0")
        self.assertEqual(DEVELOPER_CREDIT, "Developed by Mahdi Alemi")

    def test_dashboard_uses_central_version_and_developer_footer(self):
        init = Path("dashboard/__init__.py").read_text(encoding="utf-8")
        login = Path("dashboard/templates/login.html").read_text(encoding="utf-8")
        main = Path("dashboard/templates/main.html").read_text(encoding="utf-8")
        self.assertIn("inject_product_metadata", init)
        self.assertIn("product_version", login)
        self.assertIn("developer_credit", login)
        self.assertIn('class="app-footer"', main)
        self.assertIn("product_version", main)
        self.assertIn("developer_credit", main)

    def test_readme_is_public_safe_versioned_and_uses_current_backup_cli(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        runbook = Path("RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("# SecPath ProxyPool", readme)
        self.assertIn("version-v1.0.0", readme)
        self.assertIn("Developed by **Mahdi Alemi**", readme)
        self.assertIn("SecPath Proxy Lists", readme)
        self.assertIn("--source proxies.db", readme)
        self.assertIn("--directory backups", readme)
        self.assertNotIn("--database proxies.db", readme)
        self.assertNotIn("/home/mahdi/", readme + runbook)

    def test_public_site_and_excel_use_central_metadata(self):
        site = Path("public_monitor/site.py").read_text(encoding="utf-8")
        excel = Path("public_monitor/excel.py").read_text(encoding="utf-8")
        for token in ("VERSION_LABEL", "DEVELOPER_CREDIT", "PRODUCT_NAME", "PUBLIC_SITE_NAME"):
            self.assertIn(token, site)
            self.assertIn(token, excel)

    def test_hygiene_ignores_local_virtual_environment(self):
        hygiene = Path("scripts/repo_hygiene_check.sh").read_text(encoding="utf-8")
        self.assertIn("--exclude-dir=.venv", hygiene)
        self.assertIn("--exclude-dir=.ruff_cache", hygiene)


if __name__ == "__main__":
    unittest.main()
