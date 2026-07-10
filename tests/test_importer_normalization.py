import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORTER_PATH = ROOT / 'proxy_importer' / 'utils' / 'importer.py'


def load_importer_with_stubs():
    old_database = sys.modules.get('database')
    old_requests = sys.modules.get('requests')
    sys.modules['database'] = types.SimpleNamespace(
        init_db=lambda: None,
        insert_proxy=lambda *a, **k: True,
        get_proxy_count=lambda: 0,
    )
    sys.modules['requests'] = types.SimpleNamespace(get=lambda *a, **k: None)
    try:
        spec = importlib.util.spec_from_file_location('importer_under_test', IMPORTER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old_database is None:
            sys.modules.pop('database', None)
        else:
            sys.modules['database'] = old_database
        if old_requests is None:
            sys.modules.pop('requests', None)
        else:
            sys.modules['requests'] = old_requests


class ImporterNormalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.importer = load_importer_with_stubs()

    def test_url_format_preserves_auth(self):
        result = self.importer.normalize_proxy_line('socks5://user:pass@10.0.0.1:1080', 'http')
        self.assertEqual(result, ('socks5', '10.0.0.1', 1080, 'user', 'pass'))

    def test_host_port_user_pass_format(self):
        result = self.importer.normalize_proxy_line('10.0.0.2:8080:alice:secret', 'http')
        self.assertEqual(result, ('http', '10.0.0.2', 8080, 'alice', 'secret'))

    def test_plain_host_port_uses_default_protocol(self):
        result = self.importer.normalize_proxy_line('10.0.0.3:3128', 'https')
        self.assertEqual(result, ('https', '10.0.0.3', 3128, None, None))

    def test_invalid_port_is_rejected(self):
        self.assertIsNone(self.importer.normalize_proxy_line('10.0.0.4:notaport', 'http'))

    def test_ui_manual_protocol_host_port_format(self):
        result = self.importer.normalize_proxy_line('http 192.168.1.1:8080', 'socks5')
        self.assertEqual(result, ('http', '192.168.1.1', 8080, None, None))

    def test_ui_manual_auth_format(self):
        result = self.importer.normalize_proxy_line('socks5 10.0.0.1:1080 user pass', 'http')
        self.assertEqual(result, ('socks5', '10.0.0.1', 1080, 'user', 'pass'))

    def test_separate_host_port_format(self):
        result = self.importer.normalize_proxy_line('https proxy.example 8443 alice secret', 'http')
        self.assertEqual(result, ('https', 'proxy.example', 8443, 'alice', 'secret'))

    def test_bracketed_ipv6_format(self):
        result = self.importer.normalize_proxy_line('[2001:db8::1]:8080', 'http')
        self.assertEqual(result, ('http', '2001:db8::1', 8080, None, None))


if __name__ == '__main__':
    unittest.main()
