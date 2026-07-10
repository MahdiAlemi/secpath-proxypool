import json
import os
import queue
import random
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import func, or_

from database import MonitorSession, MonitorTested, Proxy, db
from proxy_monitor import config as pm_config
from proxy_monitor.lifecycle import read_action
from proxy_monitor.utils import (
    STOP,
    compute_cost,
    fetch_geo_info,
    geo_expired,
    log,
    resolve_host,
    runtime_health_rank,
    weighted_shuffle,
    write_progress,
)
from proxy_monitor.workers import worker


SHUFFLE_BIAS = pm_config.SHUFFLE_BIAS

STATE_TRANSITIONS = {
    "untested": {"+2": "alive", "+1-1": "soft", "-2": "dead"},
    "alive": {"+2": "alive", "+1-1": "soft", "-2": "cooling"},
    "soft": {"+2": "alive", "+1-1": "soft", "-2": "dead"},
    "cooling": {"+2": "alive", "+1-1": "soft", "-2": "dead"},
    "dead": {"+2": "revived", "+1-1": "semi-revived", "-2": "dead"},
    "revived": {"+2": "alive", "+1-1": "soft", "-2": "dead"},
    "flaky": {"+2": "alive", "+1-1": "soft", "-2": "dead"},
    "semi-revived": {"+2": "revived", "+1-1": "semi-revived", "-2": "dead"},
}


def apply_transition(current_status, transition):
    return STATE_TRANSITIONS.get(current_status, {}).get(transition, current_status)


def _root_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _apply_filters(query, args):
    if args and args.protocol:
        protocols = [value.strip() for value in args.protocol.split(",") if value.strip()]
        if protocols:
            query = query.filter(Proxy.protocol.in_(protocols))
    if args and args.status:
        statuses = [value.strip() for value in args.status.split(",") if value.strip()]
        if statuses:
            conditions = []
            for status in statuses:
                if status == "untested":
                    conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
                else:
                    conditions.append(Proxy.status == status)
            if conditions:
                query = query.filter(or_(*conditions))
    return query


def _session_status_counts(monitor_id):
    counts = {}
    if not monitor_id:
        return counts
    with db.session() as session:
        rows = (
            session.query(Proxy.status, func.count(Proxy.id))
            .join(MonitorTested, MonitorTested.proxy_id == Proxy.id)
            .filter(MonitorTested.session_id == monitor_id)
            .group_by(Proxy.status)
            .all()
        )
        counts = {(status or "untested"): count for status, count in rows}
    return counts


def _progress_payload(total, progress_state, *, state, completed=False):
    tested = int(progress_state.get("tested", 0))
    percent = 100 if completed else (int((tested / total) * 100) if total > 0 else 0)
    payload = {
        "state": state,
        "completed": bool(completed),
        "paused": state == "paused",
        "stopped": state == "stopped",
        "failed": state == "failed",
        "total": int(total),
        "tested": tested,
        "alive": int(progress_state.get("alive", 0)),
        "dead": int(progress_state.get("dead", 0)),
        "other": int(progress_state.get("other", 0)),
        "percent": max(0, min(100, percent)),
    }
    return payload


def _persist_session(monitor_id, progress_state, status):
    if not monitor_id:
        return
    with db.session() as session:
        record = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if record:
            record.status = status
            record.tested_count = int(progress_state.get("tested", 0))
            record.alive_count = int(progress_state.get("alive", 0))
            record.dead_count = int(progress_state.get("dead", 0))
            record.other_count = int(progress_state.get("other", 0))


def _write_final_progress(root_dir, monitor_id, total, progress_state, state):
    if not monitor_id:
        return
    completed = state == "completed"
    payload = _progress_payload(total, progress_state, state=state, completed=completed)
    if completed:
        counts = _session_status_counts(monitor_id)
        payload.update(
            {
                "alive": counts.get("alive", 0),
                "soft": counts.get("soft", 0),
                "flaky": counts.get("flaky", 0),
                "cooling": counts.get("cooling", 0),
                "dead": counts.get("dead", 0),
                "revived": counts.get("revived", 0),
                "semi_revived": counts.get("semi-revived", 0),
                "untested": counts.get("untested", 0),
            }
        )
    write_progress(root_dir, monitor_id, payload)


