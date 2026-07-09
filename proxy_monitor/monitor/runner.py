import json
import os
import queue
import random
import threading
import time

from datetime import datetime, timezone
from sqlalchemy import or_

from database import Proxy, db, MonitorSession, MonitorTested
from proxy_monitor import config as pm_config
SHUFFLE_BIAS = pm_config.SHUFFLE_BIAS
SPEED_THRESHOLD_MS = pm_config.SPEED_THRESHOLD_MS
from proxy_monitor.utils import (
    log, STOP,
    runtime_health_rank, weighted_shuffle,
    geo_expired, resolve_host, fetch_geo_info,
    compute_cost,
    write_progress
)
from proxy_monitor.workers import worker, result_q


STATE_TRANSITIONS = {
    # First scan should classify proxies directly. Previously untested +2 became
    # flaky and untested -2 became revived, which inverted the intended meaning.
    'untested':    {'+2': 'alive',   '+1-1': 'soft',   '-2': 'dead'},
    'alive':       {'+2': 'alive',   '+1-1': 'soft',   '-2': 'cooling'},
    'soft':        {'+2': 'alive',   '+1-1': 'soft',   '-2': 'dead'},
    'cooling':     {'+2': 'alive',   '+1-1': 'soft',   '-2': 'dead'},
    'dead':        {'+2': 'revived', '+1-1': 'semi-revived', '-2': 'dead'},
    'revived':     {'+2': 'alive',   '+1-1': 'soft',   '-2': 'dead'},
    'flaky':       {'+2': 'alive',   '+1-1': 'soft',   '-2': 'dead'},
    'semi-revived':{'+2': 'revived', '+1-1': 'semi-revived', '-2': 'dead'},
}


def apply_transition(current_status, transition):
    return STATE_TRANSITIONS.get(current_status, {}).get(transition, current_status)


def mark_monitor_config_done(root_dir: str, monitor_id: str):
    """Best-effort cleanup so completed one-shot monitors leave Running state in UI."""
    if not monitor_id:
        return
    try:
        from datetime import datetime, timezone
        cfg_path = os.path.join(root_dir, '.monitors.json')
        if not os.path.exists(cfg_path):
            return
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if monitor_id in cfg:
            cfg[monitor_id]['pid'] = None
            cfg[monitor_id]['end_time'] = datetime.now(timezone.utc).isoformat()
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
    except Exception as e:
        log('[!] Failed to mark monitor config completed for {}: {}', monitor_id, e)


