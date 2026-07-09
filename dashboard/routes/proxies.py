from flask import Blueprint, request, jsonify, g
from sqlalchemy import or_, desc, asc
from database import Proxy
from proxy_monitor.utils.validation import validate_proxy
from proxy_importer.utils.importer import normalize_proxy_line

from dashboard.decorators import login_required, require_permission, get_user_proxy_filters, get_current_user
from dashboard.utils.helpers import clamp_int

proxies_bp = Blueprint('proxies', __name__)


def get_db():
    """Get database session from Flask g object"""
    if "db_session" not in g:
        from database import db
        g.db_session = db.get_session()
    return g.db_session


@proxies_bp.route("/api/proxies", methods=["GET"])
@login_required
@require_permission("proxies.view")
def api_proxies():
    session = get_db()
    page = clamp_int(request.args.get("page", 1), 1)
    page_size_raw = request.args.get("page_size", "50")
    page_size = clamp_int(page_size_raw, 50, 1, 1000)
    proto = request.args.get("proto", "all")
    status = request.args.get("status", "all")
    sort_col = request.args.get("sort_col", "cost")
    sort_order = request.args.get("sort_order", "asc")
    search = request.args.get("search", "")
    ip_filter = request.args.get("ip", "")
    country_filter = request.args.get("country", "")
    isp_filter = request.args.get("isp", "")
    adv_search_json = request.args.get("adv_search", "[]")
    capability = request.args.get("capability", "")

    query = session.query(Proxy)

    # Apply user proxy filters (status and protocol restrictions)
    user = get_current_user()
    if user:
        user_filters = get_user_proxy_filters(user)
        # If user has status filter, apply it
        if user_filters["statuses"]:
            query = query.filter(Proxy.status.in_(user_filters["statuses"]))
        # If user has protocol filter, apply it
        if user_filters["protocols"]:
            query = query.filter(Proxy.protocol.in_(user_filters["protocols"]))

    if proto != "all":
        query = query.filter(Proxy.protocol == proto)

    if status and status != "all":
        statuses = [s.strip() for s in status.split(',')]
        status_conditions = []
        for s in statuses:
            if s == "untested":
                status_conditions.append(or_(Proxy.status == 'untested', Proxy.status.is_(None)))
            else:
                status_conditions.append(Proxy.status == s)
        if status_conditions:
            query = query.filter(or_(*status_conditions))

    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            Proxy.ip.like(search_term),
            Proxy.countryCode.like(search_term),
            Proxy.isp.like(search_term),
            Proxy.city.like(search_term),
            Proxy.regionName.like(search_term)
        ))

    if ip_filter:
        query = query.filter(Proxy.ip.like(f"%{ip_filter}%"))
    
    if country_filter:
        query = query.filter(Proxy.countryCode.like(f"%{country_filter}%"))
    
    if isp_filter:
        query = query.filter(Proxy.isp.like(f"%{isp_filter}%"))

    if capability:
        caps = {c.strip() for c in capability.split(',') if c.strip()}
        if 'web_https' in caps:
            query = query.filter(Proxy.web_https_ok == True)
        if 'remote_dns' in caps:
            query = query.filter(Proxy.remote_dns_ok == True)
        if 'telegram' in caps:
            query = query.filter(Proxy.telegram_ok == True)

    import json
    try:
        adv_rules = json.loads(adv_search_json)
        for rule in adv_rules:
            col = rule.get('column', '')
            op = rule.get('operator', 'contains')
            val = rule.get('value', '')
            if not col or not val:
                continue
            column = getattr(Proxy, col, None)
            if column is None:
                continue
            if op == 'contains':
                query = query.filter(column.like(f"%{val}%"))
            elif op == 'equals':
                query = query.filter(column == val)
            elif op == 'starts':
                query = query.filter(column.like(f"{val}%"))
            elif op == 'gt':
                query = query.filter(column > val)
            elif op == 'lt':
                query = query.filter(column < val)
            elif op == 'gte':
                query = query.filter(column >= val)
            elif op == 'lte':
                query = query.filter(column <= val)
    except:
        pass

    total = query.count()
    pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    if sort_order.lower() == 'desc':
        query = query.order_by(desc(getattr(Proxy, sort_col, Proxy.cost)))
    else:
        query = query.order_by(asc(getattr(Proxy, sort_col, Proxy.cost)))

    proxies = query.offset(offset).limit(page_size).all()

    return jsonify({
        "proxies": [p.to_dict() for p in proxies],
        "total": total,
        "page": page,
        "pages": pages
    })


