import unittest

from config import config


class ConfigDefaultsTest(unittest.TestCase):
    def test_local_default_is_sqlite(self):
        self.assertEqual(config.DB_TYPE.lower(), 'sqlite')
        self.assertTrue(config.get_database_url().startswith('sqlite:///'))




class DiagnosticsEndpointTest(unittest.TestCase):
    def test_diagnostics_endpoint_shape(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
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
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class ServerPreviewEndpointTest(unittest.TestCase):
    def test_server_preview_candidates_endpoint_shape(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.post('/api/server/preview-candidates', json={'candidate_statuses': 'alive', 'require_web_https': True})
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                self.assertTrue(data['success'])
                self.assertIn('total', data)
                self.assertIn('by_protocol', data)
                self.assertIn('warnings', data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class CockpitRenderTest(unittest.TestCase):
    def test_cockpit_route_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=cockpit')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'tab-cockpit', res.data)
                self.assertIn(b'ProxyPool readiness overview', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class DefaultLandingTest(unittest.TestCase):
    def test_default_route_lands_on_cockpit(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'tab-cockpit', res.data)
                self.assertIn(b'ProxyPool readiness overview', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class InventoryRenderTest(unittest.TestCase):
    def test_inventory_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=proxies')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'inventory-overview', res.data)
                self.assertIn(b'inventory-empty-state', res.data)
                self.assertIn(b'Proxy Inventory', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
