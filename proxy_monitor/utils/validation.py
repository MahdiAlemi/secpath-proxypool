import ipaddress
import subprocess
import time
from typing import Dict, Tuple

IPIFY_HTTPS = "https://api.ipify.org"
IPIFY_HTTP = "http://api.ipify.org"
TELEGRAM_URL = "https://api.telegram.org"


def is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address((text or "").strip())
        return True
    except Exception:
        return False


def proxy_url(scheme: str, host: str, port: int, user: str = "", pwd: str = "") -> str:
    auth = f"{user}:{pwd}@" if user and pwd else ""
    return f"{scheme}://{auth}{host}:{port}"


def curl_text(proxy: str, url: str, timeout: int, proxy_insecure: bool = False) -> Tuple[bool, str, int, str]:
    args = [
        "curl", "-x", proxy, url,
        "--max-time", str(timeout),
        "--connect-timeout", str(timeout),
        "-sS",
    ]
    if proxy_insecure:
        args.append("--proxy-insecure")
    start = time.perf_counter()
    try:
        res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 3, check=False)
        elapsed = int((time.perf_counter() - start) * 1000)
        out = res.stdout.decode(errors="ignore").strip()
        err = res.stderr.decode(errors="ignore").strip()[:300]
        return res.returncode == 0, out, elapsed, err
    except Exception as e:
        return False, "", int((time.perf_counter() - start) * 1000), str(e)[:300]


def curl_status(proxy: str, url: str, timeout: int, proxy_insecure: bool = False) -> Tuple[bool, str, int, str]:
    args = [
        "curl", "-x", proxy, url,
        "--max-time", str(timeout),
        "--connect-timeout", str(timeout),
        "-sS", "-o", "/dev/null", "-w", "%{http_code}",
    ]
    if proxy_insecure:
        args.append("--proxy-insecure")
    start = time.perf_counter()
    try:
        res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 3, check=False)
        elapsed = int((time.perf_counter() - start) * 1000)
        code = res.stdout.decode(errors="ignore").strip()
        err = res.stderr.decode(errors="ignore").strip()[:300]
        return res.returncode == 0 and code and code != "000", code, elapsed, err
    except Exception as e:
        return False, "000", int((time.perf_counter() - start) * 1000), str(e)[:300]


def protocol_candidates(proto: str):
    proto = (proto or "").lower()
    if proto == "socks5":
        # socks5h validates proxy-side DNS, closer to browser/Telegram use.
        return [
            {"scheme": "socks5h", "remote_dns": True},
            {"scheme": "socks5", "remote_dns": False},
        ]
    if proto == "socks4":
        return [
            {"scheme": "socks4a", "remote_dns": True},
            {"scheme": "socks4", "remote_dns": False},
        ]
    if proto == "https":
        # Public lists often use "https" to mean "HTTP proxy that supports
        # HTTPS CONNECT". First try real TLS-to-proxy, then HTTP CONNECT fallback.
        return [
            {"scheme": "https", "remote_dns": True, "proxy_insecure": True, "proxy_tls": True},
            {"scheme": "http", "remote_dns": True, "https_label_fallback": True},
        ]
    return [{"scheme": "http", "remote_dns": True}]


def validate_proxy(row: Dict, timeout: int = 5, telegram: bool = True) -> Dict:
    proto = (row.get("protocol") or "").lower()
    host = row.get("ip")
    port = int(row.get("port"))
    user = row.get("username") or ""
    pwd = row.get("password") or ""

    summary = {
        "protocol": proto,
        "web_http_ok": False,
        "web_https_ok": False,
        "remote_dns_ok": False,
        "telegram_ok": False,
        "exit_ip": None,
        "speed_ms": None,
        "proxy_url_scheme": None,
        "proxy_tls_ok": False,
        "http_connect_fallback_ok": False,
        "errors": [],
    }

    chosen = None
    for cand in protocol_candidates(proto):
        scheme = cand["scheme"]
        purl = proxy_url(scheme, host, port, user, pwd)
        ok, out, ms, err = curl_text(purl, IPIFY_HTTPS, timeout, proxy_insecure=bool(cand.get("proxy_insecure")))
        if ok and is_ip(out):
            summary.update({
                "web_https_ok": True,
                "exit_ip": out.strip(),
                "speed_ms": ms,
                "proxy_url_scheme": scheme,
                "remote_dns_ok": bool(cand.get("remote_dns")),
                "proxy_tls_ok": bool(cand.get("proxy_tls")),
                "http_connect_fallback_ok": bool(cand.get("https_label_fallback")),
            })
            chosen = cand
            break
        summary["errors"].append({"scheme": scheme, "target": "https_ipify", "error": err or out[:120]})

    if chosen:
        purl = proxy_url(chosen["scheme"], host, port, user, pwd)
        pinsecure = bool(chosen.get("proxy_insecure"))
        ok_http, out_http, _, err_http = curl_text(purl, IPIFY_HTTP, timeout, proxy_insecure=pinsecure)
        summary["web_http_ok"] = bool(ok_http and is_ip(out_http))
        if not summary["web_http_ok"]:
            summary["errors"].append({"scheme": chosen["scheme"], "target": "http_ipify", "error": err_http or out_http[:120]})

        if telegram:
            ok_tg, code, _, err_tg = curl_status(purl, TELEGRAM_URL, timeout, proxy_insecure=pinsecure)
            summary["telegram_ok"] = bool(ok_tg and code != "000")
            summary["telegram_status"] = code
            if not summary["telegram_ok"]:
                summary["errors"].append({"scheme": chosen["scheme"], "target": "telegram", "error": err_tg or code})

    summary["ok"] = bool(summary["web_https_ok"] and summary["exit_ip"])
    return summary
