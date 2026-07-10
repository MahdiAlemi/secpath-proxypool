#!/usr/bin/env python3
import datetime as dt
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import MonitorSession, db, init_db
from proxy_monitor import config as pm_config
from proxy_monitor.config import DEFAULT_INTERVAL, DEFAULT_RUN_MODE, parse_args
from proxy_monitor.lifecycle import (
    MonitorAlreadyRunning,
    activate_claim,
    clear_action,
    read_action,
    release_claim,
    update_monitor_registry,
    utcnow_iso,
)
from proxy_monitor.monitor import run_monitor
from proxy_monitor.utils import STOP, init_signals, log, reset_stop, wait_interruptible


ARGS = None
_DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _root_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _allowed_schedule_days(value):
    normalized = (value or "daily").strip().lower()
    if normalized == "daily":
        return set(range(7))
    if normalized == "weekdays":
        return set(range(5))
    if normalized == "weekends":
        return {5, 6}
    days = {_DAY_MAP[item.strip()] for item in normalized.split(",") if item.strip() in _DAY_MAP}
    return days or set(range(7))


def _seconds_until_next_schedule(schedule_time, schedule_days):
    hour, minute = map(int, schedule_time.split(":"))
    allowed = _allowed_schedule_days(schedule_days)
    now = dt.datetime.now().astimezone()
    for offset in range(0, 8):
        candidate_date = now.date() + dt.timedelta(days=offset)
        candidate = dt.datetime.combine(candidate_date, dt.time(hour, minute), tzinfo=now.tzinfo)
        if candidate.weekday() in allowed and candidate > now:
            return max(0.0, (candidate - now).total_seconds()), candidate
    candidate = now + dt.timedelta(days=1)
    return 86400.0, candidate


def _mark_session_exit(monitor_id, state):
    if not monitor_id:
        return
    with db.session() as session:
        record = session.query(MonitorSession).filter_by(id=monitor_id).first()
        if record and (record.status == "running" or state in {"paused", "stopped", "failed"}):
            record.status = state


def _configure_runtime(args):
    pm_config.THREADS = args.threads
    pm_config.TIMEOUT = args.timeout
    pm_config.PROBES_PER_PROXY = args.probes
    if args.check_urls:
        pm_config.CHECK_URLS = [url.strip() for url in args.check_urls.split(",") if url.strip()]


def _run_recurring(args, interval_seconds):
    state = "idle"
    while not STOP:
        state = run_monitor(args)
        if STOP:
            break
        log("[+] Cycle complete. Next cycle in {} seconds", int(interval_seconds))
        if not wait_interruptible(interval_seconds):
            break
    return state


def main():
    global ARGS
    ARGS = parse_args()
    reset_stop()
    init_signals()
    _configure_runtime(ARGS)

    root_dir = _root_dir()
    monitor_id = ARGS.monitor_id
    claim = None
    final_state = "stopped"
    exit_code = 0
    error_text = None

    try:
        if monitor_id:
            claim = activate_claim(
                root_dir,
                monitor_id,
                token=ARGS.start_token or os.environ.get("PROXYPOOL_MONITOR_START_TOKEN"),
                pid=os.getpid(),
            )
            update_monitor_registry(
                root_dir,
                monitor_id,
                {
                    "pid": str(os.getpid()),
                    "process_create_time": claim["process_create_time"],
                    "start_time": utcnow_iso(),
                    "end_time": None,
                    "last_state": "running",
                    "last_error": None,
                },
            )

        log("[*] Initializing database...")
        init_db()
        log("[+] Database initialized")

        run_mode = ARGS.run_mode or DEFAULT_RUN_MODE
        interval = ARGS.interval or DEFAULT_INTERVAL

        if run_mode == "once":
            final_state = run_monitor(ARGS)
        elif run_mode in {"infinite", "restart"}:
            log("[+] Running recurring monitor every {} seconds", interval)
            final_state = _run_recurring(ARGS, interval)
        elif run_mode == "custom":
            seconds = ARGS.custom_every * 3600
            log("[+] Running recurring monitor every {} hours", ARGS.custom_every)
            final_state = _run_recurring(ARGS, seconds)
        elif run_mode == "schedule":
            schedule_time = ARGS.schedule_time or "00:00"
            schedule_days = ARGS.schedule_days or "daily"
            log("[+] Scheduled for {} ({})", schedule_time, schedule_days)
            while not STOP:
                wait_seconds, target = _seconds_until_next_schedule(schedule_time, schedule_days)
                log("[+] Next scheduled cycle at {}", target.isoformat())
                if not wait_interruptible(wait_seconds):
                    break
                final_state = run_monitor(ARGS)
            if STOP:
                final_state = "stopped"
        else:
            raise RuntimeError(f"Unsupported run mode: {run_mode}")

        if STOP:
            action = read_action(root_dir, monitor_id) if monitor_id else None
            final_state = "paused" if action == "pause" else "stopped"
    except MonitorAlreadyRunning as exc:
        error_text = str(exc)
        final_state = "rejected"
        exit_code = 73
        log("[!] {}", exc)
    except Exception as exc:
        error_text = str(exc)[:500]
        final_state = "failed"
        exit_code = 1
        log("[!] Monitor crashed: {}", exc)
        traceback.print_exc()
    finally:
        # A process rejected by an existing claim must not overwrite the real
        # monitor's registry/session state during its own cleanup.
        if claim is not None:
            try:
                _mark_session_exit(monitor_id, final_state)
            except Exception as exc:
                log("[!] Could not persist final session state: {}", exc)
            try:
                update_monitor_registry(
                    root_dir,
                    monitor_id,
                    {
                        "pid": None,
                        "process_create_time": None,
                        "end_time": utcnow_iso(),
                        "last_state": final_state,
                        "last_error": error_text,
                    },
                )
            except Exception as exc:
                log("[!] Could not update monitor registry on exit: {}", exc)
            try:
                release_claim(root_dir, monitor_id, pid=os.getpid())
                clear_action(root_dir, monitor_id)
            except Exception as exc:
                log("[!] Could not release monitor runtime state: {}", exc)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
