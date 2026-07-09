# Phase 4 runtime fix

Fixes:
- HTTP proxy listener no longer enables TLS automatically. This fixes `curl -x http://127.0.0.1:<port> https://...` failing with SSL record-layer errors / connection reset.
- Dashboard process status now treats zombie/defunct monitor/server processes as not running.

Apply:
```bash
unzip -o /mnt/c/Users/Mahdi/Downloads/overlay_phase4_runtime_fix.zip -d .
```
