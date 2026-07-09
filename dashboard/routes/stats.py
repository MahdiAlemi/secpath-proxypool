import os
import shutil
from datetime import datetime
from flask import Blueprint, request, jsonify

from dashboard.decorators import login_required
from dashboard.config import DB_PATH, PROTOCOLS, USERS

stats_bp = Blueprint('stats', __name__)


def get_db():
    from flask import g
    if "db_session" not in g:
        from database import db
        g.db_session = db.get_session()
    return g.db_session


@stats_bp.route("/api/stats", methods=["GET"])
@login_required
def api_stats():
    from sqlalchemy import func, or_
    from database import Proxy
    
    session = get_db()

    total = session.query(func.count(Proxy.id)).scalar()
    alive = session.query(func.count(Proxy.id)).filter(Proxy.status == 'alive').scalar()
    flaky = session.query(func.count(Proxy.id)).filter(Proxy.status == 'flaky').scalar()
    soft = session.query(func.count(Proxy.id)).filter(Proxy.status == 'soft').scalar()
    cooling = session.query(func.count(Proxy.id)).filter(Proxy.status == 'cooling').scalar()
    dead = session.query(func.count(Proxy.id)).filter(Proxy.status == 'dead').scalar()
    untested = session.query(func.count(Proxy.id)).filter(or_(Proxy.status == 'untested', Proxy.status.is_(None))).scalar()
    revived = session.query(func.count(Proxy.id)).filter(Proxy.status == 'revived').scalar()
    semi_alived = session.query(func.count(Proxy.id)).filter(Proxy.status == 'semi-revived').scalar()

    by_protocol = {}
    for p in PROTOCOLS:
        cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p).scalar()
        by_protocol[p] = cnt

    by_country = session.query(Proxy.countryCode, func.count(Proxy.id)).filter(
        Proxy.countryCode.isnot(None), Proxy.countryCode != ''
    ).group_by(Proxy.countryCode).order_by(func.count(Proxy.id).desc()).limit(10).all()
    by_country = [{"country": r[0], "count": r[1]} for r in by_country]

    avg_speed = session.query(func.avg(Proxy.speed_ms)).filter(Proxy.speed_ms.isnot(None)).scalar()

    last_scan = session.query(func.max(Proxy.last_checked)).scalar()

    protocol_stats = {}
    for p in PROTOCOLS:
        alive_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'alive').scalar()
        flaky_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'flaky').scalar()
        soft_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'soft').scalar()
        cooling_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'cooling').scalar()
        dead_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'dead').scalar()
        untested_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, or_(Proxy.status == 'untested', Proxy.status.is_(None))).scalar()
        revived_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'revived').scalar()
        semi_alived_cnt = session.query(func.count(Proxy.id)).filter(Proxy.protocol == p, Proxy.status == 'semi-revived').scalar()
        last_check = session.query(func.max(Proxy.last_checked)).filter(Proxy.protocol == p).scalar()
        protocol_stats[p] = {"alive": alive_cnt, "flaky": flaky_cnt, "soft": soft_cnt, "cooling": cooling_cnt, "dead": dead_cnt, "untested": untested_cnt, "revived": revived_cnt, "semi-revived": semi_alived_cnt, "last_check": last_check}

    by_isp = session.query(Proxy.isp, func.count(Proxy.id)).filter(
        Proxy.isp.isnot(None), Proxy.isp != ''
    ).group_by(Proxy.isp).order_by(func.count(Proxy.id).desc()).limit(15).all()
    by_isp = [{"isp": r[0], "count": r[1]} for r in by_isp]

    return jsonify({
        "total": total,
        "alive": alive,
        "flaky": flaky,
        "soft": soft,
        "cooling": cooling,
        "dead": dead,
        "untested": untested,
        "revived": revived,
        "semi-revived": semi_alived,
        "by_protocol": by_protocol,
        "by_country": by_country,
        "by_isp": by_isp,
        "protocol_stats": protocol_stats,
        "avg_speed": round(avg_speed, 0) if avg_speed else 0,
        "last_scan": last_scan
    })
