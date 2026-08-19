from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func


def _group_count(session, column) -> list[dict[str, Any]]:
    rows = (
        session.query(column, func.count())
        .group_by(column)
        .order_by(func.count().desc())
        .all()
    )
    return [{"value": value if value not in (None, "") else "unknown", "count": int(count)} for value, count in rows]


def summary() -> dict[str, Any]:
    from database import Proxy, db

    with db.session() as session:
        total = session.query(Proxy).count()
        statuses = _group_count(session, Proxy.status)
        protocols = _group_count(session, Proxy.protocol)

        caps = {}
        for name in ("web_http_ok", "web_https_ok", "remote_dns_ok", "telegram_ok"):
            column = getattr(Proxy, name, None)
            if column is not None:
                caps[name] = int(session.query(Proxy).filter(column.is_(True)).count())

        speed_col = getattr(Proxy, "speed_ms", None)
        latency = {"samples": 0, "avg_ms": None, "min_ms": None, "max_ms": None}
        if speed_col is not None:
            row = (
                session.query(
                    func.count(speed_col),
                    func.avg(speed_col),
                    func.min(speed_col),
                    func.max(speed_col),
                )
                .filter(speed_col.is_not(None))
                .first()
            )
            if row:
                latency = {
                    "samples": int(row[0] or 0),
                    "avg_ms": round(float(row[1]), 2) if row[1] is not None else None,
                    "min_ms": float(row[2]) if row[2] is not None else None,
                    "max_ms": float(row[3]) if row[3] is not None else None,
                }

    return {
        "total": int(total),
        "statuses": statuses,
        "protocols": protocols,
        "capabilities": caps,
        "latency": latency,
    }


def health() -> list[dict[str, Any]]:
    from database import Proxy, db

    with db.session() as session:
        total = int(session.query(Proxy).count())
        rows = _group_count(session, Proxy.status)
    for row in rows:
        row["percent"] = round((row["count"] / total) * 100, 2) if total else 0.0
    return rows


def protocols() -> list[dict[str, Any]]:
    from database import Proxy, db
    with db.session() as session:
        return _group_count(session, Proxy.protocol)


def capabilities() -> list[dict[str, Any]]:
    from database import Proxy, db

    mapping = [
        ("HTTP", "web_http_ok"),
        ("HTTPS", "web_https_ok"),
        ("Remote DNS", "remote_dns_ok"),
        ("Telegram", "telegram_ok"),
    ]
    result = []
    with db.session() as session:
        total = int(session.query(Proxy).count())
        for label, attr in mapping:
            column = getattr(Proxy, attr, None)
            if column is None:
                continue
            count = int(session.query(Proxy).filter(column.is_(True)).count())
            result.append(
                {
                    "capability": label,
                    "count": count,
                    "percent": round((count / total) * 100, 2) if total else 0.0,
                }
            )
    return result


def latency() -> dict[str, Any]:
    from database import Proxy, db

    column = getattr(Proxy, "speed_ms", None)
    if column is None:
        return {"samples": 0, "avg_ms": None, "min_ms": None, "max_ms": None, "buckets": []}

    with db.session() as session:
        values = [
            float(row[0])
            for row in session.query(column).filter(column.is_not(None), column >= 0).all()
            if row[0] is not None
        ]

    if not values:
        return {"samples": 0, "avg_ms": None, "min_ms": None, "max_ms": None, "buckets": []}

    values.sort()
    buckets = [
        ("<250ms", 0, 250),
        ("250-500ms", 250, 500),
        ("500-1000ms", 500, 1000),
        ("1-2s", 1000, 2000),
        (">=2s", 2000, None),
    ]
    out = []
    for label, low, high in buckets:
        if high is None:
            count = sum(1 for v in values if v >= low)
        else:
            count = sum(1 for v in values if low <= v < high)
        out.append({"bucket": label, "count": count})

    def percentile(p: float) -> float:
        if len(values) == 1:
            return values[0]
        pos = (len(values) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(values) - 1)
        frac = pos - lo
        return values[lo] * (1 - frac) + values[hi] * frac

    return {
        "samples": len(values),
        "avg_ms": round(sum(values) / len(values), 2),
        "min_ms": min(values),
        "p50_ms": round(percentile(0.50), 2),
        "p95_ms": round(percentile(0.95), 2),
        "max_ms": max(values),
        "buckets": out,
    }


def countries(limit: int = 20) -> list[dict[str, Any]]:
    from database import Proxy, db

    column = getattr(Proxy, "country_code", None)
    if column is None:
        return []
    with db.session() as session:
        return _group_count(session, column)[:limit]


def providers(by: str = "isp", limit: int = 20) -> list[dict[str, Any]]:
    from database import Proxy, db

    aliases = {
        "isp": "isp",
        "org": "org",
        "organization": "org",
        "asn": "asn",
    }
    attr = aliases.get(str(by).lower())
    if attr is None:
        raise ValueError("--by must be one of: isp, org, asn")
    column = getattr(Proxy, attr, None)
    if column is None:
        return []
    with db.session() as session:
        return _group_count(session, column)[:limit]
