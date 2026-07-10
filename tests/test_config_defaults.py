import unittest

from config import config


class ConfigDefaultsTest(unittest.TestCase):
    def test_local_default_is_sqlite(self):
        self.assertEqual(config.DB_TYPE.lower(), 'sqlite')
        self.assertTrue(config.get_database_url().startswith('sqlite:///'))


if __name__ == '__main__':
    unittest.main()
