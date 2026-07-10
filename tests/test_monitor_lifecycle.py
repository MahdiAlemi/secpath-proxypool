import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from database import MonitorSession, MonitorTested, Proxy, db
from proxy_monitor.lifecycle import (
    MonitorAlreadyRunning,
    abandon_reservation,
    activate_claim,
    clear_action,
    process_matches,
    read_action,
    release_claim,
    request_action,
    reserve_start,
    terminate_process,
)
from proxy_monitor.monitor.runner import run_monitor
from proxy_monitor.utils.logging import STOP, request_stop, reset_stop
from proxy_monitor.utils.progress import read_progress, write_progress


class MonitorLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.ensure_schema()

    def setUp(self):
        reset_stop()
        self.temp_dir = tempfile.TemporaryDirectory(prefix="proxypool-lifecycle-")

    def tearDown(self):
        reset_stop()
        self.temp_dir.cleanup()

    def test_stop_flag_remains_live_for_importers(self):
        imported_reference = STOP
        self.assertFalse(bool(imported_reference))
        request_stop("unit-test")
        self.assertTrue(bool(imported_reference))
        reset_stop()
        self.assertFalse(bool(imported_reference))

    def test_start_reservation_rejects_concurrent_launch(self):
        monitor_id = "monitor_reservation-test"
        token = reserve_start(self.temp_dir.name, monitor_id)
        with self.assertRaises(MonitorAlreadyRunning):
            reserve_start(self.temp_dir.name, monitor_id)
        abandon_reservation(self.temp_dir.name, monitor_id, token)
        replacement = reserve_start(self.temp_dir.name, monitor_id)
        self.assertNotEqual(token, replacement)
        abandon_reservation(self.temp_dir.name, monitor_id, replacement)

    def test_process_identity_and_graceful_termination(self):
        monitor_id = "monitor_process-test"
        token = reserve_start(self.temp_dir.name, monitor_id)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                "--monitor-id",
                monitor_id,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            activate_claim(self.temp_dir.name, monitor_id, token=token, pid=process.pid)
            self.assertTrue(process_matches(process.pid, monitor_id))
            result = terminate_process(
                self.temp_dir.name,
                monitor_id,
                action="pause",
                grace_seconds=2,
            )
            process.wait(timeout=5)
            self.assertTrue(result["found"])
            self.assertEqual(read_action(self.temp_dir.name, monitor_id), "pause")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            release_claim(self.temp_dir.name, monitor_id, pid=process.pid)
            clear_action(self.temp_dir.name, monitor_id)

    def test_unrelated_pid_is_not_accepted_as_monitor(self):
        monitor_id = "monitor_pid-reuse-test"
        self.assertFalse(process_matches(os.getpid(), monitor_id))

    def test_rejected_duplicate_process_does_not_overwrite_registry(self):
        from proxy_monitor import app as monitor_app

        args = SimpleNamespace(
            monitor_id="monitor_duplicate-test",
            protocol=None,
            status=None,
            check_urls=None,
            threads=1,
            timeout=1,
            probes=1,
            name="duplicate",
            run_mode="once",
            interval=10,
            schedule_time=None,
            schedule_days="daily",
            custom_every=24,
            geo="false",
            start_token="token",
        )
        with (
            patch.object(monitor_app, "parse_args", return_value=args),
            patch.object(monitor_app, "init_signals"),
            patch.object(
                monitor_app,
                "activate_claim",
                side_effect=MonitorAlreadyRunning(args.monitor_id, 1234),
            ),
            patch.object(monitor_app, "update_monitor_registry") as update_registry,
        ):
            exit_code = monitor_app.main()
        self.assertEqual(exit_code, 73)
        update_registry.assert_not_called()

    def test_progress_paths_reject_traversal(self):
        with self.assertRaises(ValueError):
            write_progress(self.temp_dir.name, "../../escape", {"tested": 1})

    def test_pause_preserves_partial_progress_for_resume(self):
        monitor_id = f"monitor_pause-{uuid4().hex[:8]}"
        marker_status = f"lifecycle-{uuid4().hex[:10]}"
        proxy_ids = []
        with db.session() as session:
            for index in range(6):
                proxy = Proxy(
                    protocol="http",
                    ip=f"lifecycle-{index}-{uuid4().hex[:6]}.example",
                    port=8000 + index,
                    status=marker_status,
                )
                session.add(proxy)
                session.flush()
                proxy_ids.append(proxy.id)

        args = SimpleNamespace(
            monitor_id=monitor_id,
            protocol="http",
            status=marker_status,
            threads=1,
            timeout=1,
            probes=2,
            geo="false",
        )

        probe_counter = {"count": 0}
        first_proxy_done = threading.Event()

        def slow_success(*_args, **_kwargs):
            time.sleep(0.08)
            probe_counter["count"] += 1
            if probe_counter["count"] >= 2:
                first_proxy_done.set()
            return {
                "ok": True,
                "speed_ms": 10,
                "web_http_ok": True,
                "web_https_ok": True,
                "remote_dns_ok": True,
                "telegram_ok": False,
                "exit_ip": "203.0.113.10",
            }

        result = {}

        def execute():
            result["state"] = run_monitor(args)

        try:
            with (
                patch("proxy_monitor.monitor.runner._root_dir", return_value=self.temp_dir.name),
                patch("proxy_monitor.workers.tester.validate_proxy", side_effect=slow_success),
                patch("proxy_monitor.config.PROBES_PER_PROXY", 2),
                patch("proxy_monitor.config.PROBE_JITTER", (0.0, 0.0)),
            ):
                thread = threading.Thread(target=execute)
                thread.start()
                self.assertTrue(first_proxy_done.wait(timeout=3))
                time.sleep(0.05)
                request_action(self.temp_dir.name, monitor_id, "pause")
                request_stop("pause-test")
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            progress = read_progress(self.temp_dir.name, monitor_id)
            self.assertEqual(result.get("state"), "paused")
            self.assertTrue(progress["paused"])
            self.assertFalse(progress["completed"])
            self.assertGreaterEqual(progress["tested"], 1)
            self.assertLess(progress["tested"], progress["total"])
            paused_tested = progress["tested"]
            with db.session() as session:
                monitor_session = session.query(MonitorSession).filter_by(id=monitor_id).first()
                self.assertIsNotNone(monitor_session)
                self.assertEqual(monitor_session.status, "paused")
                self.assertEqual(monitor_session.tested_count, paused_tested)

            reset_stop()
            clear_action(self.temp_dir.name, monitor_id)
            with (
                patch("proxy_monitor.monitor.runner._root_dir", return_value=self.temp_dir.name),
                patch("proxy_monitor.workers.tester.validate_proxy", side_effect=slow_success),
                patch("proxy_monitor.config.PROBES_PER_PROXY", 2),
                patch("proxy_monitor.config.PROBE_JITTER", (0.0, 0.0)),
            ):
                resumed_state = run_monitor(args)
            resumed = read_progress(self.temp_dir.name, monitor_id)
            self.assertEqual(resumed_state, "completed")
            self.assertTrue(resumed["completed"])
            self.assertEqual(resumed["tested"], resumed["total"])
            self.assertEqual(resumed["total"], 6)
        finally:
            reset_stop()
            with db.session() as session:
                session.query(MonitorTested).filter_by(session_id=monitor_id).delete()
                session.query(MonitorSession).filter_by(id=monitor_id).delete()
                session.query(Proxy).filter(Proxy.id.in_(proxy_ids)).delete(synchronize_session=False)


if __name__ == "__main__":
    unittest.main()
