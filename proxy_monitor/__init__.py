"""Proxy monitor package.

Keep package import lightweight. Importing proxy_monitor.app pulls in the DB and
SQLAlchemy; utility modules such as validation should be importable without that.
"""

ARGS = None


def main(*args, **kwargs):
    from proxy_monitor.app import main as _main
    return _main(*args, **kwargs)

__all__ = ["main", "ARGS"]
