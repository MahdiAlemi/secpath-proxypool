import json

from flask import Blueprint, g, jsonify, request
from sqlalchemy import asc, desc, or_
from sqlalchemy.exc import IntegrityError

from dashboard.config import PROTOCOLS
from dashboard.decorators import (
    get_current_user,
    get_user_proxy_filters,
    has_permission,
    login_required,
    require_permission,
)
from dashboard.proxy_scope import (
    SAFE_FILTER_COLUMNS,
    apply_proxy_scope,
    public_proxy_dict,
)
from dashboard.security import api_error
from dashboard.utils.helpers import clamp_int
from database import Proxy
from proxy_importer.utils.importer import normalize_proxy_line
from proxy_monitor.utils.validation import validate_proxy

proxies_bp = Blueprint("proxies", __name__)


def get_db():
    if "db_session" not in g:
        from database import db

        g.db_session = db.get_session()
    return g.db_session


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def validate_proxy_payload(data, *, partial=False):
    if not isinstance(data, dict):
        return None, "A JSON object is required"

    result = {}
    if not partial or "protocol" in data:
        protocol = str(data.get("protocol", "")).strip().lower()
        if protocol not in PROTOCOLS:
            return None, f"protocol must be one of: {', '.join(PROTOCOLS)}"
        result["protocol"] = protocol

    if not partial or "ip" in data:
        host = str(data.get("ip", "")).strip()
        if not host or len(host) > 255 or any(char.isspace() for char in host):
            return None, "ip/host is required and must not contain whitespace"
        result["ip"] = host

    if not partial or "port" in data:
        try:
            port = int(data.get("port"))
        except (TypeError, ValueError):
            return None, "port must be an integer between 1 and 65535"
        if not 1 <= port <= 65535:
            return None, "port must be an integer between 1 and 65535"
        result["port"] = port

    for field in ("username", "password"):
        if field in data:
            value = str(data.get(field, "") or "")
            if len(value) > 255:
                return None, f"{field} must be at most 255 characters"
            result[field] = value
        elif not partial:
            result[field] = ""

    return result, None


def _apply_requested_filters(query):
    proto = request.args.get("proto", "all")
    status = request.args.get("status", "all")
    search = request.args.get("search", "").strip()[:255]
    ip_filter = request.args.get("ip", "").strip()[:255]
    country_filter = request.args.get("country", "").strip()[:32]
    isp_filter = request.args.get("isp", "").strip()[:255]
    capability = request.args.get("capability", "")

    if proto != "all" and proto in PROTOCOLS:
        query = query.filter(Proxy.protocol == proto)

    if status and status != "all":
        conditions = []
        for value in [part.strip() for part in status.split(",") if part.strip()]:
            if value == "untested":
                conditions.append(or_(Proxy.status == "untested", Proxy.status.is_(None)))
            else:
                conditions.append(Proxy.status == value)
        if conditions:
            query = query.filter(or_(*conditions))

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Proxy.ip.like(like),
                Proxy.countryCode.like(like),
                Proxy.isp.like(like),
                Proxy.city.like(like),
                Proxy.regionName.like(like),
            )
        )
    if ip_filter:
        query = query.filter(Proxy.ip.like(f"%{ip_filter}%"))
    if country_filter:
        query = query.filter(Proxy.countryCode.like(f"%{country_filter}%"))
    if isp_filter:
        query = query.filter(Proxy.isp.like(f"%{isp_filter}%"))

    capabilities = {item.strip() for item in capability.split(",") if item.strip()}
    if "web_https" in capabilities:
        query = query.filter(Proxy.web_https_ok.is_(True))
    if "remote_dns" in capabilities:
        query = query.filter(Proxy.remote_dns_ok.is_(True))
    if "telegram" in capabilities:
        query = query.filter(Proxy.telegram_ok.is_(True))

    try:
        rules = json.loads(request.args.get("adv_search", "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        rules = []
    if not isinstance(rules, list):
        rules = []

    for rule in rules[:20]:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("column", ""))
        operator = str(rule.get("operator", "contains"))
        value = rule.get("value", "")
        if name not in SAFE_FILTER_COLUMNS or value in (None, ""):
            continue
        column = getattr(Proxy, name)
        if operator == "contains":
            query = query.filter(column.like(f"%{str(value)[:255]}%"))
        elif operator == "equals":
            query = query.filter(column == value)
        elif operator == "starts":
            query = query.filter(column.like(f"{str(value)[:255]}%"))
        elif operator == "gt":
            query = query.filter(column > value)
        elif operator == "lt":
            query = query.filter(column < value)
        elif operator == "gte":
            query = query.filter(column >= value)
        elif operator == "lte":
            query = query.filter(column <= value)
    return query


def _scoped_proxy(session, proxy_id):
    return apply_proxy_scope(session.query(Proxy)).filter(Proxy.id == proxy_id).first()


def _selection_ids(data, *, limit=500):
    if not isinstance(data, dict) or not isinstance(data.get("ids"), list):
        return None, "ids must be an array"
    if not data["ids"]:
        return None, "Select at least one proxy"
    if len(data["ids"]) > limit:
        return None, f"A maximum of {limit} proxies can be selected"

    result = []
    seen = set()
    for value in data["ids"]:
        if isinstance(value, bool):
            return None, "Proxy IDs must be positive integers"
        try:
            proxy_id = int(value)
        except (TypeError, ValueError):
            return None, "Proxy IDs must be positive integers"
        if proxy_id <= 0:
            return None, "Proxy IDs must be positive integers"
        if proxy_id not in seen:
            seen.add(proxy_id)
            result.append(proxy_id)
    return result, None


@proxies_bp.route("/api/proxies", methods=["GET"])
@login_required
@require_permission("proxies.view")
def api_proxies():
    db_session = get_db()
    page = clamp_int(request.args.get("page", 1), 1)
    page_size = clamp_int(request.args.get("page_size", "50"), 50, 1, 1000)
    sort_col = request.args.get("sort_col", "cost")
    sort_order = request.args.get("sort_order", "asc")
    if sort_col not in SAFE_FILTER_COLUMNS:
        sort_col = "cost"

    query = _apply_requested_filters(apply_proxy_scope(db_session.query(Proxy)))
    total = query.count()
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)

    order_column = getattr(Proxy, sort_col)
    query = query.order_by(desc(order_column) if sort_order.lower() == "desc" else asc(order_column))
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return jsonify(
        {
            "success": True,
            "proxies": [public_proxy_dict(proxy) for proxy in rows],
            "total": total,
            "page": page,
            "pages": pages,
        }
    )


