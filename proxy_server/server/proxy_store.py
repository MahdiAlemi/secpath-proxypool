from __future__ import annotations

import hashlib
import random
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote, urlsplit

from database import Proxy, get_db_session
from proxy_server.protocol import ProtocolError, parse_authority
from proxy_server.utils.logging import log


class ProxyStore:
    def __init__(self, args):
        self.args = args
        self.readonly = bool(getattr(args, "readonly", False))
        self.lock = threading.RLock()
        self.cached_proxy = None
        self.last_rotate = 0.0
        self._candidates = None
        self._last_load = 0.0
        self._load_interval = 30.0

    @staticmethod
    def _identity(row):
        return (
            row.get("id"),
            str(row.get("protocol") or "").lower(),
            str(row.get("ip") or "").lower(),
            int(row.get("port") or 0),
            str(row.get("username") or ""),
        )

    def _load_candidates_from_db(self):
        statuses_arg = getattr(self.args, "candidate_statuses", "alive") or "alive"
        statuses = [status.strip() for status in str(statuses_arg).split(",") if status.strip()] or ["alive"]
        with get_db_session() as session:
            query = session.query(Proxy).filter(
                Proxy.protocol.in_(["http", "https", "socks4", "socks5"]),
                Proxy.status.in_(statuses),
            )
            return [proxy.to_dict() for proxy in query.all()]

    def _ensure_candidates(self, *, force=False):
        now = time.time()
        if force or self._candidates is None or now - self._last_load > self._load_interval:
            try:
                self._candidates = self._load_candidates_from_db()
                self._last_load = now
                log("[Store] loaded {0} candidate proxies", len(self._candidates))
            except Exception as exc:
                log("[Store] DB load failed: {0}", exc)
                if self._candidates is None:
                    self._candidates = []

    @staticmethod
    def _match_csv(row, field_name, csv_arg):
        if not csv_arg:
            return True
        wanted = {value.strip() for value in str(csv_arg).split(",") if value.strip()}
        if not wanted:
            return True
        value = row.get(field_name)
        return value is not None and str(value) in wanted

    @staticmethod
    def _match_flag(row, field_name, wanted):
        if wanted is None:
            return True
        value = row.get(field_name)
        if value is None:
            return False
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                actual = True
            elif lowered in {"0", "false", "no", "off", ""}:
                actual = False
            else:
                actual = bool(value)
        else:
            actual = bool(value)
        return actual is bool(wanted)

    def fetch_candidates(self, *, force=False):
        self._ensure_candidates(force=force)
        minimum = float(self.args.min_cost or 0.0)
        maximum = float(self.args.cost_threshold) if self.args.cost_threshold is not None else None
        upstream_protocols = {
            value.strip().lower()
            for value in str(getattr(self.args, "upstream_protocol", "") or "").split(",")
            if value.strip()
        }

        rows = []
        for row in list(self._candidates or []):
            if getattr(self.args, "require_web_https", False) and not row.get("web_https_ok"):
                continue
            if getattr(self.args, "require_remote_dns", False) and not row.get("remote_dns_ok"):
                continue
            if getattr(self.args, "require_telegram", False) and not row.get("telegram_ok"):
                continue

            auth_filter = getattr(self.args, "auth_required", None)
            has_credentials = bool(row.get("username") or row.get("password"))
            if auth_filter == "auth" and not has_credentials:
                continue
            if auth_filter == "no_auth" and has_credentials:
                continue

            if upstream_protocols and str(row.get("protocol") or "").lower() not in upstream_protocols:
                continue

            mappings = (
                ("countryCode", self.args.countryCodes),
                ("regionName", self.args.regions),
                ("city", self.args.cities),
                ("org", self.args.orgs),
                ("isp", self.args.isp),
                ("asn", self.args.asn),
                ("continentCode", self.args.continentCode),
                ("zip", self.args.zip_codes),
                ("timezone", self.args.timezones),
            )
            if any(not self._match_csv(row, field, wanted) for field, wanted in mappings):
                continue
            if not self._match_flag(row, "mobile", self.args.mobile):
                continue
            if not self._match_flag(row, "proxy", self.args.proxy):
                continue
            if not self._match_flag(row, "hosting", self.args.hosting):
                continue

            try:
                cost = float(row.get("cost"))
            except (TypeError, ValueError):
                continue
            if cost < minimum or (maximum is not None and cost > maximum):
                continue
            rows.append(row)

        rows.sort(key=lambda item: (float(item.get("cost") or 9999.0), item.get("speed_ms") or 99999))
        return rows

    def _compute_cost(self, row):
        speed = row.get("speed_ms") or 1000
        alive = max(1, row.get("alive_hits") or 0)
        fails = row.get("fail_hits") or 0
        return (speed / 1000.0) * self.args.w_latency + (fails / alive) * self.args.w_fail

    def best(self, candidates):
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda row: float(row.get("cost")) if row.get("cost") is not None else self._compute_cost(row),
        )

    def _still_available(self, cached, candidates):
        identity = self._identity(cached) if cached else None
        return next((row for row in candidates if self._identity(row) == identity), None)

    def _parse_sticky_upstream(self):
        raw = str(getattr(self.args, "sticky_upstream", "") or "").strip()
        if not raw:
            return None
        if raw.lower().startswith("id:"):
            try:
                return {"id": int(raw.split(":", 1)[1])}
            except ValueError as exc:
                raise ProtocolError("sticky_upstream id must be numeric") from exc

        candidate = raw if "://" in raw else f"//{raw}"
        parsed = urlsplit(candidate)
        protocol = parsed.scheme.lower() if parsed.scheme else None
        if protocol and protocol not in {"http", "https", "socks4", "socks5"}:
            raise ProtocolError("sticky_upstream protocol is invalid")
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            host, port = parse_authority(raw)
        return {
            "protocol": protocol,
            "ip": host.lower(),
            "port": int(port),
            "username": unquote(parsed.username or "") if parsed.username else None,
        }

    def _select_explicit_sticky(self, candidates):
        selector = self._parse_sticky_upstream()
        if not selector:
            return None
        for row in candidates:
            if selector.get("id") is not None and row.get("id") == selector["id"]:
                return row
            if selector.get("id") is not None:
                continue
            if str(row.get("ip") or "").lower() != selector["ip"] or int(row.get("port") or 0) != selector["port"]:
                continue
            if selector.get("protocol") and str(row.get("protocol") or "").lower() != selector["protocol"]:
                continue
            if selector.get("username") is not None and str(row.get("username") or "") != selector["username"]:
                continue
            return row
        return None

    def _select_client_sticky(self, candidates, client_key):
        if not candidates:
            return None
        key = str(client_key or "anonymous")
        # Rendezvous hashing remains stable when the candidate order changes and
        # only remaps clients affected by a candidate entering/leaving the set.
        def score(row):
            material = f"{key}|{self._identity(row)!r}".encode()
            return int.from_bytes(hashlib.sha256(material).digest(), "big")

        return max(candidates, key=score)

    def select(self, force=False, *, client_key=None, exclude_ids=None):
        excluded = {value for value in (exclude_ids or set()) if value is not None}
        with self.lock:
            candidates = [row for row in self.fetch_candidates(force=force) if row.get("id") not in excluded]
            if not candidates:
                return None

            mode = self.args.rotate
            cached = self._still_available(self.cached_proxy, candidates)
            if cached is not None:
                self.cached_proxy = cached
            elif self.cached_proxy is not None:
                self.cached_proxy = None

            if mode == "fixed":
                if self.cached_proxy is None:
                    self.cached_proxy = random.choice(candidates)
                return self.cached_proxy

            if mode == "per_connection":
                return random.choice(candidates)

            if mode == "better_cost":
                best = self.best(candidates)
                if self.cached_proxy is None or force:
                    self.cached_proxy = best
                    self.last_rotate = time.time()
                else:
                    current_cost = float(self.cached_proxy.get("cost") or self._compute_cost(self.cached_proxy))
                    best_cost = float(best.get("cost") or self._compute_cost(best))
                    if best_cost < current_cost - 1e-9:
                        self.cached_proxy = best
                        self.last_rotate = time.time()
                return self.cached_proxy

            if mode == "time":
                now = time.time()
                if self.cached_proxy is None or force or now - self.last_rotate >= max(1, self.args.rotate_interval):
                    self.cached_proxy = random.choice(candidates)
                    self.last_rotate = now
                return self.cached_proxy

            if mode == "sticky":
                explicit = self._select_explicit_sticky(candidates)
                if getattr(self.args, "sticky_upstream", None):
                    return explicit
                return self._select_client_sticky(candidates, client_key)

            return random.choice(candidates)

    def mark_fail(self, row):
        if self.readonly or not row or row.get("id") is None:
            return
        try:
            with get_db_session() as session:
                proxy = session.query(Proxy).filter_by(id=row["id"]).first()
                if proxy:
                    now = datetime.now(timezone.utc)
                    proxy.fail_hits = (proxy.fail_hits or 0) + 1
                    proxy.total_checks = (proxy.total_checks or 0) + 1
                    proxy.consecutive_fails = (proxy.consecutive_fails or 0) + 1
                    proxy.last_fail = now
                    proxy.last_checked = now
        except Exception as exc:
            log("[Store] failed to persist upstream failure: {0}", exc)

    def mark_alive(self, row, speed_ms: Optional[int] = None):
        if self.readonly or not row or row.get("id") is None:
            return
        try:
            with get_db_session() as session:
                proxy = session.query(Proxy).filter_by(id=row["id"]).first()
                if proxy:
                    now = datetime.now(timezone.utc)
                    proxy.alive_hits = (proxy.alive_hits or 0) + 1
                    proxy.total_checks = (proxy.total_checks or 0) + 1
                    proxy.consecutive_fails = 0
                    proxy.last_alive = now
                    proxy.last_checked = now
                    if speed_ms is not None:
                        proxy.speed_ms = int(speed_ms)
        except Exception as exc:
            log("[Store] failed to persist upstream success: {0}", exc)
