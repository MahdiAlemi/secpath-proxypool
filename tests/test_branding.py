from pathlib import Path
import unittest

class BrandingRegressionTest(unittest.TestCase):
    def test_dashboard_uses_secpath_product_name(self):
        for name in ("dashboard/templates/login.html", "dashboard/templates/main.html", "dashboard/static/js/shell.js"):
            self.assertIn("SecPath ProxyPool", Path(name).read_text(encoding="utf-8"))

    def test_readme_is_public_safe_and_uses_current_backup_cli(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        runbook = Path("RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("# SecPath ProxyPool", readme)
        self.assertIn("SecPath Proxy Lists", readme)
        self.assertIn("--source proxies.db", readme)
        self.assertIn("--directory backups", readme)
        self.assertNotIn("--database proxies.db", readme)
        self.assertNotIn("/home/mahdi/", readme + runbook)

    def test_public_site_uses_companion_brand(self):
        site = Path("public_monitor/site.py").read_text(encoding="utf-8")
        excel = Path("public_monitor/excel.py").read_text(encoding="utf-8")
        self.assertIn("SecPath Proxy Lists", site)
        self.assertIn("SecPath ProxyPool", site)
        self.assertIn("SecPath Proxy Lists", excel)
        workflow = Path(".github/workflows/public-proxy-monitor.yml").read_text(encoding="utf-8")
        self.assertIn("Build and publish SecPath Proxy Lists", workflow)

if __name__ == "__main__":
    unittest.main()
