import csv
import io
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from dashboard.config import PROTOCOLS
from dashboard.decorators import has_permission, login_required, require_permission
from dashboard.imports import (
    MAX_SOURCE_CONFIG_BYTES,
    ImportInputError,
    execute_import,
    parse_link_config,
    preview_import,
)
from dashboard.proxy_scope import (
    SAFE_FILTER_COLUMNS,
    apply_proxy_scope,
    credential_proxy_dict,
    public_proxy_dict,
)
from dashboard.security import api_error
from database import ImportRun, ImportSource, Proxy

import_export_bp = Blueprint("import_export", __name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    if "db_session" not in g:
        from database import db

        g.db_session = db.get_session()
    return g.db_session


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _source_import_data(source: ImportSource) -> dict:
    if source.mode == "url":
        return {
            "mode": "url",
            "protocol": source.protocol or "http",
            "url": source.source_url or "",
        }
    return {"mode": "links", "content": source.source_content or ""}


def _validate_http_url(value: str) -> str:
    value = str(value or "").strip()
    if len(value) > 2048:
        raise ImportInputError("Source URL is too long")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ImportInputError("Source URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ImportInputError("Source URL must use HTTP or HTTPS")
    return value


def _boolean_value(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ImportInputError("is_active must be a boolean")


def _source_fields(data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    if not 2 <= len(name) <= 100:
        raise ImportInputError("Source name must contain 2 to 100 characters")
    mode = str(data.get("mode", "url")).strip().lower()
    if mode not in {"url", "links"}:
        raise ImportInputError("Saved sources must use url or links mode")

    fields = {
        "name": name,
        "mode": mode,
        "protocol": None,
        "source_url": None,
        "source_content": None,
        "is_active": _boolean_value(data.get("is_active"), True),
    }
    if mode == "url":
        protocol = str(data.get("protocol", "http")).lower()
        if protocol not in PROTOCOLS:
            raise ImportInputError("Invalid protocol")
        fields["protocol"] = protocol
        fields["source_url"] = _validate_http_url(data.get("url", ""))
    else:
        content = str(data.get("content", ""))
        if not content.strip():
            raise ImportInputError("Source configuration is required")
        if len(content.encode("utf-8")) > MAX_SOURCE_CONFIG_BYTES:
            raise ImportInputError("Source configuration is too large")
        sources = parse_link_config(content)
        if not sources:
            raise ImportInputError("No valid source URLs found")
        for _protocol, url in sources:
            _validate_http_url(url)
        fields["source_content"] = content
    return fields


def _source_by_id(db_session, source_id: int):
    return db_session.query(ImportSource).filter_by(id=source_id).first()


def _run_record(result: dict, *, source=None, source_name=None) -> ImportRun:
    summary = result.get("summary", {})
    return ImportRun(
        source_id=source.id if source else None,
        source_name=(source.name if source else source_name) or None,
        mode=result.get("mode", "manual"),
        status=result.get("status", "completed"),
        total=summary.get("total_lines", 0),
        valid=summary.get("valid", 0),
        added=summary.get("added", 0),
        skipped=summary.get("skipped", 0),
        existing=summary.get("existing", 0),
        invalid=summary.get("invalid", 0),
        input_duplicates=summary.get("input_duplicates", 0),
        protocol_counts=result.get("protocols", {}),
        source_results=result.get("sources", []),
        error="; ".join(result.get("errors", [])[:5]) or None,
        created_by=g.get("user_id"),
        started_at=utcnow(),
        completed_at=utcnow(),
    )


def _failed_run(db_session, *, mode, error, source=None, source_name=None):
    run = ImportRun(
        source_id=source.id if source else None,
        source_name=(source.name if source else source_name) or None,
        mode=mode,
        status="failed",
        error=str(error)[:2000],
        created_by=g.get("user_id"),
        started_at=utcnow(),
        completed_at=utcnow(),
    )
    db_session.add(run)
    if source:
        source.last_run_at = utcnow()
        source.last_status = "failed"
        source.last_added = 0
        source.last_skipped = 0
        source.last_error = str(error)[:2000]
    db_session.commit()
    return run


def _perform_import(db_session, data: dict, *, source=None, source_name=None):
    result = execute_import(db_session, data)
    summary = result["summary"]
    if summary.get("valid", 0) == 0 and result.get("errors"):
        raise ImportInputError("No source could be imported: " + result["errors"][0])

    run = _run_record(result, source=source, source_name=source_name)
    db_session.add(run)
    if source:
        source.last_run_at = utcnow()
        source.last_status = result.get("status", "completed")
        source.last_added = summary.get("added", 0)
        source.last_skipped = summary.get("skipped", 0)
        source.last_error = "; ".join(result.get("errors", [])[:5]) or None
    db_session.commit()
    result.update(
        {
            "success": True,
            "run_id": run.id,
            "added": summary.get("added", 0),
            "skipped": summary.get("skipped", 0),
        }
    )
    return result


def _apply_export_filters(query):
    proto = request.args.get("proto", "all")
    status = request.args.get("status", "all")
    search = request.args.get("search", "").strip()[:255]
    ip_filter = request.args.get("ip", "").strip()[:255]
    country_filter = request.args.get("country", "").strip()[:32]
    isp_filter = request.args.get("isp", "").strip()[:255]

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
        value = f"%{search}%"
        query = query.filter(
            or_(
                Proxy.ip.like(value),
                Proxy.countryCode.like(value),
                Proxy.isp.like(value),
                Proxy.city.like(value),
                Proxy.regionName.like(value),
            )
        )
    if ip_filter:
        query = query.filter(Proxy.ip.like(f"%{ip_filter}%"))
    if country_filter:
        query = query.filter(Proxy.countryCode.like(f"%{country_filter}%"))
    if isp_filter:
        query = query.filter(Proxy.isp.like(f"%{isp_filter}%"))

    capabilities = {item.strip() for item in request.args.get("capability", "").split(",") if item.strip()}
    if "web_https" in capabilities:
        query = query.filter(Proxy.web_https_ok.is_(True))
    if "remote_dns" in capabilities:
        query = query.filter(Proxy.remote_dns_ok.is_(True))
    if "telegram" in capabilities:
        query = query.filter(Proxy.telegram_ok.is_(True))
    return query


def _csv_value(value):
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@import_export_bp.route("/api/import/preview", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_preview():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        result = preview_import(get_db(), data)
        result["success"] = True
        return jsonify(result)
    except (requests.RequestException, ImportInputError, ValueError) as exc:
        return api_error(str(exc), 400, "import_preview_failed")
    except Exception:
        return api_error("Could not preview import", 500, "import_preview_failed")


@import_export_bp.route("/api/import", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    db_session = get_db()
    try:
        source_name = str(data.get("source_name", "")).strip()[:100] or None
        return jsonify(_perform_import(db_session, data, source_name=source_name))
    except IntegrityError:
        db_session.rollback()
        return api_error("Import contained conflicting rows", 409, "duplicate_proxy")
    except (requests.RequestException, ImportInputError, ValueError) as exc:
        db_session.rollback()
        return api_error(str(exc), 400, "import_failed")
    except Exception:
        db_session.rollback()
        return api_error("Import failed", 500, "import_failed")


@import_export_bp.route("/api/import/count-url", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_count_url():
    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        payload = {
            "mode": "url",
            "protocol": data.get("protocol", "http"),
            "url": data.get("url", ""),
        }
        result = preview_import(get_db(), payload)
        return jsonify({"success": True, "count": result["summary"]["valid"], "summary": result["summary"]})
    except (requests.RequestException, ImportInputError, ValueError) as exc:
        return api_error(str(exc), 400, "source_fetch_failed")
    except Exception:
        return api_error("Could not inspect source", 500, "source_fetch_failed")


@import_export_bp.route("/api/import/sources", methods=["GET", "POST"])
@login_required
@require_permission("proxies.import")
def api_import_sources():
    db_session = get_db()
    if request.method == "GET":
        rows = db_session.query(ImportSource).order_by(ImportSource.updated_at.desc(), ImportSource.id.desc()).all()
        return jsonify({"success": True, "sources": [row.to_dict() for row in rows]})

    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        fields = _source_fields(data)
        duplicate = (
            db_session.query(ImportSource.id)
            .filter(func.lower(ImportSource.name) == fields["name"].lower())
            .first()
        )
        if duplicate:
            return api_error("A source with this name already exists", 409, "duplicate_source")
        source = ImportSource(**fields, created_by=g.get("user_id"))
        db_session.add(source)
        db_session.commit()
        return jsonify({"success": True, "source": source.to_dict(include_config=True)}), 201
    except ImportInputError as exc:
        db_session.rollback()
        return api_error(str(exc), 400, "invalid_source")
    except Exception:
        db_session.rollback()
        return api_error("Could not save source", 500, "source_save_failed")


@import_export_bp.route("/api/import/sources/<int:source_id>", methods=["GET", "PUT", "DELETE"])
@login_required
@require_permission("proxies.import")
def api_import_source(source_id):
    db_session = get_db()
    source = _source_by_id(db_session, source_id)
    if not source:
        return api_error("Source not found", 404, "source_not_found")
    if request.method == "GET":
        return jsonify({"success": True, "source": source.to_dict(include_config=True)})
    if request.method == "DELETE":
        db_session.delete(source)
        db_session.commit()
        return jsonify({"success": True, "deleted": source_id})

    data = _json_object()
    if data is None:
        return api_error("A JSON object is required", 400, "invalid_json")
    try:
        fields = _source_fields(data)
        duplicate = (
            db_session.query(ImportSource.id)
            .filter(
                ImportSource.id != source_id,
                func.lower(ImportSource.name) == fields["name"].lower(),
            )
            .first()
        )
        if duplicate:
            return api_error("A source with this name already exists", 409, "duplicate_source")
        for key, value in fields.items():
            setattr(source, key, value)
        source.updated_at = utcnow()
        db_session.commit()
        return jsonify({"success": True, "source": source.to_dict(include_config=True)})
    except ImportInputError as exc:
        db_session.rollback()
        return api_error(str(exc), 400, "invalid_source")
    except Exception:
        db_session.rollback()
        return api_error("Could not update source", 500, "source_save_failed")


@import_export_bp.route("/api/import/sources/<int:source_id>/preview", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_source_preview(source_id):
    db_session = get_db()
    source = _source_by_id(db_session, source_id)
    if not source:
        return api_error("Source not found", 404, "source_not_found")
    try:
        result = preview_import(db_session, _source_import_data(source))
        result.update({"success": True, "source": source.to_dict()})
        return jsonify(result)
    except (requests.RequestException, ImportInputError, ValueError) as exc:
        return api_error(str(exc), 400, "import_preview_failed")
    except Exception:
        return api_error("Could not preview source", 500, "import_preview_failed")


@import_export_bp.route("/api/import/sources/<int:source_id>/run", methods=["POST"])
@login_required
@require_permission("proxies.import")
def api_import_source_run(source_id):
    db_session = get_db()
    source = _source_by_id(db_session, source_id)
    if not source:
        return api_error("Source not found", 404, "source_not_found")
    if not source.is_active:
        return api_error("Source is disabled", 409, "source_disabled")
    try:
        result = _perform_import(db_session, _source_import_data(source), source=source)
        result["source"] = source.to_dict()
        return jsonify(result)
    except (requests.RequestException, ImportInputError, ValueError) as exc:
        db_session.rollback()
        _failed_run(db_session, mode=source.mode, error=exc, source=source)
        return api_error(str(exc), 400, "import_failed")
    except Exception:
        db_session.rollback()
        _failed_run(db_session, mode=source.mode, error="Import failed", source=source)
        return api_error("Import failed", 500, "import_failed")


@import_export_bp.route("/api/import/runs", methods=["GET"])
@login_required
@require_permission("proxies.import")
def api_import_runs():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    limit = min(100, max(1, limit))
    rows = get_db().query(ImportRun).order_by(ImportRun.started_at.desc(), ImportRun.id.desc()).limit(limit).all()
    return jsonify({"success": True, "runs": [row.to_dict() for row in rows]})


@import_export_bp.route("/api/export", methods=["GET"])
@login_required
@require_permission("proxies.export")
def api_export():
    fmt = request.args.get("format", "txt").lower()
    if fmt not in {"txt", "csv", "json"}:
        return api_error("format must be txt, csv, or json", 400, "invalid_format")

    include_credentials = request.args.get("include_credentials", "false").lower() in {"1", "true", "yes"}
    if include_credentials and not has_permission("proxies.credentials"):
        return api_error("Credential export requires proxies.credentials", 403, "permission_denied")

    db_session = get_db()
    rows = _apply_export_filters(apply_proxy_scope(db_session.query(Proxy))).all()
    serializer = credential_proxy_dict if include_credentials else public_proxy_dict

    requested = [item.strip() for item in request.args.get("columns", "").split(",") if item.strip()]
    column_map = {
        "protocol": "protocol",
        "port": "port",
        "cost": "cost",
        "speed": "speed_ms",
        "alive": "alive_hits",
        "fails": "fail_hits",
        "country": "countryCode",
        "region": "regionName",
        "city": "city",
        "isp": "isp",
        "asn": "asn",
        "org": "org",
        "mobile": "mobile",
        "hosting": "hosting",
        "lastalive": "last_alive",
        "lastcheck": "last_checked",
    }
    selected = ["ip"] + [column_map[item] for item in requested if item in column_map] if requested else None

    data = []
    for proxy in rows:
        item = serializer(proxy)
        if selected:
            item = {key: item.get(key) for key in selected if key in SAFE_FILTER_COLUMNS or key == "ip"}
        if include_credentials and proxy.username and proxy.password:
            item["proxy_url"] = f"{proxy.protocol}://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        data.append(item)

    if fmt == "json":
        return jsonify({"success": True, "count": len(data), "proxies": data})

    if not data:
        return Response("", mimetype="text/csv" if fmt == "csv" else "text/plain")

    output = io.StringIO(newline="")
    fields = list(data[0].keys())
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if fmt == "csv":
        writer.writeheader()
    for item in data:
        writer.writerow({key: _csv_value(item.get(key)) for key in fields})

    content_type = "text/csv; charset=utf-8" if fmt == "csv" else "text/plain; charset=utf-8"
    response = Response(output.getvalue(), content_type=content_type)
    response.headers["Content-Disposition"] = f'attachment; filename="proxies.{fmt}"'
    return response
