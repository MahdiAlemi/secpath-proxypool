from __future__ import annotations

import ipaddress
import subprocess
import time


def is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address((text or "").strip())
        return True
    except ValueError:
        return False


def proxy_url(scheme: str, host: str, port: int) -> str:
    formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{scheme}://{formatted_host}:{port}"


def curl_text(
    proxy: str,
    url: str,
    timeout: int,
    *,
    proxy_insecure: bool = False,
) -> tuple[bool, str, int, str]:
    args = [
        "curl",
        "-x",
        proxy,
        url,
        "--max-time",
        str(timeout),
        "--connect-timeout",
        str(timeout),
        "-sS",
    ]
    if proxy_insecure:
        args.append("--proxy-insecure")

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return False, "", elapsed_ms, str(exc)[:300]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    output = completed.stdout.decode(errors="ignore").strip()
    error = completed.stderr.decode(errors="ignore").strip()[:300]
    return completed.returncode == 0, output, elapsed_ms, error


def protocol_candidates(protocol: str) -> list[dict[str, object]]:
    normalized = (protocol or "").lower()
    if normalized == "socks5":
        return [
            {"scheme": "socks5h", "remote_dns": True},
            {"scheme": "socks5", "remote_dns": False},
        ]
    if normalized == "socks4":
        return [
            {"scheme": "socks4a", "remote_dns": True},
            {"scheme": "socks4", "remote_dns": False},
        ]
    if normalized == "https":
        return [
            {
                "scheme": "https",
                "remote_dns": True,
                "proxy_insecure": True,
                "proxy_tls": True,
            },
            {
                "scheme": "http",
                "remote_dns": True,
                "https_label_fallback": True,
            },
        ]
    return [{"scheme": "http", "remote_dns": True}]
