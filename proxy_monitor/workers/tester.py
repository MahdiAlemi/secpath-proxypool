import random
import time
import queue

from proxy_monitor import config as pm_config
from proxy_monitor.utils.validation import validate_proxy
from proxy_monitor.utils.logging import log, STOP


result_q = queue.Queue()


def test_proxy(row):
    pid = row["id"]
    proto, host, port, user, pwd = row["protocol"], row["ip"], row["port"], row["username"], row["password"]
    if STOP:
        return

    successes = 0
    speeds = []

    capability_history = []
    for attempt in range(pm_config.PROBES_PER_PROXY):
        try:
            capability = validate_proxy(row, timeout=pm_config.TIMEOUT, telegram=True)
            ok = bool(capability.get("ok"))
        except Exception as e:
            capability = {"ok": False, "errors": [{"error": str(e)[:300]}]}
            ok = False
        capability_history.append(capability)

        if ok:
            successes += 1
            if capability.get("speed_ms"):
                speeds.append(int(capability["speed_ms"]))
        if attempt != pm_config.PROBES_PER_PROXY - 1:
            time.sleep(random.uniform(pm_config.PROBE_JITTER[0], pm_config.PROBE_JITTER[1]))

    aggregate = capability_history[-1] if capability_history else {"ok": False}
    aggregate = dict(aggregate)
    aggregate["probe_history"] = capability_history[-3:]
    aggregate["web_https_ok"] = successes == pm_config.PROBES_PER_PROXY
    aggregate["web_http_ok"] = any(c.get("web_http_ok") for c in capability_history)
    aggregate["remote_dns_ok"] = any(c.get("remote_dns_ok") for c in capability_history)
    aggregate["telegram_ok"] = any(c.get("telegram_ok") for c in capability_history)
    aggregate["exit_ip"] = next((c.get("exit_ip") for c in capability_history if c.get("exit_ip")), None)
    result_q.put((pid, proto, host, port, successes, speeds, aggregate))
