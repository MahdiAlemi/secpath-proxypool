import unittest

from config import config


class ConfigDefaultsTest(unittest.TestCase):
    def test_local_default_is_sqlite(self):
        self.assertEqual(config.DB_TYPE.lower(), 'sqlite')
        self.assertTrue(config.get_database_url().startswith('sqlite:///'))




class DiagnosticsEndpointTest(unittest.TestCase):
    def test_diagnostics_endpoint_shape(self):
        from dashboard import create_app
        app = create_app()
        app.config['TESTING'] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = 'admin'
                sess['user_id'] = 0
            res = client.get('/api/settings/diagnostics')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['success'])
            self.assertIn('db', data)
            self.assertIn('counts', data)
            self.assertIn('runtime', data)
            self.assertIn('recommendations', data)
            self.assertIn('web_ready', data['counts'])


if __name__ == '__main__':
    unittest.main()
