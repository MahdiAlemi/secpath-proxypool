from __future__ import annotations

import argparse
import os
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    PUBLIC_GROUPS,
    ValidationSummary,
    choose_top,
    collect_candidates,
    select_candidates,
    validate_candidates,
)
from .excel import build_excel
from .site import build_site

FILENAMES = {
    "socks5": "top-20-socks5.xlsx",
    "socks4": "top-20-socks4.xlsx",
    "http": "top-20-http-https.xlsx",
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build the ProxyPool public validation site.")
    result.add_argument("--sources", default="public_monitor/sources.ini")
    result.add_argument("--output", default="public_site")
    result.add_argument("--work-dir", default=".public-monitor-work")
    result.add_argument("--top", type=int, default=20)
    result.add_argument("--max-candidates", type=int, default=700)
    result.add_argument("--workers", type=int, default=96)
    result.add_argument("--timeout", type=int, default=5)
    result.add_argument("--fetch-timeout", type=int, default=15)
    result.add_argument("--probes", type=int, default=2)
    result.add_argument("--seed", default="")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.top <= 100:
        raise SystemExit("--top must be between 1 and 100")
    if not 20 <= args.max_candidates <= 5_000:
        raise SystemExit("--max-candidates must be between 20 and 5000")
    if not 1 <= args.workers <= 256:
        raise SystemExit("--workers must be between 1 and 256")
    if not 2 <= args.timeout <= 20:
        raise SystemExit("--timeout must be between 2 and 20")
    if not 3 <= args.fetch_timeout <= 60:
        raise SystemExit("--fetch-timeout must be between 3 and 60")
    if not 1 <= args.probes <= 5:
        raise SystemExit("--probes must be between 1 and 5")
    if not shutil.which("curl"):
        raise SystemExit("curl is required for proxy validation")

    generated_at = datetime.now(timezone.utc)
    repository = os.environ.get("GITHUB_REPOSITORY", "secpath/proxypool")
    repository_url = os.environ.get("PUBLIC_MONITOR_REPOSITORY_URL", f"https://github.com/{repository}")
    seed = args.seed or generated_at.strftime("%Y-%m-%dT%H")

    work_dir = Path(args.work_dir)
    output_dir = Path(args.output)
    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Fetching and normalizing public sources")
    grouped, source_failures = collect_candidates(args.sources, fetch_timeout=args.fetch_timeout)

    summaries: dict[str, ValidationSummary] = {}
    downloads: dict[str, Path] = {}
    warning = False

    for group in PUBLIC_GROUPS:
        all_candidates = grouped[group]
        summary = ValidationSummary(
            group=group,
            fetched=len(all_candidates),
            source_failures=sum(source_failures.get(protocol, 0) for protocol in PUBLIC_GROUPS[group]),
        )
        selected = select_candidates(
            all_candidates,
            limit=args.max_candidates,
            seed=f"{seed}:{group}",
        )
        summary.selected = len(selected)
        print(f"[2/4] Validating {group}: {len(selected)} selected from {len(all_candidates)} unique")
        results = validate_candidates(
            selected,
            timeout=args.timeout,
            probes=args.probes,
            workers=args.workers,
        )
        top = choose_top(results, top_n=args.top)
        healthy = [result for result in results if result.successes > 0]
        summary.tested = len(results)
        summary.healthy = len(healthy)
        summary.top_count = len(top)
        if top:
            summary.top_median_latency_ms = int(
                round(statistics.median(item.median_latency_ms or 0 for item in top))
            )
        if not top:
            warning = True

        workbook_path = work_dir / FILENAMES[group]
        build_excel(
            workbook_path,
            group=group,
            proxies=top,
            summary=summary,
            repository_url=repository_url,
        )
        downloads[group] = workbook_path
        summaries[group] = summary
        print(
            f"[result:{group}] tested={summary.tested} healthy={summary.healthy} "
            f"exported={summary.top_count}"
        )

    print("[3/4] Building static site")
    build_site(
        output_dir,
        summaries=summaries,
        downloads=downloads,
        repository_url=repository_url,
        generated_at=generated_at,
        run_status="warning" if warning else "success",
    )
    print(f"[4/4] Site ready: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