@proxies_bp.route("/api/proxies/<int:proxy_id>", methods=["GET"])
@login_required
@require_permission("proxies.view")
def api_proxy_detail(proxy_id):
    db_session = get_db()
    proxy = _scoped_proxy(db_session, proxy_id)
    if not proxy:
        return api_error("Proxy not found", 404, "not_found")
    return jsonify({"success": True, "proxy": public_proxy_dict(proxy)})


@proxies_bp.route("/api/proxies", methods=["POST"])
@login_required
@require_permission("proxies.add")
def api_proxies_add():
    db_session = get_db()
    payload, error = validate_proxy_payload(_json_object())
    if error:
        return api_error(error, 400, "invalid_proxy")
    try:
        proxy = Proxy(**payload, cost=1.0)
        db_session.add(proxy)
        db_session.commit()
        return jsonify({"success": True, "id": proxy.id}), 201
    except IntegrityError:
        db_session.rollback()
        return api_error("Proxy already exists", 409, "duplicate_proxy")
    except Exception:
        db_session.rollback()
        return api_error("Could not add proxy", 500, "proxy_create_failed")


@proxies_bp.route("/api/proxies/bulk", methods=["POST"])
@login_required
@require_permission("proxies.add")
def api_proxies_bulk():
    db_session = get_db()
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    content = str(data.get("proxies", ""))
    if len(content) > 2_000_000:
        return api_error("Bulk proxy input is too large", 413, "payload_too_large")

    added = 0
    skipped = 0
    for line in content.splitlines()[:100_000]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = normalize_proxy_line(line, "http")
        if not parsed:
            skipped += 1
            continue
        protocol, ip, port, username, password = parsed
        payload, error = validate_proxy_payload(
            {
                "protocol": protocol,
                "ip": ip,
                "port": port,
                "username": username or "",
                "password": password or "",
            }
        )
        if error:
            skipped += 1
            continue
        exists = db_session.query(Proxy.id).filter_by(**payload).first()
        if exists:
            skipped += 1
            continue
        db_session.add(Proxy(**payload, cost=1.0))
        added += 1
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        return api_error("Bulk import contained conflicting rows", 409, "duplicate_proxy")
    return jsonify({"success": True, "added": added, "skipped": skipped})


@proxies_bp.route("/api/proxies/<int:proxy_id>", methods=["DELETE"])
@login_required
@require_permission("proxies.delete")
def api_proxies_delete(proxy_id):
    db_session = get_db()
    proxy = _scoped_proxy(db_session, proxy_id)
    if not proxy:
        return api_error("Proxy not found", 404, "not_found")
    try:
        db_session.delete(proxy)
        db_session.commit()
        return jsonify({"success": True})
    except Exception:
        db_session.rollback()
        return api_error("Could not delete proxy", 500, "proxy_delete_failed")


