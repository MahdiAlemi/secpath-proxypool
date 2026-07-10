from __future__ import annotations

import hashlib
import ipaddress
import random
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

from proxy_importer.utils.importer import normalize_proxy_line
from proxy_monitor.utils.validation import curl_text, is_ip, protocol_candidates, proxy_url

CHECK_TARGETS = (
    "https://api.ipify.org",
    "https://ident.me",
)
SUPPORTED_SOURCE_SECTIONS = {"http", "https", "socks4", "socks5"}
PUBLIC_GROUPS = {
    "socks5": {"socks5"},
    "socks4": {"socks4"},
    "http": {"http", "https"},
}


@dataclass(frozen=True, slots=True)
class Candidate:
    protocol: str
    host: str
    port: int
    source_count: int = 1

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{host}:{self.port}"

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.protocol, self.host, self.port


@dataclass(slots=True)
class RankedProxy:
    candidate: Candidate
    successes: int
    probes: int
    latencies_ms: list[int]
    exit_ips: list[str]
    verified_scheme: str | None
    remote_dns: bool
    checked_at: datetime
    errors: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.probes <= 0:
            return 0.0
        return self.successes / self.probes

    @property
    def median_latency_ms(self) -> int | None:
        if not self.latencies_ms:
            return None
        return int(round(statistics.median(self.latencies_ms)))

    @property
    def jitter_ms(self) -> int:
        if len(self.latencies_ms) < 2:
            return 0
        return int(round(statistics.pstdev(self.latencies_ms)))

    @property
    def exit_ip(self) -> str | None:
        return self.exit_ips[-1] if self.exit_ips else None

    @property
    def exit_consistent(self) -> bool:
        return bool(self.exit_ips) and len(set(self.exit_ips)) == 1

    @property
    def proxy_url(self) -> str:
        scheme = self.verified_scheme or self.candidate.protocol
        return proxy_url(scheme, self.candidate.host, self.candidate.port)


@dataclass(slots=True)
class ValidationSummary:
    group: str
    fetched: int = 0
    selected: int = 0
    tested: int = 0
    healthy: int = 0
    top_count: int = 0
    source_failures: int = 0
    top_median_latency_ms: int | None = None


def parse_source_config(path: str | Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {name: [] for name in SUPPORTED_SOURCE_SECTIONS}
    current: str | None = None

    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            candidate = line[1:-1].strip().lower()
            current = candidate if candidate in SUPPORTED_SOURCE_SECTIONS else None
            continue
        if current:
            parsed = urlparse(line)
            if parsed.scheme == "https" and parsed.hostname:
                sections[current].append(line)
    return sections


def _public_ip(text: str) -> str | None:
    try:
        address = ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return None
    if not address.is_global:
        return None
    return str(address)


def _fetch_source(protocol: str, url: str, timeout: int) -> list[Candidate]:
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "SecPath-ProxyPool-Public-Monitor/1.0"},
        )
        response.raise_for_status()
    finally:
        session.close()
    if len(response.content) > 2_000_000:
        raise ValueError("source response exceeds 2 MB")

    candidates: list[Candidate] = []
    for raw_line in response.text.splitlines():
        normalized = normalize_proxy_line(raw_line, protocol)
        if not normalized:
            continue
        parsed_protocol, host, port, username, password = normalized
        if username or password:
            continue
        if parsed_protocol not in SUPPORTED_SOURCE_SECTIONS:
            continue
        public_host = _public_ip(host)
        if not public_host:
            continue
        candidates.append(Candidate(parsed_protocol, public_host, int(port)))
    return candidates


def collect_candidates(
    source_path: str | Path,
    *,
    fetch_timeout: int = 20,
) -> tuple[dict[str, list[Candidate]], dict[str, int]]:
    sources = parse_source_config(source_path)
    by_identity: dict[tuple[str, str, int], Candidate] = {}
    failures = {name: 0 for name in SUPPORTED_SOURCE_SECTIONS}

    jobs = [(protocol, url) for protocol, urls in sources.items() for url in urls]
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs))), thread_name_prefix="source-fetch") as executor:
        future_map = {
            executor.submit(_fetch_source, protocol, url, fetch_timeout): (protocol, url)
            for protocol, url in jobs
        }
        for future in as_completed(future_map):
            protocol, url = future_map[future]
            try:
                fetched = future.result()
            except Exception as exc:
                failures[protocol] += 1
                print(f"[source:{protocol}] {url} failed: {type(exc).__name__}: {exc}")
                continue
            for candidate in fetched:
                existing = by_identity.get(candidate.identity)
                if existing:
                    by_identity[candidate.identity] = Candidate(
                        existing.protocol,
                        existing.host,
                        existing.port,
                        existing.source_count + 1,
                    )
                else:
                    by_identity[candidate.identity] = candidate

    grouped: dict[str, list[Candidate]] = {name: [] for name in PUBLIC_GROUPS}
    for candidate in by_identity.values():
        for group, protocols in PUBLIC_GROUPS.items():
            if candidate.protocol in protocols:
                grouped[group].append(candidate)
                break
    return grouped, failures


