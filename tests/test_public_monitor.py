from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from public_monitor.core import (
    Candidate,
    RankedProxy,
    ValidationSummary,
    choose_top,
    parse_source_config,
    score_result,
    select_candidates,
)
from public_monitor.site import build_site


class PublicMonitorTest(unittest.TestCase):
    def _result(
        self,
        host: str,
        latency: int,
        *,
        successes: int = 2,
        probes: int = 2,
        exit_ip: str | None = None,
        source_count: int = 2,
        protocol: str = "socks5",
    ) -> RankedProxy:
        result = RankedProxy(
            candidate=Candidate(protocol, host, 1080, source_count),
            successes=successes,
            probes=probes,
            latencies_ms=[latency] * successes,
            exit_ips=[exit_ip or host] * successes,
            verified_scheme="socks5h" if protocol == "socks5" else protocol,
            remote_dns=protocol.startswith("socks"),
            checked_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        )
        result.score = score_result(result)
        return result

    def test_public_monitor_import_is_standalone_from_application_database(self):
        script = r"""
import builtins

blocked = {"database", "proxy_importer", "proxy_monitor", "psutil", "sqlalchemy"}
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.split(".", 1)[0] in blocked:
        raise RuntimeError(f"blocked application dependency imported: {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import public_monitor.core  # noqa: F401
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_public_monitor_normalizer_handles_source_formats_without_credentials(self):
        from public_monitor.normalization import normalize_proxy_line

        self.assertEqual(
            normalize_proxy_line("198.51.100.10:8080", "http"),
            ("http", "198.51.100.10", 8080, None, None),
        )
        self.assertEqual(
            normalize_proxy_line("socks5 203.0.113.7 1080", "http"),
            ("socks5", "203.0.113.7", 1080, None, None),
        )
        self.assertEqual(
            normalize_proxy_line("[2001:db8::1]:1080", "socks5"),
            ("socks5", "2001:db8::1", 1080, None, None),
        )
        self.assertIsNone(normalize_proxy_line("ftp://198.51.100.10:21", "http"))
        self.assertIsNone(normalize_proxy_line("198.51.100.10:70000", "http"))

        from public_monitor.network import protocol_candidates, proxy_url

        self.assertEqual(proxy_url("socks5h", "2001:4860:4860::8888", 1080), "socks5h://[2001:4860:4860::8888]:1080")
        self.assertTrue(protocol_candidates("socks5")[0]["remote_dns"])
        self.assertEqual(protocol_candidates("https")[1]["scheme"], "http")

    def test_source_config_accepts_only_https_known_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.ini"
            path.write_text(
                "[http]\nhttps://example.com/list.txt\nhttp://bad.example/list\n"
                "[unknown]\nhttps://example.com/ignored\n[socks5]\nhttps://example.org/s5\n",
                encoding="utf-8",
            )
            parsed = parse_source_config(path)
        self.assertEqual(parsed["http"], ["https://example.com/list.txt"])
        self.assertEqual(parsed["socks5"], ["https://example.org/s5"])
        self.assertEqual(parsed["socks4"], [])

    def test_candidate_selection_prioritizes_corroborated_sources_and_is_stable(self):
        candidates = [Candidate("http", f"198.51.100.{index}", 8000 + index, 1) for index in range(1, 40)]
        candidates.append(Candidate("http", "203.0.113.10", 8080, 4))
        first = select_candidates(candidates, limit=20, seed="run-a")
        second = select_candidates(candidates, limit=20, seed="run-a")
        self.assertEqual(first, second)
        self.assertIn(Candidate("http", "203.0.113.10", 8080, 4), first)

    def test_top_ranking_prefers_reliability_and_diverse_exit_ips(self):
        reliable = self._result("8.8.8.8", 180, exit_ip="1.1.1.1")
        faster_but_unreliable = self._result("9.9.9.9", 30, successes=1, exit_ip="2.2.2.2")
        duplicate_exit = self._result("4.2.2.2", 90, exit_ip="1.1.1.1")
        other = self._result("208.67.222.222", 210, exit_ip="3.3.3.3")
        top = choose_top([faster_but_unreliable, duplicate_exit, other, reliable], top_n=3)
        self.assertEqual(top[0], duplicate_exit)
        self.assertIn(reliable, top)
        self.assertIn(other, top)
        self.assertNotIn(faster_but_unreliable, top)

    def test_static_site_contains_downloads_but_no_proxy_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workbooks = {}
            for group, filename in {
                "socks5": "top-20-socks5.xlsx",
                "socks4": "top-20-socks4.xlsx",
                "http": "top-20-http-https.xlsx",
            }.items():
                path = root / filename
                path.write_bytes(b"xlsx-placeholder")
                workbooks[group] = path
            summaries = {
                group: ValidationSummary(group, fetched=100, selected=50, tested=50, healthy=25, top_count=20, top_median_latency_ms=120)
                for group in workbooks
            }
            output = root / "site"
            build_site(
                output,
                summaries=summaries,
                downloads=workbooks,
                repository_url="https://github.com/MahdiAlemi/secpath-proxypool",
                generated_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
                run_status="success",
            )
            html_text = (output / "index.html").read_text(encoding="utf-8")
            metadata_text = (output / "metadata.json").read_text(encoding="utf-8")
            metadata = json.loads(metadata_text)

        self.assertIn("SecPath Proxy Lists", html_text)
        self.assertIn("SecPath ProxyPool", html_text)
        self.assertIn("Download Excel", html_text)
        self.assertIn("v1.0.0", html_text)
        self.assertIn("Developed by Mahdi Alemi", html_text)
        self.assertIn("github.com/MahdiAlemi/secpath-proxypool", html_text)
        self.assertIn("top-20-socks5.xlsx", html_text)
        self.assertNotIn("198.51.100.", html_text)
        self.assertNotIn("198.51.100.", metadata_text)
        self.assertEqual(metadata["groups"]["socks5"]["exported"], 20)
        self.assertEqual(metadata["version"], "v1.0.0")
        self.assertEqual(metadata["developer"], "Developed by Mahdi Alemi")
        self.assertEqual(metadata["repository"], "https://github.com/MahdiAlemi/secpath-proxypool")

    def test_workflow_is_scheduled_manual_and_pages_only(self):
        workflow = Path(".github/workflows/public-proxy-monitor.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn('cron: "17 */2 * * *"', workflow)
        self.assertIn("actions/checkout@v7", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-pages-artifact@v5", workflow)
        self.assertIn("actions/deploy-pages@v5", workflow)
        self.assertNotIn("curl proxy.secpath.space/api", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_excel_export_is_a_valid_xlsx_when_dependency_is_available(self):
        try:
            from public_monitor.excel import build_excel
        except ModuleNotFoundError as exc:
            self.skipTest(f"optional public monitor dependency unavailable: {exc}")

        result = self._result("8.8.4.4", 140, exit_ip="1.0.0.1")
        summary = ValidationSummary("socks5", fetched=10, selected=5, tested=5, healthy=1, top_count=1, top_median_latency_ms=140)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.xlsx"
            build_excel(
                path,
                group="socks5",
                proxies=[result],
                summary=summary,
                repository_url="https://github.com/MahdiAlemi/secpath-proxypool",
            )
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        self.assertIn("[Content_Types].xml", names)
        self.assertIn("Top Proxies", workbook_xml)
        self.assertIn("About", workbook_xml)


if __name__ == "__main__":
    unittest.main()
