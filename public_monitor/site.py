from __future__ import annotations

import hashlib
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .core import ValidationSummary

CARD_COPY = {
    "socks5": ("SOCKS5", "Proxy-side DNS support and flexible TCP tunneling."),
    "socks4": ("SOCKS4", "Lightweight SOCKS endpoints ranked by current reachability."),
    "http": ("HTTP / HTTPS", "Web proxies validated through HTTPS CONNECT targets."),
}


def _format_number(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_site(
    output_dir: str | Path,
    *,
    summaries: dict[str, ValidationSummary],
    downloads: dict[str, Path],
    repository_url: str,
    generated_at: datetime,
    run_status: str,
) -> None:
    root = Path(output_dir)
    assets = root / "assets"
    download_dir = root / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    package_root = Path(__file__).resolve().parent
    project_root = package_root.parent
    shutil.copy2(package_root / "static" / "app.css", assets / "app.css")
    shutil.copy2(project_root / "dashboard" / "static" / "img" / "favicon.svg", assets / "logo.svg")
    favicon_ico = project_root / "dashboard" / "static" / "img" / "favicon.ico"
    if favicon_ico.exists():
        shutil.copy2(favicon_ico, root / "favicon.ico")

    files: dict[str, dict[str, object]] = {}
    for group, source in downloads.items():
        destination = download_dir / source.name
        shutil.copy2(source, destination)
        files[group] = {
            "path": f"downloads/{destination.name}",
            "size_bytes": destination.stat().st_size,
            "sha256": _sha256(destination),
        }

    total_checked = sum(item.tested for item in summaries.values())
    total_healthy = sum(item.healthy for item in summaries.values())
    status_class = "status-ok" if run_status == "success" else "status-warning"
    status_text = "Validation completed" if run_status == "success" else "Validation completed with warnings"

    cards: list[str] = []
    for group in ("socks5", "socks4", "http"):
        summary = summaries[group]
        title, description = CARD_COPY[group]
        file_info = files[group]
        size_kb = max(1, round(int(file_info["size_bytes"]) / 1024))
        cards.append(
            f"""
            <article class="download-card">
              <div class="card-heading">
                <span class="protocol-mark">{html.escape(title)}</span>
                <span class="healthy-count">{summary.top_count}/20 exported</span>
              </div>
              <p>{html.escape(description)}</p>
              <dl class="card-metrics">
                <div><dt>Tested</dt><dd>{_format_number(summary.tested)}</dd></div>
                <div><dt>Healthy</dt><dd>{_format_number(summary.healthy)}</dd></div>
                <div><dt>Top median</dt><dd>{_format_number(summary.top_median_latency_ms)} ms</dd></div>
              </dl>
              <a class="download-button" href="{html.escape(str(file_info['path']))}" download>
                <span>Download Excel</span>
                <small>{size_kb} KB · XLSX</small>
              </a>
            </article>
            """
        )

    generated_iso = generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    generated_human = generated_at.astimezone(timezone.utc).strftime("%d %B %Y · %H:%M UTC")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Fresh public proxy exports validated and ranked automatically by SecPath ProxyPool.">
  <meta name="theme-color" content="#0b1524">
  <meta property="og:title" content="SecPath Proxy Lists">
  <meta property="og:description" content="Download the current top 20 SOCKS5, SOCKS4, and HTTP/HTTPS public proxies as Excel files.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://proxy.secpath.space/">
  <link rel="canonical" href="https://proxy.secpath.space/">
  <link rel="icon" href="assets/logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/app.css">
  <title>SecPath Proxy Lists · Validated Public Proxy Exports</title>
</head>
<body>
  <div class="ambient ambient-one" aria-hidden="true"></div>
  <div class="ambient ambient-two" aria-hidden="true"></div>
  <main>
    <header class="hero">
      <a class="brand" href="{html.escape(repository_url)}" aria-label="Open SecPath ProxyPool on GitHub">
        <img src="assets/logo.svg" alt="SecPath ProxyPool logo" width="58" height="58">
        <span>SecPath Proxy Lists</span>
      </a>
      <div class="eyebrow">AUTOMATED PUBLIC VALIDATION</div>
      <h1>Fresh proxy exports.<br><span>Tested before download.</span></h1>
      <p class="hero-copy">GitHub Actions collects public proxy candidates, validates them repeatedly, ranks the strongest results, and publishes three clean Excel exports.</p>
      <div class="run-strip">
        <span class="run-state {status_class}"><i></i>{html.escape(status_text)}</span>
        <span>Last run: <time datetime="{generated_iso}">{generated_human}</time></span>
        <span>{total_checked:,} tested</span>
        <span>{total_healthy:,} healthy</span>
      </div>
    </header>

    <section class="downloads" aria-labelledby="downloads-title">
      <div class="section-heading">
        <div>
          <span class="section-kicker">CURRENT EXPORTS</span>
          <h2 id="downloads-title">Choose a protocol</h2>
        </div>
        <p>Each workbook contains up to 20 current endpoints with latency, reliability, exit-IP, and validation metadata.</p>
      </div>
      <div class="card-grid">
        {''.join(cards)}
      </div>
    </section>

    <section class="product-panel">
      <div>
        <span class="section-kicker">POWERED BY THE FULL PRODUCT</span>
        <h2>More than a proxy list.</h2>
        <p>SecPath ProxyPool is a local-first control plane for importing, validating, analyzing, and serving proxy pools through one security-conscious operational dashboard.</p>
      </div>
      <ul>
        <li>Normalize public and private sources</li>
        <li>Run resumable validation profiles</li>
        <li>Rank by reliability and capabilities</li>
        <li>Build rotating HTTP and SOCKS listeners</li>
      </ul>
      <a class="github-button" href="{html.escape(repository_url)}">Explore SecPath ProxyPool on GitHub <span aria-hidden="true">↗</span></a>
    </section>

    <section class="method-panel">
      <div>
        <span class="section-kicker">HOW TO READ THE FILES</span>
        <h2>Point-in-time validation, not a trust guarantee.</h2>
      </div>
      <p>Checks run from GitHub-hosted infrastructure and may differ from your network. Public proxies are untrusted: never send credentials, personal information, cookies, or sensitive traffic through them.</p>
    </section>
  </main>
  <footer>
    <span>SecPath Proxy Lists</span>
    <span>Updated automatically by GitHub Actions</span>
  </footer>
</body>
</html>
"""
    (root / "index.html").write_text(page, encoding="utf-8")

    metadata = {
        "generated_at": generated_iso,
        "status": run_status,
        "checked": total_checked,
        "healthy": total_healthy,
        "groups": {
            group: {
                "fetched": summary.fetched,
                "selected": summary.selected,
                "tested": summary.tested,
                "healthy": summary.healthy,
                "exported": summary.top_count,
                "top_median_latency_ms": summary.top_median_latency_ms,
                "source_failures": summary.source_failures,
                "download": files[group],
            }
            for group, summary in summaries.items()
        },
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "CNAME").write_text("proxy.secpath.space\n", encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://proxy.secpath.space/sitemap.xml\n", encoding="utf-8")
    (root / "sitemap.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://proxy.secpath.space/</loc><lastmod>{generated_at.date().isoformat()}</lastmod></url>
</urlset>
""",
        encoding="utf-8",
    )
