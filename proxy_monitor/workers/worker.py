import queue
import random
import time

from proxy_monitor import config as pm_config
from proxy_monitor.utils.logging import log, STOP
from proxy_monitor.utils.validation import validate_proxy
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
        
        try:
            capability = validate_proxy(job, timeout=pm_config.TIMEOUT, telegram=True)
            ok = bool(capability.get("ok"))
            elapsed_ms = capability.get("speed_ms") or 0
            
            from database import Proxy
            from database import db
            with db.session() as session:
                proxy = session.query(Proxy).filter_by(id=job["id"]).first()
                if proxy:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc)
                    proxy.web_http_ok = bool(capability.get("web_http_ok"))
                    proxy.web_https_ok = bool(capability.get("web_https_ok"))
                    proxy.remote_dns_ok = bool(capability.get("remote_dns_ok"))
                    proxy.telegram_ok = bool(capability.get("telegram_ok"))
                    proxy.exit_ip = capability.get("exit_ip")
                    proxy.validation_profile = "telegram" if proxy.telegram_ok else ("web" if proxy.web_https_ok else "basic")
                    proxy.validation_summary = capability
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
