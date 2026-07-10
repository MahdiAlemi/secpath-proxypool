import queue
import random

from proxy_monitor import config as pm_config
from proxy_monitor.utils.validation import validate_proxy
from proxy_monitor.utils.logging import STOP


# Backward-compatible default queue. New monitor runs pass an isolated queue so
# stale sentinels/results from a previous run cannot corrupt the next session.
result_q = queue.Queue()


def test_proxy(row, results=None):
    target_q = results or result_q
    pid = row["id"]
    proto = row["protocol"]
    host = row["ip"]
    port = row["port"]
    if STOP:
        return

    successes = 0
    speeds = []
    capability_history = []

    for attempt in range(pm_config.PROBES_PER_PROXY):
        if STOP:
            break
        try:
            capability = validate_proxy(row, timeout=pm_config.TIMEOUT, telegram=True)
            ok = bool(capability.get("ok"))
        except Exception as exc:
            capability = {"ok": False, "errors": [{"error": str(exc)[:300]}]}
            ok = False
        capability_history.append(capability)

        if ok:
            successes += 1
            if capability.get("speed_ms"):
                speeds.append(int(capability["speed_ms"]))
        if attempt != pm_config.PROBES_PER_PROXY - 1 and not STOP:
            delay = random.uniform(pm_config.PROBE_JITTER[0], pm_config.PROBE_JITTER[1])
            STOP.wait(delay)

    # An interrupted proxy is left untested so pause/resume can retry it as a
    # complete unit. Partial probes must never be converted into synthetic
    # failures.
    if not capability_history or (STOP and len(capability_history) < pm_config.PROBES_PER_PROXY):
        return

    aggregate = dict(capability_history[-1])
    aggregate["probe_history"] = capability_history[-3:]
    aggregate["web_https_ok"] = successes == len(capability_history) == pm_config.PROBES_PER_PROXY
    aggregate["web_http_ok"] = any(c.get("web_http_ok") for c in capability_history)
    aggregate["remote_dns_ok"] = any(c.get("remote_dns_ok") for c in capability_history)
    aggregate["telegram_ok"] = any(c.get("telegram_ok") for c in capability_history)
    aggregate["exit_ip"] = next((c.get("exit_ip") for c in capability_history if c.get("exit_ip")), None)
    aggregate["attempted_probes"] = len(capability_history)
    aggregate["interrupted"] = bool(STOP) and len(capability_history) < pm_config.PROBES_PER_PROXY
    target_q.put((pid, proto, host, port, successes, speeds, aggregate))
