import subprocess
import time

from datetime import datetime, timezone

from database import Proxy, db
from proxy_monitor.config import CHECK_URLS
from proxy_monitor.utils.network import build_curl_args
from proxy_monitor.utils.cost import compute_cost


def quick_probe(proxy_row, check_url="https://ident.me", timeout=3):
    proto = proxy_row["protocol"]
    host = proxy_row["ip"]
    port = proxy_row["port"]
    user = proxy_row.get("username")
    pwd = proxy_row.get("password")

    start = time.perf_counter()
    try:
        args = build_curl_args(proto, user, pwd, host, port, check_url, timeout)
        res = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ok = bool(res.stdout and res.stdout.strip())
        return ok, (elapsed_ms if ok else None)
    except Exception:
        return False, None


def select_working_proxy(top_n=12, probe_timeout=2):
    check_url = CHECK_URLS[0]

    with db.session() as session:
        candidates = session.query(Proxy).filter(
            Proxy.ip.isnot(None)
        ).order_by(Proxy.cost.asc()).limit(top_n).all()

        if not candidates:
            return None

        for proxy in candidates:
            row = proxy.to_dict()
            ok, speed = quick_probe(row, check_url=check_url, timeout=probe_timeout)
            now = datetime.now(timezone.utc)

            if ok:
                proxy.alive_hits = (proxy.alive_hits or 0) + 1
                proxy.last_alive = now
                proxy.speed_ms = speed
                session.commit()
                return row
            else:
                proxy.fail_hits = (proxy.fail_hits or 0) + 1
                proxy.last_fail = now
                proxy.consecutive_fails = (proxy.consecutive_fails or 0) + 1
                proxy.status = 'dead'
                proxy.previous_cost = proxy.cost
                proxy.cost, proxy.is_cooling, proxy.latency_score, proxy.reliability, proxy.jitter_score, proxy.recency_score, proxy.previous_cost = compute_cost(
                    proxy.alive_hits, proxy.fail_hits,
                    proxy.speed_ms, proxy.speed_history,
                    proxy.last_alive, proxy.last_fail,
                    proxy.consecutive_fails or 0,
                    'dead',
                    proxy.previous_cost
                )
                session.commit()

    return None
