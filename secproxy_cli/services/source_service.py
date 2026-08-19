from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _lookup_source(session, identifier: str):
    from database import ImportSource

    value = str(identifier).strip()
    if value.isdigit():
        source = session.query(ImportSource).filter(ImportSource.id == int(value)).first()
        if source is not None:
            return source
    return (
        session.query(ImportSource)
        .filter(func.lower(ImportSource.name) == value.lower())
        .first()
    )


def _safe_source_dict(source, *, include_config: bool = False) -> dict[str, Any]:
    item = source.to_dict(include_config=include_config)
    # Source URLs can contain credentials/query tokens. Keep normal CLI display redacted.
    if include_config:
        from dashboard.imports import redact_source_url

        if item.get("url"):
            item["url"] = redact_source_url(item["url"])
        if item.get("content"):
            safe_lines: list[str] = []
            for raw in str(item["content"]).splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith(("#", ";", "[")):
                    safe_lines.append(raw)
                else:
                    safe_lines.append(redact_source_url(stripped))
            item["content"] = "\n".join(safe_lines)
    return item


def _source_import_data(source) -> dict[str, Any]:
    if source.mode == "url":
        return {
            "mode": "url",
            "protocol": source.protocol or "http",
            "url": source.source_url or "",
        }
    return {"mode": "links", "content": source.source_content or ""}


def _validate_http_url(value: str) -> str:
    from dashboard.imports import ImportInputError

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


def _source_fields(
    *,
    name: str,
    mode: str,
    protocol: str | None,
    url: str | None,
    content: str | None,
    is_active: bool,
) -> dict[str, Any]:
    from dashboard.config import PROTOCOLS
    from dashboard.imports import MAX_SOURCE_CONFIG_BYTES, ImportInputError, parse_link_config

    clean_name = str(name or "").strip()
    if not 2 <= len(clean_name) <= 100:
        raise ImportInputError("Source name must contain 2 to 100 characters")

    clean_mode = str(mode or "url").strip().lower()
    if clean_mode not in {"url", "links"}:
        raise ImportInputError("Saved sources must use url or links mode")

    fields: dict[str, Any] = {
        "name": clean_name,
        "mode": clean_mode,
        "protocol": None,
        "source_url": None,
        "source_content": None,
        "is_active": bool(is_active),
    }

    if clean_mode == "url":
        clean_protocol = str(protocol or "http").lower()
        if clean_protocol not in PROTOCOLS:
            raise ImportInputError("Invalid protocol")
        fields["protocol"] = clean_protocol
        fields["source_url"] = _validate_http_url(str(url or ""))
        return fields

    clean_content = str(content or "")
    if not clean_content.strip():
        raise ImportInputError("Source configuration is required")
    if len(clean_content.encode("utf-8")) > MAX_SOURCE_CONFIG_BYTES:
        raise ImportInputError("Source configuration is too large")
    sources = parse_link_config(clean_content)
    if not sources:
        raise ImportInputError("No valid source URLs found")
    for _protocol, source_url in sources:
        _validate_http_url(source_url)
    fields["source_content"] = clean_content
    return fields


def list_sources(*, active: bool | None = None) -> list[dict[str, Any]]:
    from database import ImportSource, db

    with db.session() as session:
        query = session.query(ImportSource)
        if active is not None:
            query = query.filter(ImportSource.is_active.is_(active))
        rows = query.order_by(ImportSource.updated_at.desc(), ImportSource.id.desc()).all()
        return [_safe_source_dict(row) for row in rows]


def get_source(identifier: str) -> dict[str, Any] | None:
    from database import db

    with db.session() as session:
        source = _lookup_source(session, identifier)
        if source is None:
            return None
        return _safe_source_dict(source, include_config=True)


