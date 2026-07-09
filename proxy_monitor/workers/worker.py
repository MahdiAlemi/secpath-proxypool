import queue
import random
import time
import subprocess

from proxy_monitor import config as pm_config
from proxy_monitor.utils.logging import log, STOP
from proxy_monitor.utils.network import build_curl_args
from proxy_monitor.workers.tester import test_proxy, result_q


def worker(jobs):
    while not STOP:
        try:
            job = jobs.get(timeout=0.5)
        except queue.Empty:
            return
        test_proxy(job)
        jobs.task_done()


def worker_infinite(jobs):
    while not STOP:
        try:
            job = jobs.get(timeout=0.5)
        except queue.Empty:
            return
        
        proto = job.get("protocol")
        ip = job.get("ip")
        port = job.get("port")
        user = job.get("username")
        pwd = job.get("password")
        
        url = random.choice(pm_config.CHECK_URLS)
        start = time.perf_counter()
        try:
            args = build_curl_args(proto, user, pwd, ip, port, url, pm_config.TIMEOUT)
            res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=pm_config.TIMEOUT+1, check=False)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            ok = bool(res.stdout and res.stdout.strip())
            
            from database import Proxy
            from database import db
            with db.session() as session:
                proxy = session.query(Proxy).filter_by(id=job["id"]).first()
                if proxy:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    if ok:
                        proxy.alive_hits = (proxy.alive_hits or 0) + 1
                        proxy.last_alive = now
                        proxy.speed_ms = elapsed_ms
                    else:
                        proxy.fail_hits = (proxy.fail_hits or 0) + 1
                        proxy.last_fail = now
                    session.commit()
        except Exception as e:
            log("[!] Worker infinite error: {}", e)
        
        jobs.task_done()
