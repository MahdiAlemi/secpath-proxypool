#!/usr/bin/env python3
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy_monitor.config import parse_args, DEFAULT_RUN_MODE, DEFAULT_INTERVAL
from proxy_monitor.utils import init_signals, log, STOP
from proxy_monitor.monitor import run_monitor
from sqlalchemy import or_


ARGS = None


def main():
    global ARGS
    ARGS = parse_args()
    import proxy_monitor.config as pm_config
    pm_config.THREADS = ARGS.threads
    pm_config.TIMEOUT = ARGS.timeout
    pm_config.PROBES_PER_PROXY = ARGS.probes
    if ARGS.check_urls:
        pm_config.CHECK_URLS = [u.strip() for u in ARGS.check_urls.split(",") if u.strip()]
    
    init_signals()
    
    log("[*] Initializing database...")
    from database import init_db
    init_db()
    log("[+] Database initialized")
    
    run_mode = ARGS.run_mode if ARGS else DEFAULT_RUN_MODE
    interval = ARGS.interval if ARGS else DEFAULT_INTERVAL
    
    if run_mode == "once":
        log("[+] Running once...")
        run_monitor(ARGS)
    
    elif run_mode == "infinite":
        log("[+] Running in infinite mode...")
        from proxy_monitor.workers import worker_infinite
        from sqlalchemy import or_
        import queue
        import threading
        import time
        
        while not STOP:
            from database import db, Proxy
            with db.session() as session:
                query = session.query(Proxy.id, Proxy.protocol, Proxy.ip, 
                                      Proxy.port, Proxy.username, Proxy.password)
                
                if ARGS and ARGS.protocol:
                    protocols = [p.strip() for p in ARGS.protocol.split(",") if p.strip()]
                    if protocols:
                        query = query.filter(Proxy.protocol.in_(protocols))
                
                if ARGS and ARGS.status:
                    statuses = [s.strip() for s in ARGS.status.split(",") if s.strip()]
                    if statuses:
                        status_conditions = []
                        for s in statuses:
                            if s == "untested":
                                status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                            else:
                                status_conditions.append(Proxy.status == s)
                        if status_conditions:
                            query = query.filter(or_(*status_conditions))
                
                proxies = query.all()
            
            if not proxies:
                log("[!] No proxies found")
                time.sleep(interval)
                continue
            
            log("[+] Starting infinite run with {} proxies", len(proxies))
            import random
            random.shuffle(proxies)
            proxy_queue = queue.Queue()
            for p in proxies:
                proxy_queue.put({
                    "id": p.id, "protocol": p.protocol, "ip": p.ip, "port": p.port,
                    "username": p.username, "password": p.password
                })
            
            for _ in range(ARGS.threads):
                threading.Thread(target=worker_infinite, args=(proxy_queue,), daemon=True).start()
            
            log("[+] Waiting {} seconds until next run...", interval)
            time.sleep(interval)
    
    elif run_mode == "restart":
        log("[+] Running in restart mode...")
        while not STOP:
            run_monitor(ARGS)
            log("[+] Run complete. Waiting {} seconds...", interval)
            import time
            time.sleep(interval)
    
    elif run_mode == "schedule":
        log("[+] Running in schedule mode...")
        import time
        schedule_time = ARGS.schedule_time if ARGS and ARGS.schedule_time else "00:00"
        schedule_days = ARGS.schedule_days if ARGS and ARGS.schedule_days else "daily"
        
        hour, minute = map(int, schedule_time.split(":"))
        log("[+] Scheduled to run at {} on {}", schedule_time, schedule_days)
        
        while not STOP:
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if target <= now:
                target = target + datetime.timedelta(days=1)
            
            wait_seconds = (target - now).total_seconds()
            log("[+] Next run in {:.0f} seconds (at {})", wait_seconds, target)
            
            while wait_seconds > 0 and not STOP:
                time.sleep(min(60, wait_seconds))
                wait_seconds -= 60
            
            if not STOP:
                log("[+] Starting scheduled run...")
                run_monitor(ARGS)
    
    elif run_mode == "custom":
        log("[+] Running in custom mode...")
        import time
        custom_hours = ARGS.custom_every if ARGS and ARGS.custom_every else 24
        custom_interval = custom_hours * 3600
        
        log("[+] Running every {} hours", custom_hours)
        
        while not STOP:
            run_monitor(ARGS)
            log("[+] Run complete. Waiting {} hours...", custom_hours)
            elapsed = 0
            while elapsed < custom_interval and not STOP:
                time.sleep(min(60, custom_interval - elapsed))
                elapsed += 60
    
    else:
        log("[!] Unsupported run mode: {}", run_mode)


if __name__ == "__main__":
    main()