def select_candidates(
    candidates: Iterable[Candidate],
    *,
    limit: int,
    seed: str,
) -> list[Candidate]:
    ranked = sorted(
        candidates,
        key=lambda item: (-item.source_count, item.protocol, item.host, item.port),
    )
    if len(ranked) <= limit:
        return ranked

    # Keep broadly corroborated endpoints first, then rotate the long tail between runs.
    priority_count = min(max(limit // 3, 20), len(ranked))
    priority = ranked[:priority_count]
    tail = ranked[priority_count:]
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    rng.shuffle(tail)
    return priority + tail[: max(0, limit - len(priority))]


def _probe_candidate(candidate: Candidate, timeout: int, probes: int) -> RankedProxy:
    latencies: list[int] = []
    exit_ips: list[str] = []
    errors: list[str] = []
    verified_scheme: str | None = None
    remote_dns = False
    successes = 0

    for probe_index in range(probes):
        target = CHECK_TARGETS[probe_index % len(CHECK_TARGETS)]
        probe_ok = False
        for option in protocol_candidates(candidate.protocol):
            scheme = option["scheme"]
            endpoint = proxy_url(scheme, candidate.host, candidate.port)
            ok, output, elapsed_ms, error = curl_text(
                endpoint,
                target,
                timeout,
                proxy_insecure=bool(option.get("proxy_insecure")),
            )
            if ok and is_ip(output):
                successes += 1
                latencies.append(elapsed_ms)
                exit_ips.append(output.strip())
                verified_scheme = scheme
                remote_dns = bool(option.get("remote_dns"))
                probe_ok = True
                break
            if error:
                errors.append(error[:160])
        if not probe_ok:
            errors.append(f"probe {probe_index + 1} failed")

    result = RankedProxy(
        candidate=candidate,
        successes=successes,
        probes=probes,
        latencies_ms=latencies,
        exit_ips=exit_ips,
        verified_scheme=verified_scheme,
        remote_dns=remote_dns,
        checked_at=datetime.now(timezone.utc),
        errors=errors[-5:],
    )
    result.score = score_result(result)
    return result


def score_result(result: RankedProxy) -> float:
    median = result.median_latency_ms or 10_000
    latency_component = max(0.0, 1.0 - min(median, 3_000) / 3_000)
    reliability = result.success_rate
    consistency = 1.0 if result.exit_consistent else 0.0
    corroboration = min(result.candidate.source_count, 4) / 4
    remote_dns = 1.0 if result.remote_dns else 0.0
    return round(
        reliability * 60
        + latency_component * 25
        + consistency * 5
        + corroboration * 5
        + remote_dns * 5,
        3,
    )


def validate_candidates(
    candidates: list[Candidate],
    *,
    timeout: int,
    probes: int,
    workers: int,
) -> list[RankedProxy]:
    if not candidates:
        return []
    results: list[RankedProxy] = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="proxy-check") as executor:
        future_map = {
            executor.submit(_probe_candidate, candidate, timeout, probes): candidate
            for candidate in candidates
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            candidate = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    RankedProxy(
                        candidate=candidate,
                        successes=0,
                        probes=probes,
                        latencies_ms=[],
                        exit_ips=[],
                        verified_scheme=None,
                        remote_dns=False,
                        checked_at=datetime.now(timezone.utc),
                        errors=[f"{type(exc).__name__}: {exc}"],
                    )
                )
            if index % 100 == 0 or index == len(candidates):
                print(f"[validation] completed {index}/{len(candidates)}")
    return results


def choose_top(results: Iterable[RankedProxy], *, top_n: int) -> list[RankedProxy]:
    healthy = [item for item in results if item.successes > 0 and item.median_latency_ms is not None]
    healthy.sort(
        key=lambda item: (
            -item.success_rate,
            -item.score,
            item.median_latency_ms or 99_999,
            item.jitter_ms,
            item.candidate.endpoint,
        )
    )

    selected: list[RankedProxy] = []
    seen_exit: set[str] = set()
    reliability_levels = sorted({item.success_rate for item in healthy}, reverse=True)

    # Exit-IP diversity is applied inside each reliability tier. A less reliable
    # endpoint can never displace a fully reliable endpoint merely for diversity.
    for level in reliability_levels:
        tier = [item for item in healthy if item.success_rate == level]
        deferred: list[RankedProxy] = []
        for result in tier:
            exit_ip = result.exit_ip
            if exit_ip and exit_ip in seen_exit:
                deferred.append(result)
                continue
            selected.append(result)
            if exit_ip:
                seen_exit.add(exit_ip)
            if len(selected) >= top_n:
                return selected
        for result in deferred:
            selected.append(result)
            if len(selected) >= top_n:
                return selected
    return selected