@proxies_bp.route("/api/proxies/<int:proxy_id>", methods=["PUT"])
@login_required
@require_permission("proxies.edit")
def api_proxies_update(proxy_id):
    db_session = get_db()
    data = _json_object()
    payload, error = validate_proxy_payload(data, partial=True)
    if error:
        return api_error(error, 400, "invalid_proxy")
    if any(key in payload for key in ("username", "password")) and not has_permission("proxies.credentials"):
        return api_error("Credential changes require proxies.credentials", 403, "permission_denied")

    proxy = _scoped_proxy(db_session, proxy_id)
    if not proxy:
        return api_error("Proxy not found", 404, "not_found")
    for key, value in payload.items():
        setattr(proxy, key, value)
    try:
        db_session.commit()
        return jsonify({"success": True})
    except IntegrityError:
        db_session.rollback()
        return api_error("Proxy already exists", 409, "duplicate_proxy")
    except Exception:
        db_session.rollback()
        return api_error("Could not update proxy", 500, "proxy_update_failed")


@proxies_bp.route("/api/proxies/test/<int:proxy_id>", methods=["POST"])
@login_required
@require_permission("proxies.test")
def api_proxies_test(proxy_id):
    db_session = get_db()
    proxy = _scoped_proxy(db_session, proxy_id)
    if not proxy:
        return api_error("Proxy not found", 404, "not_found")
    try:
        summary = validate_proxy(proxy.to_dict(), timeout=5, telegram=True)
        proxy.web_http_ok = bool(summary.get("web_http_ok"))
        proxy.web_https_ok = bool(summary.get("web_https_ok"))
        proxy.remote_dns_ok = bool(summary.get("remote_dns_ok"))
        proxy.telegram_ok = bool(summary.get("telegram_ok"))
        proxy.exit_ip = summary.get("exit_ip")
        proxy.validation_profile = "telegram" if proxy.telegram_ok else ("web" if proxy.web_https_ok else "basic")
        proxy.validation_summary = summary
        db_session.commit()
        return jsonify(
            {
                "success": True,
                "result": "alive" if summary.get("ok") else "dead",
                "response": summary.get("exit_ip") or "",
                "validation": summary,
            }
        )
    except Exception:
        db_session.rollback()
        return api_error("Proxy test failed", 502, "proxy_test_failed")


@proxies_bp.route("/api/proxies/selection/delete", methods=["POST"])
@login_required
@require_permission("proxies.delete")
def api_proxies_selection_delete():
    db_session = get_db()
    ids, error = _selection_ids(_json_object())
    if error:
        return api_error(error, 400, "invalid_selection")

    query = apply_proxy_scope(db_session.query(Proxy)).filter(Proxy.id.in_(ids))
    count = query.count()
    if count == 0:
        return api_error("No selected proxies are available", 404, "not_found")
    try:
        query.delete(synchronize_session=False)
        db_session.commit()
        return jsonify({"success": True, "deleted": count})
    except Exception:
        db_session.rollback()
        return api_error("Could not delete selected proxies", 500, "proxy_delete_failed")


@proxies_bp.route("/api/proxies/delete", methods=["POST"])
@login_required
@require_permission("proxies.delete")
def api_proxies_bulk_delete():
    db_session = get_db()
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")

    query = apply_proxy_scope(db_session.query(Proxy))
    protocol = str(data.get("protocol", "all"))
    status = str(data.get("status", "all"))
    if protocol != "all":
        if protocol not in PROTOCOLS:
            return api_error("Invalid protocol", 400, "invalid_filter")
        query = query.filter(Proxy.protocol == protocol)
    if status != "all":
        if status == "untested":
            query = query.filter(or_(Proxy.status == "untested", Proxy.status.is_(None)))
        else:
            query = query.filter(Proxy.status == status)

    count = query.count()
    if count == 0:
        return api_error("No proxies match the criteria", 404, "not_found")
    try:
        query.delete(synchronize_session=False)
        db_session.commit()
        return jsonify({"success": True, "deleted": count})
    except Exception:
        db_session.rollback()
        return api_error("Could not delete proxies", 500, "proxy_delete_failed")


@proxies_bp.route("/api/proxies/my-filters", methods=["GET"])
@login_required
@require_permission("proxies.view")
def api_proxies_my_filters():
    user = get_current_user()
    if not user:
        return api_error("User not found", 404, "not_found")
    return jsonify({"success": True, **get_user_proxy_filters(user)})
