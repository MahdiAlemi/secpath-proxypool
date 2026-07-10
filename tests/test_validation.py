import unittest

from proxy_monitor.utils import validation


class ValidationHelpersTest(unittest.TestCase):
    def test_is_ip(self):
        self.assertTrue(validation.is_ip('1.1.1.1'))
        self.assertTrue(validation.is_ip('2001:4860:4860::8888'))
        self.assertFalse(validation.is_ip('example.com'))
        self.assertFalse(validation.is_ip(''))

    def test_protocol_candidates_order(self):
        self.assertEqual(validation.protocol_candidates('socks5')[0]['scheme'], 'socks5h')
        self.assertTrue(validation.protocol_candidates('socks5')[0]['remote_dns'])
        self.assertEqual(validation.protocol_candidates('socks4')[0]['scheme'], 'socks4a')
        self.assertEqual(validation.protocol_candidates('https')[0]['scheme'], 'https')
        self.assertEqual(validation.protocol_candidates('https')[1]['scheme'], 'http')
        self.assertTrue(validation.protocol_candidates('https')[1]['https_label_fallback'])
        self.assertEqual(validation.protocol_candidates('http'), [{'scheme': 'http', 'remote_dns': True}])

    def test_proxy_url_with_and_without_auth(self):
        self.assertEqual(validation.proxy_url('http', '127.0.0.1', 8080), 'http://127.0.0.1:8080')
        self.assertEqual(validation.proxy_url('socks5h', '1.2.3.4', 1080, 'u', 'p'), 'socks5h://u:p@1.2.3.4:1080')


class ValidateProxySimulationTest(unittest.TestCase):
    def setUp(self):
        self.old_curl_text = validation.curl_text
        self.old_curl_status = validation.curl_status

    def tearDown(self):
        validation.curl_text = self.old_curl_text
        validation.curl_status = self.old_curl_status

    def test_socks5h_success_sets_remote_dns_and_telegram(self):
        def fake_curl_text(proxy, url, timeout, proxy_insecure=False):
            if url == validation.IPIFY_HTTPS:
                self.assertTrue(proxy.startswith('socks5h://'))
                return True, '8.8.8.8', 123, ''
            if url == validation.IPIFY_HTTP:
                return True, '8.8.8.8', 80, ''
            raise AssertionError(url)

        def fake_curl_status(proxy, url, timeout, proxy_insecure=False):
            self.assertEqual(url, validation.TELEGRAM_URL)
            return True, '200', 50, ''

        validation.curl_text = fake_curl_text
        validation.curl_status = fake_curl_status
        summary = validation.validate_proxy({'protocol': 'socks5', 'ip': '1.2.3.4', 'port': 1080}, timeout=1, telegram=True)

        self.assertTrue(summary['ok'])
        self.assertTrue(summary['web_https_ok'])
        self.assertTrue(summary['web_http_ok'])
        self.assertTrue(summary['remote_dns_ok'])
        self.assertTrue(summary['telegram_ok'])
        self.assertEqual(summary['proxy_url_scheme'], 'socks5h')
        self.assertEqual(summary['exit_ip'], '8.8.8.8')

    def test_https_label_fallback_marks_http_connect_fallback(self):
        calls = []

        def fake_curl_text(proxy, url, timeout, proxy_insecure=False):
            calls.append((proxy, url, proxy_insecure))
            if url == validation.IPIFY_HTTPS and proxy.startswith('https://'):
                return False, '', 10, 'tls proxy failed'
            if url == validation.IPIFY_HTTPS and proxy.startswith('http://'):
                return True, '9.9.9.9', 111, ''
            if url == validation.IPIFY_HTTP:
                return True, '9.9.9.9', 90, ''
            raise AssertionError(url)

        validation.curl_text = fake_curl_text
        validation.curl_status = lambda *a, **k: (False, '000', 0, 'skipped')
        summary = validation.validate_proxy({'protocol': 'https', 'ip': '5.6.7.8', 'port': 3128}, timeout=1, telegram=False)

        self.assertTrue(summary['ok'])
        self.assertEqual(summary['proxy_url_scheme'], 'http')
        self.assertTrue(summary['http_connect_fallback_ok'])
        self.assertFalse(summary['proxy_tls_ok'])
        self.assertGreaterEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
