import unittest

from config import config


class ConfigDefaultsTest(unittest.TestCase):
    def test_local_default_is_sqlite(self):
        self.assertEqual(config.DB_TYPE.lower(), 'sqlite')
        self.assertTrue(config.get_database_url().startswith('sqlite:///'))

    def test_explicit_database_url_takes_precedence(self):
        config_type = type(config)
        previous = config_type.DATABASE_URL
        try:
            config_type.DATABASE_URL = 'sqlite:////tmp/proxypool-explicit.sqlite'
            self.assertEqual(config.get_database_url(), 'sqlite:////tmp/proxypool-explicit.sqlite')
        finally:
            config_type.DATABASE_URL = previous




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
                self.assertIn(b'Know what is ready before you route traffic.', res.data)
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
                self.assertIn(b'Know what is ready before you route traffic.', res.data)
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
                self.assertIn(b'inventory-metrics', res.data)
                self.assertIn(b'inventory-empty-state', res.data)
                self.assertIn(b'Inspect the proxies that can actually carry traffic.', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class MonitorRenderTest(unittest.TestCase):
    def test_monitor_center_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=monitor')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'validation-workspace', res.data)
                self.assertIn(b'Validation workspace', res.data)
                self.assertIn(b'validation-profile-list', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class ImportRenderTest(unittest.TestCase):
    def test_import_source_center_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=import')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'source-workbench', res.data)
                self.assertIn(b'Build the pool from trusted inputs.', res.data)
                self.assertIn(b'source-manual-content', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class StatsRenderTest(unittest.TestCase):
    def test_stats_insights_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=stats')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'insights-kpi-grid', res.data)
                self.assertIn(b'Pool quality at a glance', res.data)
                self.assertIn(b'insights-health-bars', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class SettingsRenderTest(unittest.TestCase):
    def test_operations_center_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=operations')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'Operations and maintenance', res.data)
                self.assertIn(b'operations-summary-grid', res.data)
                self.assertIn(b'operations-danger-zone', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class AccessRenderTest(unittest.TestCase):
    def test_access_control_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=users')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'Access control', res.data)
                self.assertIn(b'access-user-list', res.data)
                self.assertIn(b'access-detail-card', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


class ServerRenderTest(unittest.TestCase):
    def test_serving_center_shell_renders(self):
        from dashboard import create_app
        from database import db
        app = create_app()
        app.config['TESTING'] = True
        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['user'] = 'admin'
                    sess['user_id'] = 0
                res = client.get('/index?tab=server')
                self.assertEqual(res.status_code, 200)
                self.assertIn(b'Serving Center', res.data)
                self.assertIn(b'serving-workspace', res.data)
                self.assertIn(b'serving-profile-list', res.data)
                self.assertIn(b'serving-detail-panel', res.data)
        finally:
            if getattr(db, 'Session', None) is not None:
                db.Session.remove()
            if getattr(db, 'engine', None) is not None:
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
