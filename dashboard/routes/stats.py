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
        .limit(15)
        .all()
    )
    by_isp = [{"isp": row[0], "count": row[1]} for row in by_isp_rows]

    avg_speed = base.with_entities(func.avg(Proxy.speed_ms)).filter(Proxy.speed_ms.isnot(None)).scalar()
    last_scan = base.with_entities(func.max(Proxy.last_checked)).scalar()

    protocol_stats = {}
    for protocol in PROTOCOLS:
        protocol_query = base.filter(Proxy.protocol == protocol)
        protocol_stats[protocol] = {
            "alive": _count(protocol_query.filter(Proxy.status == "alive")),
            "flaky": _count(protocol_query.filter(Proxy.status == "flaky")),
            "soft": _count(protocol_query.filter(Proxy.status == "soft")),
            "cooling": _count(protocol_query.filter(Proxy.status == "cooling")),
            "dead": _count(protocol_query.filter(Proxy.status == "dead")),
            "untested": _count(protocol_query.filter(or_(Proxy.status == "untested", Proxy.status.is_(None)))),
            "revived": _count(protocol_query.filter(Proxy.status == "revived")),
            "semi-revived": _count(protocol_query.filter(Proxy.status == "semi-revived")),
            "last_check": protocol_query.with_entities(func.max(Proxy.last_checked)).scalar(),
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
        }
    )
