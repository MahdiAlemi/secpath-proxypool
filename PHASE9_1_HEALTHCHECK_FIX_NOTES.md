# Phase 9.1 – Health Check Smoke Test Fix

Fixes the Phase 9 `scripts/health_check.sh` validation-helper smoke test.

The script incorrectly expected `protocol_candidates('socks5')[0]` to return a tuple.
The real Phase 8A validation helper returns dictionaries like:

```python
{"scheme": "socks5h", "remote_dns": True}
```

Runtime code was correct; only the health-check assertion was too strict/wrong.