@proxies_bp.route("/api/proxies", methods=["POST"])
@login_required
@require_permission("proxies.add")
def api_proxies_add():
    session = get_db()
    data = request.json
    try:
        proxy = Proxy(
            protocol=data.get("protocol"),
            ip=data.get("ip"),
            port=data.get("port"),
            username=data.get("username", ""),
            password=data.get("password", ""),
            cost=1.0
        )
        session.add(proxy)
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "error": str(e)})


@proxies_bp.route("/api/proxies/bulk", methods=["POST"])
@login_required
@require_permission("proxies.add")
def api_proxies_bulk():
    session = get_db()
    data = request.json
    lines = data.get("proxies", "").strip().split("\n")
    added = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = normalize_proxy_line(line, "http")
        if parsed:
            proto, ip, port, user, pwd = parsed
            user = user or ""
            pwd = pwd or ""
            try:
                existing = session.query(Proxy).filter_by(
                    protocol=proto, ip=ip, port=port, username=user, password=pwd
                ).first()
                if not existing:
                    proxy = Proxy(protocol=proto, ip=ip, port=port, username=user, password=pwd, cost=1.0)
                    session.add(proxy)
                    added += 1
            except:
                pass
    session.commit()
    return jsonify({"success": True, "added": added})


@proxies_bp.route("/api/proxies/<int:proxy_id>", methods=["DELETE"])
@login_required
@require_permission("proxies.delete")
def api_proxies_delete(proxy_id):
    session = get_db()
    try:
        proxy = session.query(Proxy).filter_by(id=proxy_id).first()
        if proxy:
            session.delete(proxy)
            session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "error": str(e)})


@proxies_bp.route("/api/proxies/<int:proxy_id>", methods=["PUT"])
@login_required
@require_permission("proxies.edit")
def api_proxies_update(proxy_id):
    session = get_db()
    data = request.json
    try:
        proxy = session.query(Proxy).filter_by(id=proxy_id).first()
        if proxy:
            proxy.protocol = data.get("protocol", proxy.protocol)
            proxy.ip = data.get("ip", proxy.ip)
            proxy.port = data.get("port", proxy.port)
            proxy.username = data.get("username", "")
            proxy.password = data.get("password", "")
            session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "error": str(e)})


@proxies_bp.route("/api/proxies/test/<int:proxy_id>", methods=["POST"])
@login_required
@require_permission("proxies.test")
def api_proxies_test(proxy_id):
    session = get_db()
    proxy = session.query(Proxy).filter_by(id=proxy_id).first()
    if not proxy:
        return jsonify({"success": False, "error": "Proxy not found"})

    try:
        summary = validate_proxy(proxy.to_dict(), timeout=5, telegram=True)
        proxy.web_http_ok = bool(summary.get("web_http_ok"))
        proxy.web_https_ok = bool(summary.get("web_https_ok"))
        proxy.remote_dns_ok = bool(summary.get("remote_dns_ok"))
        proxy.telegram_ok = bool(summary.get("telegram_ok"))
        proxy.exit_ip = summary.get("exit_ip")
        proxy.validation_profile = "telegram" if proxy.telegram_ok else ("web" if proxy.web_https_ok else "basic")
        proxy.validation_summary = summary
        session.commit()
        return jsonify({
            "success": True,
            "result": "alive" if summary.get("ok") else "dead",
            "response": summary.get("exit_ip") or "",
            "validation": summary
        })
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "result": "dead", "error": str(e)})


@proxies_bp.route("/api/proxies/delete", methods=["POST"])
@login_required
@require_permission("proxies.delete")
def api_proxies_bulk_delete():
    session = get_db()
    data = request.json
    
    try:
        query = session.query(Proxy)
        
        filter_type = data.get("filter", "all")
        protocol = data.get("protocol", "all")
        status = data.get("status", "all")
        
        if protocol != "all":
            query = query.filter(Proxy.protocol == protocol)
        
        if status != "all":
            if status == "untested":
                query = query.filter(or_(Proxy.status == 'untested', Proxy.status.is_(None)))
            else:
                query = query.filter(Proxy.status == status)
        
        count = query.count()
        
        if count == 0:
            return jsonify({"success": False, "error": "No proxies match the criteria", "deleted": 0})
        
        query.delete(synchronize_session=False)
        session.commit()
        
        return jsonify({"success": True, "deleted": count})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "error": str(e), "deleted": 0})


@proxies_bp.route("/api/proxies/my-filters", methods=["GET"])
@login_required
@require_permission("proxies.view")
def api_proxies_my_filters():
    """Get current user's proxy visibility filters"""
    user = get_current_user()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    filters = get_user_proxy_filters(user)
    return jsonify(filters)