def add_source(
    *,
    name: str,
    mode: str,
    protocol: str | None = None,
    url: str | None = None,
    content: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    from dashboard.imports import ImportInputError
    from database import ImportSource, db

    fields = _source_fields(
        name=name,
        mode=mode,
        protocol=protocol,
        url=url,
        content=content,
        is_active=is_active,
    )
    with db.session() as session:
        duplicate = (
            session.query(ImportSource.id)
            .filter(func.lower(ImportSource.name) == fields["name"].lower())
            .first()
        )
        if duplicate:
            raise ImportInputError("A source with this name already exists")
        source = ImportSource(**fields, created_by=None)
        session.add(source)
        session.flush()
        result = _safe_source_dict(source, include_config=True)
    return result


def set_source_active(identifier: str, active: bool) -> dict[str, Any] | None:
    from database import db

    with db.session() as session:
        source = _lookup_source(session, identifier)
        if source is None:
            return None
        source.is_active = active
        source.updated_at = utcnow()
        session.flush()
        return _safe_source_dict(source)


def delete_source(identifier: str) -> dict[str, Any] | None:
    from database import db

    with db.session() as session:
        source = _lookup_source(session, identifier)
        if source is None:
            return None
        result = {"id": source.id, "name": source.name}
        session.delete(source)
        return result


def preview_source(identifier: str) -> dict[str, Any] | None:
    from dashboard.imports import preview_import
    from database import db

    with db.session() as session:
        source = _lookup_source(session, identifier)
        if source is None:
            return None
        result = preview_import(session, _source_import_data(source))
        result["source"] = _safe_source_dict(source)
        return result


def preview_input(
    *,
    mode: str,
    protocol: str = "http",
    url: str | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    from dashboard.imports import preview_import
    from database import db

    data = _import_payload(mode=mode, protocol=protocol, url=url, content=content)
    with db.session() as session:
        return preview_import(session, data)


def import_input(
    *,
    mode: str,
    protocol: str = "http",
    url: str | None = None,
    content: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    from database import db

    data = _import_payload(mode=mode, protocol=protocol, url=url, content=content)
    with db.session() as session:
        return _perform_import(session, data, source=None, source_name=source_name)


def run_source(identifier: str) -> dict[str, Any] | None:
    from dashboard.imports import ImportInputError
    from database import db

    with db.session() as session:
        source = _lookup_source(session, identifier)
        if source is None:
            return None
        if not source.is_active:
            raise ImportInputError("Source is disabled")
        try:
            result = _perform_import(session, _source_import_data(source), source=source)
        except Exception as exc:
            # Clear any partial transaction state before recording a durable failed run.
            session.rollback()
            source = _lookup_source(session, identifier)
            if source is not None:
                source.last_run_at = utcnow()
                source.last_status = "failed"
                source.last_added = 0
                source.last_skipped = 0
                source.last_error = str(exc)[:2000]
                _record_failed_run(session, source=source, error=exc)
                session.commit()
            raise
        result["source"] = _safe_source_dict(source)
        return result


def import_history(*, limit: int = 20, source: str | None = None) -> list[dict[str, Any]]:
    from database import ImportRun, db

    with db.session() as session:
        query = session.query(ImportRun)
        if source:
            source_row = _lookup_source(session, source)
            if source_row is not None:
                query = query.filter(ImportRun.source_id == source_row.id)
            else:
                query = query.filter(func.lower(ImportRun.source_name) == source.lower())
        rows = query.order_by(ImportRun.started_at.desc(), ImportRun.id.desc()).limit(limit).all()
        return [row.to_dict() for row in rows]


def read_text_file(path: Path) -> str:
    from dashboard.imports import ImportInputError, MAX_SOURCE_BYTES

    path = path.expanduser()
    if not path.is_file():
        raise ImportInputError(f"File not found: {path}")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ImportInputError("Manual import is larger than 2 MB")
    return path.read_text(encoding="utf-8", errors="replace")


def read_links_file(path: Path) -> str:
    from dashboard.imports import ImportInputError, MAX_SOURCE_CONFIG_BYTES

    path = path.expanduser()
    if not path.is_file():
        raise ImportInputError(f"File not found: {path}")
    size = path.stat().st_size
    if size > MAX_SOURCE_CONFIG_BYTES:
        raise ImportInputError("Source configuration is too large")
    return path.read_text(encoding="utf-8", errors="replace")


def _import_payload(
    *,
    mode: str,
    protocol: str,
    url: str | None,
    content: str | None,
) -> dict[str, Any]:
    clean_mode = mode.lower()
    if clean_mode == "url":
        return {"mode": "url", "protocol": protocol, "url": url or ""}
    if clean_mode == "links":
        return {"mode": "links", "content": content or ""}
    return {"mode": "manual", "protocol": protocol, "content": content or ""}


def _perform_import(session, data: dict[str, Any], *, source=None, source_name: str | None = None):
    from dashboard.imports import ImportInputError, execute_import
    from database import ImportRun

    result = execute_import(session, data)
    summary = result["summary"]
    if summary.get("valid", 0) == 0 and result.get("errors"):
        raise ImportInputError("No source could be imported: " + result["errors"][0])

    now = utcnow()
    run = ImportRun(
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
        created_by=None,
        started_at=now,
        completed_at=now,
    )
    session.add(run)

    if source:
        source.last_run_at = now
        source.last_status = result.get("status", "completed")
        source.last_added = summary.get("added", 0)
        source.last_skipped = summary.get("skipped", 0)
        source.last_error = "; ".join(result.get("errors", [])[:5]) or None

    session.flush()
    result.update(
        {
            "success": True,
            "run_id": run.id,
            "added": summary.get("added", 0),
            "skipped": summary.get("skipped", 0),
        }
    )
    return result


def _record_failed_run(session, *, source, error: Exception) -> None:
    from database import ImportRun

    now = utcnow()
    session.add(
        ImportRun(
            source_id=source.id,
            source_name=source.name,
            mode=source.mode,
            status="failed",
            error=str(error)[:2000],
            created_by=None,
            started_at=now,
            completed_at=now,
        )
    )
