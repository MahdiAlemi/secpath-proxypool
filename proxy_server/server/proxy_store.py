import threading
import time
import random
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from database import Proxy, get_db_session


class ProxyStore:
    def __init__(self, args):
        self.args = args
        self.readonly = bool(getattr(args, "readonly", False))
        self.lock = threading.Lock()
        self.cached_proxy = None
        self.last_rotate = 0.0
        self._candidates = None
        self._last_load = 0.0
        self._load_interval = 30.0

    def _load_candidates_from_db(self):
        statuses_arg = getattr(self.args, "candidate_statuses", "alive") or "alive"
        statuses = [s.strip() for s in statuses_arg.split(",") if s.strip()]
        if not statuses:
            statuses = ["alive"]
        with get_db_session() as session:
            proxies = session.query(Proxy).filter(
                Proxy.protocol.in_(['http', 'https', 'socks4', 'socks5']),
                Proxy.status.in_(statuses)
            ).all()
            return [p.to_dict() for p in proxies]

    def _ensure_candidates(self):
        now = time.time()
        if (self._candidates is None) or (now - self._last_load > self._load_interval):
            try:
                self._candidates = self._load_candidates_from_db()
                self._last_load = now
                from proxy_server.utils.logging import log
                log("[Store] loaded {0} candidate proxies", len(self._candidates))
            except Exception as e:
                from proxy_server.utils.logging import log
                log("[Store] DB load failed: {0}", e)
                self._candidates = []

    def fetch_candidates(self):
        self._ensure_candidates()

        min_c = float(self.args.min_cost or 0.0)
        has_cost_filter = self.args.cost_threshold is not None
        max_c = float(self.args.cost_threshold) if has_cost_filter else None

        rows = []
        for r in self._candidates:
            if has_cost_filter:
                c = r.get("cost")
                if c is None:
                    continue
                try:
                    cf = float(c)
                except Exception:
                    continue
                if cf < min_c or cf > max_c:
                    continue

            if getattr(self.args, "require_web_https", False) and not r.get("web_https_ok"):
                continue
            if getattr(self.args, "require_remote_dns", False) and not r.get("remote_dns_ok"):
                continue
            if getattr(self.args, "require_telegram", False) and not r.get("telegram_ok"):
                continue

            if self.args.auth_required:
                has_creds = bool(r.get("username"))
                if self.args.auth_required == "auth" and not has_creds:
                    continue
                if self.args.auth_required == "no_auth" and has_creds:
                    continue

            def match_csv(field_name, csv_arg):
                if not csv_arg:
                    return True
                want = {v.strip() for v in csv_arg.split(",") if v.strip()}
                if not want:
                    return True
                val = r.get(field_name)
                if val is None:
                    return False
                return str(val) in want

            if not match_csv("countryCode", self.args.countryCodes):
                continue
            if not match_csv("region", self.args.regions):
                continue
            if not match_csv("city", self.args.cities):
                continue
            if not match_csv("org", self.args.orgs):
                continue
            if not match_csv("isp", self.args.isp):
                continue
            if not match_csv("asn", self.args.asn):
                continue
            if not match_csv("continentCode", self.args.continentCode):
                continue
            if not match_csv("zip", self.args.zip_codes):
                continue
            if not match_csv("timezone", self.args.timezones):
                continue

            def match_flag(field_name, arg_val):
                if arg_val is None or arg_val == "":
                    return True
                v = r.get(field_name)
                if v is None:
                    return False if arg_val else True
                try:
                    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                        return bool(int(v)) == bool(arg_val)
                except Exception:
                    pass
                return bool(v) == bool(arg_val)

            if not match_flag("mobile", self.args.mobile):
                continue
            if not match_flag("proxy", self.args.proxy):
                continue
            if not match_flag("hosting", self.args.hosting):
                continue

            upstream_proto_arg = getattr(self.args, "upstream_protocol", "") or ""
            if upstream_proto_arg:
                allowed = {p.strip().lower() for p in upstream_proto_arg.split(",") if p.strip()}
                if allowed and (str(r.get("protocol") or "").lower() not in allowed):
                    continue

            c = r.get("cost")
            if c is None:
                continue
            try:
                cf = float(c)
            except Exception:
                continue
            if has_cost_filter:
                if cf < min_c or cf > max_c:
                    continue
            else:
                if cf < min_c:
                    continue

            rows.append(r)

        rows.sort(key=lambda rr: (float(rr.get("cost") or 9999.0), rr.get("speed_ms") or 99999))
        return rows

    def _compute_cost(self, r):
        speed = (r.get("speed_ms") or 1000)
        alive = (r.get("alive_hits") or 1)
        fails = (r.get("fail_hits") or 0)
        return (speed / 1000.0) * self.args.w_latency + (fails / alive) * self.args.w_fail

    def best(self, candidates):
        if not candidates:
            return None
        def keyfn(r):
            c = r.get("cost")
            return float(c) if (c is not None) else self._compute_cost(r)
        return min(candidates, key=keyfn)

    def select(self, force=False):
        with self.lock:
            candidates = self.fetch_candidates()
            if not candidates and (self.args.rotate != "sticky"):
                return None

            mode = self.args.rotate

            if mode == "fixed":
                if not self.cached_proxy:
                    self.cached_proxy = random.choice(candidates)
                return self.cached_proxy

            if mode == "per_connection":
                return random.choice(candidates)

            if mode == "better_cost":
                if self.cached_proxy is None or force:
                    self.cached_proxy = self.best(candidates)
                    self.last_rotate = time.time()
                    return self.cached_proxy
                current_cost = float(self.cached_proxy.get("cost") or self._compute_cost(self.cached_proxy))
                for c in candidates:
                    c_cost = float(c.get("cost") or self._compute_cost(c))
                    if c_cost < current_cost - 1e-9:
                        self.cached_proxy = c
                        self.last_rotate = time.time()
                        return self.cached_proxy
                return self.cached_proxy

            if mode == "time":
                now = time.time()
                if (now - self.last_rotate) >= max(1, self.args.rotate_interval) or (self.cached_proxy is None):
                    self.cached_proxy = random.choice(candidates)
                    self.last_rotate = now
                return self.cached_proxy

            if mode == "sticky":
                return self.cached_proxy

            return random.choice(candidates)

    def mark_fail(self, row):
        if self.readonly:
            return
        row_id = row.get("id")
        if row_id is None:
            return
        try:
            with get_db_session() as session:
                proxy = session.query(Proxy).filter_by(id=row_id).first()
                if proxy:
                    proxy.fail_hits = (proxy.fail_hits or 0) + 1
                    proxy.last_checked = datetime.now(timezone.utc)
        except Exception:
            pass

    def mark_alive(self, row, speed_ms: Optional[int] = None):
        if self.readonly:
            return
        row_id = row.get("id")
        if row_id is None:
            return
        try:
            with get_db_session() as session:
                proxy = session.query(Proxy).filter_by(id=row_id).first()
                if proxy:
                    proxy.alive_hits = (proxy.alive_hits or 0) + 1
                    proxy.last_alive = datetime.now(timezone.utc)
                    if speed_ms is not None:
                        proxy.speed_ms = speed_ms
        except Exception:
            pass
