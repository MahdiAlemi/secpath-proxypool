# Phase 10 – Lightweight Regression Tests

Adds a small stdlib `unittest` suite and a repeatable test runner.

## Added

- `tests/test_validation.py`
  - IP detection
  - protocol candidate ordering (`socks5h`, `socks4a`, HTTPS fallback)
  - proxy URL formatting
  - simulated `validate_proxy()` success/fallback paths without network access
- `tests/test_importer_normalization.py`
  - URL-format proxy import with username/password preservation
  - `host:port:user:pass` parsing
  - invalid port rejection
- `tests/test_config_defaults.py`
  - local default database is SQLite
- `scripts/test.sh`
  - runs all tests with `python3 -m unittest discover`
- `scripts/health_check.sh`
  - now runs the test suite when `tests/` exists

No runtime behavior changes.
