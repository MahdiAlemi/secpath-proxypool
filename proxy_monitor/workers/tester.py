import random
import subprocess
import time
import queue

from proxy_monitor import config as pm_config
from proxy_monitor.utils.network import build_curl_args
from proxy_monitor.utils.logging import log, STOP


result_q = queue.Queue()


def test_proxy(row):
    pid = row["id"]
    proto, host, port, user, pwd = row["protocol"], row["ip"], row["port"], row["username"], row["password"]
    if STOP:
        return

    successes = 0
    speeds = []

    for attempt in range(pm_config.PROBES_PER_PROXY):
        url = pm_config.CHECK_URLS[attempt % len(pm_config.CHECK_URLS)]
        start = time.time()
        ok = True
        try:
            args = build_curl_args(proto, user, pwd, host, port, url, pm_config.TIMEOUT)
            out = subprocess.check_output(
                args,
                stderr=subprocess.DEVNULL,
                timeout=pm_config.TIMEOUT + 2
            )
            if not out.strip():
                ok = False
        except Exception:
            ok = False

        if ok:
            successes += 1
            speeds.append(int((time.time() - start) * 1000))
        if attempt != pm_config.PROBES_PER_PROXY - 1:
            time.sleep(random.uniform(pm_config.PROBE_JITTER[0], pm_config.PROBE_JITTER[1]))

    result_q.put((pid, proto, host, port, successes, speeds))
