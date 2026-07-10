import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


class _HtmlDocument(HTMLParser):
    """Small dependency-free HTML index for structural UI regression tests."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.feed(html.decode("utf-8") if isinstance(html, bytes) else html)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag.lower(), dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    @staticmethod
    def _classes(attrs):
        return set((attrs.get("class") or "").split())

    def find(self, *, tag=None, element_id=None, classes=(), attrs=None):
        matches = self.find_all(
            tag=tag,
            element_id=element_id,
            classes=classes,
            attrs=attrs,
        )
        return matches[0] if matches else None

    def find_all(self, *, tag=None, element_id=None, classes=(), attrs=None):
        required_classes = set(classes)
        required_attrs = attrs or {}
        matches = []

        for element_tag, element_attrs in self.elements:
            if tag and element_tag != tag:
                continue
            if element_id and element_attrs.get("id") != element_id:
                continue
            if not required_classes.issubset(self._classes(element_attrs)):
                continue
            if any(element_attrs.get(key) != value for key, value in required_attrs.items()):
                continue
            matches.append(element_attrs)

        return matches


class UIFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dashboard import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        from database import db

        if getattr(db, "Session", None) is not None:
            db.Session.remove()
        if getattr(db, "engine", None) is not None:
            db.engine.dispose()

    def get_dashboard(self, tab="cockpit"):
        with self.app.test_client() as client:
            with client.session_transaction() as session:
                session["user"] = "admin"
                session["user_id"] = 0
            return client.get(f"/index?tab={tab}")

    def test_dashboard_uses_new_application_shell(self):
        response = self.get_dashboard()
        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)

        self.assertIsNotNone(
            document.find(tag="aside", element_id="app-sidebar", classes=("sidebar",))
        )
        self.assertIsNotNone(document.find(tag="header", classes=("topbar",)))
        self.assertIsNotNone(
            document.find(tag="main", element_id="main-content", classes=("workspace",))
        )

        active_navigation = document.find_all(classes=("nav-btn", "active"))
        self.assertEqual(len(active_navigation), 1)
        self.assertEqual(active_navigation[0].get("data-tab"), "cockpit")

    def test_ui_assets_and_template_modules_are_present(self):
        response = self.get_dashboard("proxies")
        document = _HtmlDocument(response.data)

        styles = {
            attrs.get("href")
            for attrs in document.find_all(tag="link")
            if "stylesheet" in (attrs.get("rel") or "").split()
        }
        scripts = {
            attrs.get("src")
            for attrs in document.find_all(tag="script")
            if attrs.get("src")
        }

        self.assertIn("/static/css/tokens.css", styles)
        self.assertIn("/static/css/shell.css", styles)
        self.assertIn("/static/css/pages.css", styles)
        self.assertIn("/static/js/shell.js", scripts)

        proxy_tab = document.find(element_id="tab-proxies")
        cockpit_tab = document.find(element_id="tab-cockpit")
        self.assertIsNotNone(proxy_tab)
        self.assertIsNotNone(cockpit_tab)
        self.assertNotIn("hidden", _HtmlDocument._classes(proxy_tab))
        self.assertIn("hidden", _HtmlDocument._classes(cockpit_tab))

    def test_rendered_dashboard_has_unique_ids(self):
        response = self.get_dashboard()
        document = _HtmlDocument(response.data)
        ids = [attrs["id"] for _, attrs in document.elements if attrs.get("id")]
        duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
        self.assertEqual(duplicates, [])

    def test_invalid_tab_falls_back_to_cockpit(self):
        response = self.get_dashboard("../../settings")
        document = _HtmlDocument(response.data)

        cockpit_tab = document.find(element_id="tab-cockpit")
        active_navigation = document.find(classes=("nav-btn", "active"))
        self.assertIsNotNone(cockpit_tab)
        self.assertIsNotNone(active_navigation)
        self.assertNotIn("hidden", _HtmlDocument._classes(cockpit_tab))
        self.assertEqual(active_navigation.get("data-tab"), "cockpit")

    def test_login_page_uses_accessible_redesign(self):
        with self.app.test_client() as client:
            response = client.get("/login")

        self.assertEqual(response.status_code, 200)
        document = _HtmlDocument(response.data)
        self.assertIsNotNone(document.find(tag="main", classes=("login-shell",)))
        self.assertIsNotNone(
            document.find(tag="label", attrs={"for": "login-username"})
        )
        self.assertIsNotNone(
            document.find(tag="label", attrs={"for": "login-password"})
        )
        self.assertIsNotNone(
            document.find(tag="input", attrs={"autocomplete": "current-password"})
        )

    def test_main_template_is_composed_from_page_partials(self):
        template_root = Path(__file__).resolve().parents[1] / "dashboard" / "templates"
        main = (template_root / "main.html").read_text(encoding="utf-8")
        self.assertLess(len(main.splitlines()), 140)
        for page in ("cockpit", "inventory", "import", "monitor", "server", "stats"):
            self.assertIn(f"pages/{page}.html", main)
            self.assertTrue((template_root / "pages" / f"{page}.html").is_file())


if __name__ == "__main__":
    unittest.main()
