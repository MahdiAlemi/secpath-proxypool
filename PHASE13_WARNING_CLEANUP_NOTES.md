# Phase 13 – Warning Cleanup

Cleans warnings observed after Phase 12 tests.

## Fixed

- SQLAlchemy 2.x deprecation warning:
  - `declarative_base` now imports from `sqlalchemy.orm`.
- Python 3.14 `datetime.utcnow()` deprecation warning in dashboard auth token cleanup:
  - added `utcnow()` helper using `datetime.now(timezone.utc).replace(tzinfo=None)`.
  - keeps existing DB columns compatible with naive UTC datetimes.
- Database model defaults now use the same Python 3.14-safe `utcnow()` helper.
- Diagnostics endpoint test now explicitly removes scoped sessions and disposes the SQLAlchemy engine to avoid SQLite `ResourceWarning` on process exit.

No schema changes and no runtime behavior change beyond warning cleanup.