def run_monitor(args=None):
    if args is None:
        from proxy_monitor import app

        args = app.ARGS

    monitor_id = args.monitor_id if args and args.monitor_id else None
    root_dir = _root_dir()
    config_snapshot = {
        "protocol": args.protocol if args and args.protocol else "all",
        "status": args.status if args and args.status else "all",
        "threads": args.threads if args else pm_config.THREADS,
        "timeout": args.timeout if args else pm_config.TIMEOUT,
        "probes": args.probes if args else pm_config.PROBES_PER_PROXY,
    }

    existing_status = None
    existing_total = 0
    progress_state = {"tested": 0, "alive": 0, "dead": 0, "other": 0, "last_update": time.time()}
    tested_ids = set()

    if monitor_id:
        with db.session() as session:
            existing = session.query(MonitorSession).filter_by(id=monitor_id).first()
            if existing:
                existing_status = existing.status
                existing_total = existing.total_proxies or 0
                if existing.status == "paused":
                    progress_state.update(
                        {
                            "tested": existing.tested_count or 0,
                            "alive": existing.alive_count or 0,
                            "dead": existing.dead_count or 0,
                            "other": existing.other_count or 0,
                        }
                    )
                    tested_ids = {
                        row.proxy_id
                        for row in session.query(MonitorTested.proxy_id)
                        .filter_by(session_id=monitor_id)
                        .all()
                    }
                else:
                    session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
                    session.delete(existing)

    if existing_status == "paused":
        log("[+] Resuming paused session '{}' ({} already tested)", monitor_id, len(tested_ids))

    with db.session() as session:
        query = _apply_filters(session.query(Proxy), args)
        if tested_ids:
            query = query.filter(~Proxy.id.in_(tested_ids))
        proxies = query.all()
        rows = []
        totals = []
        for proxy in proxies:
            row = proxy.to_dict()
            row["total_checks"] = (proxy.alive_hits or 0) + (proxy.fail_hits or 0)
            totals.append(row["total_checks"])
            rows.append(row)
        max_total_checks = max(totals) if totals else 1

    total = existing_total if existing_status == "paused" and existing_total else len(rows) + len(tested_ids)

    if monitor_id:
        with db.session() as session:
            current = session.query(MonitorSession).filter_by(id=monitor_id).first()
            if current:
                current.status = "running"
                current.total_proxies = total
            else:
                session.add(
                    MonitorSession(
                        id=monitor_id,
                        config_snapshot=json.dumps(config_snapshot),
                        total_proxies=total,
                        tested_count=progress_state["tested"],
                        alive_count=progress_state["alive"],
                        dead_count=progress_state["dead"],
                        other_count=progress_state["other"],
                        status="running",
                    )
                )

    if not rows:
        log("[+] No remaining proxies for this monitor cycle")
        state = "completed" if not STOP else (read_action(root_dir, monitor_id) or "stopped")
        if state not in {"paused", "stopped"}:
            state = "completed"
        _persist_session(monitor_id, progress_state, state)
        _write_final_progress(root_dir, monitor_id, total, progress_state, state)
        return state

    log(
        "[+] Testing {} proxies (protocol: {}, status: {})",
        len(rows),
        args.protocol if args and args.protocol else "all",
        args.status if args and args.status else "all",
    )

    if SHUFFLE_BIAS and SHUFFLE_BIAS > 0.0:
        rows = weighted_shuffle(
            rows,
            lambda row: runtime_health_rank(row, max_total_checks=max(1, max_total_checks)),
            bias_factor=SHUFFLE_BIAS,
        )
    else:
        random.shuffle(rows)

    jobs = queue.Queue()
    results = queue.Queue()
    processor_errors = []

    def update_progress_file():
        if monitor_id:
            write_progress(root_dir, monitor_id, _progress_payload(total, progress_state, state="running"))

    _persist_session(monitor_id, progress_state, "running")
    update_progress_file()

    def process_results():
        while True:
            try:
                item = results.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                return
            try:
                pid, proto, host, port, successes, speeds, capability = item
                now = datetime.now(timezone.utc)
                with db.session() as session:
                    proxy = session.query(Proxy).filter_by(id=pid).first()
                    if not proxy:
                        continue
                    proxy.last_checked = now
                    current_status = proxy.status or "untested"
                    proxy.web_http_ok = bool(capability.get("web_http_ok"))
                    proxy.web_https_ok = bool(capability.get("web_https_ok"))
                    proxy.remote_dns_ok = bool(capability.get("remote_dns_ok"))
                    proxy.telegram_ok = bool(capability.get("telegram_ok"))
                    proxy.exit_ip = capability.get("exit_ip")
                    proxy.validation_profile = "telegram" if proxy.telegram_ok else ("web" if proxy.web_https_ok else "basic")
                    proxy.validation_summary = capability or None
                    if proxy.protocol == "https" and capability.get("http_connect_fallback_ok") and not capability.get("proxy_tls_ok"):
                        proxy.protocol = "http"
                        proto = "http"

                    if successes == pm_config.PROBES_PER_PROXY:
                        transition = "+2"
                        avg_speed = int(sum(speeds) / len(speeds)) if speeds else None
                        proxy.alive_hits = (proxy.alive_hits or 0) + successes
                        proxy.last_alive = now
                        proxy.speed_ms = avg_speed
                        log("[ALIVE] {} {}:{} | {}ms (ok {}/{})", proto, host, port, avg_speed, successes, pm_config.PROBES_PER_PROXY)
                    elif successes > 0:
                        transition = "+1-1"
                        avg_speed = int(sum(speeds) / len(speeds)) if speeds else None
                        proxy.alive_hits = (proxy.alive_hits or 0) + successes
                        proxy.fail_hits = (proxy.fail_hits or 0) + (pm_config.PROBES_PER_PROXY - successes)
                        proxy.last_alive = now
                        proxy.speed_ms = avg_speed
                        log("[FLAKY] {} {}:{} | ok {}/{}", proto, host, port, successes, pm_config.PROBES_PER_PROXY)
                    else:
                        transition = "-2"
                        avg_speed = None
                        proxy.fail_hits = (proxy.fail_hits or 0) + pm_config.PROBES_PER_PROXY
                        proxy.last_fail = now
                        log("[DEAD] {} {}:{} | ok 0/{}", proto, host, port, pm_config.PROBES_PER_PROXY)

                    if avg_speed:
                        history = list(proxy.speed_history or [])
                        history.append(avg_speed)
                        proxy.speed_history = history[-10:]

                    proxy.total_checks = (proxy.alive_hits or 0) + (proxy.fail_hits or 0)
                    new_status = apply_transition(current_status, transition)
                    proxy.previous_state = current_status
                    proxy.last_transition = transition
                    if current_status == "alive" and new_status != "alive":
                        proxy.previous_cost = proxy.cost
                    proxy.status = new_status
                    proxy.consecutive_fails = (proxy.consecutive_fails or 0) + 1 if new_status in {"cooling", "dead"} else 0
                    (
                        proxy.cost,
                        proxy.is_cooling,
                        proxy.latency_score,
                        proxy.reliability,
                        proxy.jitter_score,
                        proxy.recency_score,
                        proxy.previous_cost,
                    ) = compute_cost(
                        proxy.alive_hits,
                        proxy.fail_hits,
                        proxy.speed_ms,
                        proxy.speed_history,
                        proxy.last_alive,
                        proxy.last_fail,
                        proxy.consecutive_fails or 0,
                        new_status,
                        proxy.previous_cost,
                    )

                    if new_status == "alive" and (not args or getattr(args, "geo", "true") == "true") and geo_expired(proxy.last_geo):
                        resolved_ip = proxy.resolved_ip or resolve_host(host)
                        if resolved_ip:
                            geo = fetch_geo_info(resolved_ip)
                            if geo:
                                for attr, key in (
                                    ("continent", "continent"), ("continentCode", "continentCode"),
                                    ("country", "country"), ("countryCode", "countryCode"),
                                    ("region", "region"), ("regionName", "regionName"),
                                    ("city", "city"), ("district", "district"), ("zip", "zip"),
                                    ("lat", "lat"), ("lon", "lon"), ("timezone", "timezone"),
                                    ("isp", "isp"), ("org", "org"), ("asn", "as"),
                                    ("mobile", "mobile"), ("hosting", "hosting"),
                                ):
                                    setattr(proxy, attr, geo.get(key))
                                proxy.last_geo = now
                                proxy.resolved_ip = resolved_ip

                if monitor_id:
                    with db.session() as session:
                        if not session.query(MonitorTested).filter_by(session_id=monitor_id, proxy_id=pid).first():
                            session.add(MonitorTested(session_id=monitor_id, proxy_id=pid))

                progress_state["tested"] += 1
                if new_status == "alive":
                    progress_state["alive"] += 1
                elif new_status == "dead":
                    progress_state["dead"] += 1
                else:
                    progress_state["other"] += 1

                # Persist authoritative counts after every completed proxy.
                # The progress JSON remains throttled to reduce filesystem churn.
                _persist_session(monitor_id, progress_state, "running")
                now_ts = time.time()
                if progress_state["tested"] % 5 == 0 or now_ts - progress_state["last_update"] >= 1:
                    update_progress_file()
                    progress_state["last_update"] = now_ts
            except Exception as exc:
                processor_errors.append(str(exc))
                log("[!] Result processor error: {}", exc)

    processor = threading.Thread(target=process_results, name=f"{monitor_id or 'monitor'}-results")
    processor.start()

    thread_count = max(1, min(int(getattr(args, "threads", pm_config.THREADS)), len(rows)))
    threads = [
        threading.Thread(target=worker, args=(jobs, results), name=f"{monitor_id or 'monitor'}-worker-{index + 1}")
        for index in range(thread_count)
    ]
    for row in rows:
        if STOP:
            break
        jobs.put(row)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    results.put(None)
    processor.join()
    _persist_session(monitor_id, progress_state, "running")
    update_progress_file()

    action = read_action(root_dir, monitor_id) if monitor_id else None
    if STOP:
        state = action if action in {"pause", "stop"} else "stopped"
        state = "paused" if state == "pause" else "stopped"
    elif processor_errors:
        state = "failed"
    elif progress_state["tested"] >= total:
        state = "completed"
    else:
        state = "failed"

    _persist_session(monitor_id, progress_state, state)
    _write_final_progress(root_dir, monitor_id, total, progress_state, state)
    log("[+] Monitor cycle finished with state '{}' ({}/{})", state, progress_state["tested"], total)
    return state