def run_monitor(args=None):
    if args is None:
        from proxy_monitor import app
        args = app.ARGS
    
    monitor_id = args.monitor_id if args and args.monitor_id else None
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    config_snapshot = {
        'protocol': args.protocol if args and args.protocol else 'all',
        'status': args.status if args and args.status else 'all',
    }
    
    existing_session_status = None
    existing_session_counts = {'tested': 0, 'alive': 0, 'dead': 0, 'other': 0}
    
    if monitor_id:
        with db.session() as dbs:
            existing_session = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
            if existing_session:
                existing_session_status = existing_session.status
                existing_session_counts = {
                    'tested': existing_session.tested_count or 0,
                    'alive': existing_session.alive_count or 0,
                    'dead': existing_session.dead_count or 0,
                    'other': existing_session.other_count or 0
                }
    
    if existing_session_status == 'paused':
        log("[+] Resuming paused session '{}' (tested: {})", monitor_id, existing_session_counts['tested'])
        with db.session() as dbs:
            tested_ids = set(
                row.proxy_id for row in 
                dbs.query(MonitorTested.proxy_id).filter_by(session_id=monitor_id).all()
            )
    else:
        if monitor_id and existing_session_status:
            with db.session() as dbs:
                dbs.query(MonitorTested).filter_by(session_id=monitor_id).delete()
                dbs.query(MonitorSession).filter_by(id=monitor_id).delete()
                dbs.commit()
            log("[+] Starting fresh session '{}'", monitor_id)
        tested_ids = set()
    
    with db.session() as session:
        query = session.query(Proxy)
        
        if args and args.protocol:
            protocols = [p.strip() for p in args.protocol.split(",") if p.strip()]
            if protocols:
                query = query.filter(Proxy.protocol.in_(protocols))
        
        if args and args.status:
            statuses = [s.strip() for s in args.status.split(",") if s.strip()]
            if statuses:
                status_conditions = []
                for s in statuses:
                    if s == "untested":
                        status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                    else:
                        status_conditions.append(Proxy.status == s)
                if status_conditions:
                    query = query.filter(or_(*status_conditions))
        
        if tested_ids:
            query = query.filter(~Proxy.id.in_(tested_ids))
        
        proxies = query.all()

        if not proxies:
            log("[!] No proxies to test (all already tested in this session)")
            if monitor_id:
                mark_monitor_config_done(root_dir, monitor_id)
                write_progress(root_dir, monitor_id, {"completed": True, "total": 0, "tested": 0, "percent": 100})
            return

        status_str = args.status if args and args.status else "all"
        log("[+] Testing {} proxies (protocol: {}, status: {})", len(proxies), 
            args.protocol if args and args.protocol else "all", status_str)

        rows = []
        totals = []
        for proxy in proxies:
            row = proxy.to_dict()
            row["total_checks"] = (proxy.alive_hits or 0) + (proxy.fail_hits or 0)
            totals.append(row["total_checks"])
            rows.append(row)

        max_total_checks = max(totals) if totals else 1
        if max_total_checks < 1:
            max_total_checks = 1

    if monitor_id:
        with db.session() as dbs:
            existing = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
            if existing:
                total_for_session = existing.total_proxies
                existing.status = 'running'
                log("[+] Session '{}' status updated to running", monitor_id)
            else:
                total_for_session = len(rows) + len(tested_ids)
                new_session = MonitorSession(
                    id=monitor_id,
                    config_snapshot=json.dumps(config_snapshot),
                    total_proxies=total_for_session,
                    tested_count=len(tested_ids),
                    status='running'
                )
                dbs.add(new_session)
        total = total_for_session
    else:
        total = len(rows)

    if SHUFFLE_BIAS and SHUFFLE_BIAS > 0.0:
        weight_fn = lambda r: runtime_health_rank(r, max_total_checks=max_total_checks)
        rows = weighted_shuffle(rows, weight_fn, bias_factor=SHUFFLE_BIAS)
    else:
        random.shuffle(rows)

    jobs = queue.Queue()
    
    progress_state = {
        'tested': len(tested_ids),
        'alive': existing_session_counts['alive'],
        'dead': existing_session_counts['dead'],
        'other': existing_session_counts['other'],
        'last_update': time.time()
    }
    
    def update_progress_db():
        if monitor_id:
            with db.session() as dbs:
                sess = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
                if sess:
                    sess.tested_count = progress_state['tested']
                    sess.alive_count = progress_state['alive']
                    sess.dead_count = progress_state['dead']
                    sess.other_count = progress_state['other']
    
    def update_progress_file():
        if monitor_id:
            tested = progress_state['tested']
            percent = int((tested / total) * 100) if total > 0 else 0
            write_progress(root_dir, monitor_id, {
                "total": total,
                "tested": tested,
                "alive": progress_state['alive'],
                "dead": progress_state['dead'],
                "other": progress_state['other'],
                "percent": percent
            })
    
    update_progress_file()

    def process_results():
        while True:
            try:
                item = result_q.get(timeout=0.5)
                if item is None:
                    break
                if len(item) >= 7:
                    pid, proto, host, port, successes, speeds, capability = item
                else:
                    pid, proto, host, port, successes, speeds = item
                    capability = {}
            except queue.Empty:
                continue

            now = datetime.now(timezone.utc)
            
            with db.session() as session:
                proxy = session.query(Proxy).filter_by(id=pid).first()
                if not proxy:
                    continue
                
                proxy.last_checked = now
                current_status = proxy.status or 'untested'

                proxy.web_http_ok = bool(capability.get("web_http_ok"))
                proxy.web_https_ok = bool(capability.get("web_https_ok"))
                proxy.remote_dns_ok = bool(capability.get("remote_dns_ok"))
                proxy.telegram_ok = bool(capability.get("telegram_ok"))
                proxy.exit_ip = capability.get("exit_ip")
                proxy.validation_profile = "telegram" if proxy.telegram_ok else ("web" if proxy.web_https_ok else "basic")
                proxy.validation_summary = capability or None
                if proxy.protocol == 'https' and capability.get('http_connect_fallback_ok') and not capability.get('proxy_tls_ok'):
                    proxy.protocol = 'http'
                    proto = 'http'
                
                if successes == pm_config.PROBES_PER_PROXY:
                    transition = '+2'
                    avg_speed = int(sum(speeds) / len(speeds)) if speeds else None
                    log("[ALIVE] {} {}:{} | {}ms (ok {}/{}) exit={} dns={} tg={}", proto, host, port, avg_speed, successes, pm_config.PROBES_PER_PROXY, capability.get('exit_ip'), capability.get('remote_dns_ok'), capability.get('telegram_ok'))
                    proxy.alive_hits = (proxy.alive_hits or 0) + successes
                    proxy.last_alive = now
                    proxy.speed_ms = avg_speed
                    if avg_speed:
                        history = list(proxy.speed_history or [])
                        history.append(avg_speed)
                        proxy.speed_history = history[-10:]
                elif successes > 0:
                    transition = '+1-1'
                    avg_speed = int(sum(speeds) / len(speeds)) if speeds else None
                    log("[FLAKY] {} {}:{} | (ok {}/{}) avg {}ms exit={} dns={} tg={}", proto, host, port, successes, pm_config.PROBES_PER_PROXY, avg_speed, capability.get('exit_ip'), capability.get('remote_dns_ok'), capability.get('telegram_ok'))
                    proxy.alive_hits = (proxy.alive_hits or 0) + successes
                    proxy.fail_hits = (proxy.fail_hits or 0) + (pm_config.PROBES_PER_PROXY - successes)
                    proxy.last_alive = now
                    proxy.speed_ms = avg_speed
                    if avg_speed:
                        history = list(proxy.speed_history or [])
                        history.append(avg_speed)
                        proxy.speed_history = history[-10:]
                else:
                    transition = '-2'
                    log("[DEAD]  {} {}:{} | (ok 0/{})", proto, host, port, pm_config.PROBES_PER_PROXY)
                    proxy.fail_hits = (proxy.fail_hits or 0) + pm_config.PROBES_PER_PROXY
                    proxy.last_fail = now

                proxy.total_checks = (proxy.alive_hits or 0) + (proxy.fail_hits or 0)

                new_status = apply_transition(current_status, transition)
                proxy.previous_state = current_status
                proxy.last_transition = transition
                
                if current_status == 'alive' and new_status != 'alive':
                    proxy.previous_cost = proxy.cost
                
                proxy.status = new_status

                if new_status in ['cooling', 'dead']:
                    proxy.consecutive_fails = (proxy.consecutive_fails or 0) + 1
                else:
                    proxy.consecutive_fails = 0

                proxy.cost, proxy.is_cooling, proxy.latency_score, proxy.reliability, proxy.jitter_score, proxy.recency_score, proxy.previous_cost = compute_cost(
                    proxy.alive_hits, proxy.fail_hits,
                    proxy.speed_ms, proxy.speed_history,
                    proxy.last_alive, proxy.last_fail,
                    proxy.consecutive_fails or 0,
                    new_status,
                    proxy.previous_cost
                )

                if new_status == 'alive' and (not args or getattr(args, 'geo', 'true') == 'true'):
                    if geo_expired(proxy.last_geo):
                        ip = proxy.resolved_ip or resolve_host(host)
                        if ip:
                            geo = fetch_geo_info(ip)
                            if geo:
                                proxy.continent = geo.get("continent")
                                proxy.continentCode = geo.get("continentCode")
                                proxy.country = geo.get("country")
                                proxy.countryCode = geo.get("countryCode")
                                proxy.region = geo.get("region")
                                proxy.regionName = geo.get("regionName")
                                proxy.city = geo.get("city")
                                proxy.district = geo.get("district")
                                proxy.zip = geo.get("zip")
                                proxy.lat = geo.get("lat")
                                proxy.lon = geo.get("lon")
                                proxy.timezone = geo.get("timezone")
                                proxy.isp = geo.get("isp")
                                proxy.org = geo.get("org")
                                proxy.asn = geo.get("as")
                                proxy.mobile = geo.get("mobile")
                                proxy.hosting = geo.get("hosting")
                                proxy.last_geo = now
                                proxy.resolved_ip = ip

                session.commit()
                
                if monitor_id:
                    with db.session() as dbs2:
                        try:
                            tested_record = MonitorTested(
                                session_id=monitor_id,
                                proxy_id=pid
                            )
                            dbs2.add(tested_record)
                            dbs2.commit()
                        except Exception:
                            dbs2.rollback()
                
                progress_state['tested'] += 1
                if new_status == 'alive':
                    progress_state['alive'] += 1
                elif new_status == 'dead':
                    progress_state['dead'] += 1
                else:
                    progress_state['other'] += 1
                
                now_ts = time.time()
                if progress_state['tested'] % 10 == 0 or (now_ts - progress_state['last_update']) >= 3:
                    update_progress_db()
                    update_progress_file()
                    progress_state['last_update'] = now_ts

    processor = threading.Thread(target=process_results)
    processor.start()

    threads = []
    for _ in range(pm_config.THREADS):
        t = threading.Thread(target=worker, args=(jobs,))
        t.start()
        threads.append(t)

    for row in rows:
        jobs.put(row)

    for t in threads:
        t.join()

    result_q.put(None)
    processor.join()

    if monitor_id:
        from sqlalchemy import func
        with db.session() as session:
            query = session.query(Proxy.status, func.count(Proxy.id)).group_by(Proxy.status)
            if args and args.protocol:
                protocols = [p.strip() for p in args.protocol.split(",") if p.strip()]
                if protocols:
                    query = query.filter(Proxy.protocol.in_(protocols))
            if args and args.status:
                statuses = [s.strip() for s in args.status.split(",") if s.strip()]
                if statuses:
                    status_conditions = []
                    for s in statuses:
                        if s == "untested":
                            status_conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                        else:
                            status_conditions.append(Proxy.status == s)
                    if status_conditions:
                        query = query.filter(or_(*status_conditions))
            
            status_counts = {row[0] or 'untested': row[1] for row in query.all()}
        
        with db.session() as dbs:
            sess = dbs.query(MonitorSession).filter_by(id=monitor_id).first()
            if sess:
                sess.status = 'completed'
                sess.tested_count = progress_state['tested']
                sess.alive_count = progress_state['alive']
                sess.dead_count = progress_state['dead']
                sess.other_count = progress_state['other']
        
        write_progress(root_dir, monitor_id, {
            "completed": True,
            "total": total,
            "tested": total,
            "percent": 100,
            "alive": status_counts.get('alive', 0),
            "soft": status_counts.get('soft', 0),
            "flaky": status_counts.get('flaky', 0),
            "cooling": status_counts.get('cooling', 0),
            "dead": status_counts.get('dead', 0),
            "revived": status_counts.get('revived', 0),
            "semi_revived": status_counts.get('semi-revived', 0),
            "untested": status_counts.get('untested', 0)
        })
        mark_monitor_config_done(root_dir, monitor_id)

    log("[+] Monitor finished cleanly")
