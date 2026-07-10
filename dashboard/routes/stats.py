from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify
from sqlalchemy import func, or_

from dashboard.config import PROTOCOLS
from dashboard.decorators import login_required, require_permission
from dashboard.proxy_scope import apply_proxy_scope
from database import Proxy

stats_bp = Blueprint("stats", __name__)


def get_db():
    if "db_session" not in g:
        from database import db

        g.db_session = db.get_session()
    return g.db_session


def _count(query):
    return query.with_entities(func.count(Proxy.id)).scalar() or 0


def _percentage(value, total):
    return round((value / total) * 100, 1) if total else 0.0


@stats_bp.route("/api/stats", methods=["GET"])
@login_required
@require_permission("stats.view")
def api_stats():
    session = get_db()
    base = apply_proxy_scope(session.query(Proxy))

    total = _count(base)
    status_counts = {
        "alive": _count(base.filter(Proxy.status == "alive")),
        "flaky": _count(base.filter(Proxy.status == "flaky")),
        "soft": _count(base.filter(Proxy.status == "soft")),
        "cooling": _count(base.filter(Proxy.status == "cooling")),
        "dead": _count(base.filter(Proxy.status == "dead")),
        "untested": _count(base.filter(or_(Proxy.status == "untested", Proxy.status.is_(None)))),
        "revived": _count(base.filter(Proxy.status == "revived")),
        "semi-revived": _count(base.filter(Proxy.status == "semi-revived")),
    }

    by_protocol = {protocol: _count(base.filter(Proxy.protocol == protocol)) for protocol in PROTOCOLS}

    by_country_rows = (
        base.with_entities(Proxy.countryCode, func.count(Proxy.id))
        .filter(Proxy.countryCode.isnot(None), Proxy.countryCode != "")
        .group_by(Proxy.countryCode)
        .order_by(func.count(Proxy.id).desc())
        .limit(10)
        .all()
    )
    by_country = [{"country": row[0], "count": row[1]} for row in by_country_rows]

    by_isp_rows = (
        base.with_entities(Proxy.isp, func.count(Proxy.id))
        .filter(Proxy.isp.isnot(None), Proxy.isp != "")
        .group_by(Proxy.isp)
        .order_by(func.count(Proxy.id).desc())
        .limit(10)
        .all()
    )
    by_isp = [{"isp": row[0], "count": row[1]} for row in by_isp_rows]

    avg_speed = base.with_entities(func.avg(Proxy.speed_ms)).filter(Proxy.speed_ms.isnot(None)).scalar()
    last_scan = base.with_entities(func.max(Proxy.last_checked)).scalar()

    protocol_stats = {}
    for protocol in PROTOCOLS:
        protocol_query = base.filter(Proxy.protocol == protocol)
        protocol_total = _count(protocol_query)
        protocol_alive = _count(protocol_query.filter(Proxy.status == "alive"))
        protocol_stats[protocol] = {
            "total": protocol_total,
            "alive": protocol_alive,
            "flaky": _count(protocol_query.filter(Proxy.status == "flaky")),
            "soft": _count(protocol_query.filter(Proxy.status == "soft")),
            "cooling": _count(protocol_query.filter(Proxy.status == "cooling")),
            "dead": _count(protocol_query.filter(Proxy.status == "dead")),
            "untested": _count(protocol_query.filter(or_(Proxy.status == "untested", Proxy.status.is_(None)))),
            "revived": _count(protocol_query.filter(Proxy.status == "revived")),
            "semi-revived": _count(protocol_query.filter(Proxy.status == "semi-revived")),
            "last_check": protocol_query.with_entities(func.max(Proxy.last_checked)).scalar(),
            "alive_rate": _percentage(protocol_alive, protocol_total),
        }

    web_ready = _count(base.filter(Proxy.status == "alive", Proxy.web_https_ok.is_(True)))
    dns_ready = _count(base.filter(Proxy.status == "alive", Proxy.remote_dns_ok.is_(True)))
    telegram_ready = _count(base.filter(Proxy.status == "alive", Proxy.web_https_ok.is_(True), Proxy.telegram_ok.is_(True)))
    full_capability = _count(
        base.filter(
            Proxy.status == "alive",
            Proxy.web_https_ok.is_(True),
            Proxy.remote_dns_ok.is_(True),
            Proxy.telegram_ok.is_(True),
        )
    )

    tested = max(0, total - status_counts["untested"])
    unstable = sum(status_counts[key] for key in ("flaky", "soft", "cooling", "revived", "semi-revived"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    freshness = {
        "under_1h": _count(base.filter(Proxy.last_checked >= hour_ago)),
        "one_to_24h": _count(base.filter(Proxy.last_checked < hour_ago, Proxy.last_checked >= day_ago)),
        "one_to_7d": _count(base.filter(Proxy.last_checked < day_ago, Proxy.last_checked >= week_ago)),
        "older_7d": _count(base.filter(Proxy.last_checked < week_ago)),
        "never": _count(base.filter(Proxy.last_checked.is_(None))),
    }

    alive_base = base.filter(Proxy.status == "alive")
    latency_bands = {
        "fast": _count(alive_base.filter(Proxy.speed_ms.isnot(None), Proxy.speed_ms <= 300)),
        "balanced": _count(alive_base.filter(Proxy.speed_ms > 300, Proxy.speed_ms <= 800)),
        "slow": _count(alive_base.filter(Proxy.speed_ms > 800)),
        "unknown": _count(alive_base.filter(Proxy.speed_ms.is_(None))),
    }
    reliability_bands = {
        "high": _count(alive_base.filter(Proxy.reliability >= 0.9)),
        "medium": _count(alive_base.filter(Proxy.reliability >= 0.6, Proxy.reliability < 0.9)),
        "low": _count(alive_base.filter(Proxy.reliability.isnot(None), Proxy.reliability < 0.6)),
        "unknown": _count(alive_base.filter(Proxy.reliability.is_(None))),
    }

    top_country_share = _percentage(by_country[0]["count"], total) if by_country else 0.0
    top_isp_share = _percentage(by_isp[0]["count"], total) if by_isp else 0.0

    return jsonify(
        {
            "success": True,
            "total": total,
            **status_counts,
            "by_protocol": by_protocol,
            "by_country": by_country,
            "by_isp": by_isp,
            "protocol_stats": protocol_stats,
            "avg_speed": round(avg_speed, 0) if avg_speed else 0,
            "last_scan": last_scan,
            "web_ready": web_ready,
            "dns_ready": dns_ready,
            "telegram_ready": telegram_ready,
            "full_capability": full_capability,
            "quality": {
                "tested": tested,
                "stable": status_counts["alive"],
                "unstable": unstable,
                "unavailable": status_counts["dead"],
                "pending": status_counts["untested"],
                "success_rate": _percentage(status_counts["alive"], tested),
                "web_rate": _percentage(web_ready, status_counts["alive"]),
                "dns_rate": _percentage(dns_ready, status_counts["alive"]),
                "telegram_rate": _percentage(telegram_ready, status_counts["alive"]),
                "full_rate": _percentage(full_capability, status_counts["alive"]),
            },
            "freshness": freshness,
            "latency_bands": latency_bands,
            "reliability_bands": reliability_bands,
            "concentration": {
                "top_country_share": top_country_share,
                "top_isp_share": top_isp_share,
                "country_count": len(by_country),
                "isp_count": len(by_isp),
            },
        }
    )
