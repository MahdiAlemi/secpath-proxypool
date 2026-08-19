from __future__ import annotations

from pathlib import Path

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services.source_service import (
    add_source,
    delete_source,
    get_source,
    import_history,
    import_input,
    list_sources,
    preview_input,
    preview_source,
    read_links_file,
    read_text_file,
    run_source,
    set_source_active,
)
from secproxy_cli.state import CLIState

app = typer.Typer(help="Manage proxy import sources and import runs.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, message: str, exc: Exception | None = None, *, code: int = 1) -> None:
    state = _state(ctx)
    details = str(exc) if (exc is not None and state.verbose) else None
    emit_error(state, message if exc is None else str(exc), code=code, details=details)


def _emit_preview(state: CLIState, result: dict) -> None:
    if state.json_output:
        emit_json(result)
        return
    summary = result.get("summary", {})
    emit_kv(
        state,
        "Import Preview",
        {
            "Mode": result.get("mode"),
            "Total lines": summary.get("total_lines", 0),
            "Valid": summary.get("valid", 0),
            "New": summary.get("new", 0),
            "Existing": summary.get("existing", 0),
            "Invalid": summary.get("invalid", 0),
            "Input duplicates": summary.get("input_duplicates", 0),
            "Ignored": summary.get("ignored", 0),
            "Truncated": summary.get("truncated", False),
        },
    )
    protocols = result.get("protocols", {})
    if protocols:
        emit_table(
            state,
            title="Protocols",
            columns=["Protocol", "Count"],
            rows=[(name, count) for name, count in sorted(protocols.items())],
        )


def _emit_import_result(state: CLIState, result: dict) -> None:
    if state.json_output:
        emit_json(result)
        return
    summary = result.get("summary", {})
    emit_kv(
        state,
        "Import Result",
        {
            "Run ID": result.get("run_id"),
            "Status": result.get("status", "completed"),
            "Total lines": summary.get("total_lines", 0),
            "Valid": summary.get("valid", 0),
            "Added": summary.get("added", result.get("added", 0)),
            "Skipped": summary.get("skipped", result.get("skipped", 0)),
            "Existing": summary.get("existing", 0),
            "Invalid": summary.get("invalid", 0),
            "Input duplicates": summary.get("input_duplicates", 0),
        },
    )


@app.command("list")
def list_command(
    ctx: typer.Context,
    active: bool | None = typer.Option(None, "--active/--inactive", help="Filter by enabled state"),
) -> None:
    """List saved URL/grouped sources."""
    state = _state(ctx)
    try:
        sources = list_sources(active=active)
    except Exception as exc:
        _fail(ctx, "could not list sources", exc, code=7)
        return
    emit_table(
        state,
        title=f"Import Sources ({len(sources)})",
        columns=["ID", "Name", "Mode", "Protocol", "Active", "Last status", "Added", "Last run"],
        rows=[
            (
                item["id"],
                item["name"],
                item["mode"],
                item.get("protocol") or "-",
                "yes" if item["is_active"] else "no",
                item.get("last_status") or "-",
                item.get("last_added", 0),
                item.get("last_run_at") or "-",
            )
            for item in sources
        ],
        json_rows=sources,
    )


@app.command("show")
def show_command(ctx: typer.Context, source: str = typer.Argument(..., help="Source ID or name")) -> None:
    """Show one saved source with sensitive URL parts redacted."""
    state = _state(ctx)
    try:
        item = get_source(source)
    except Exception as exc:
        _fail(ctx, "could not read source", exc, code=7)
        return
    if item is None:
        emit_error(state, f"source {source!r} not found", code=3)
    emit_kv(state, f"Source {item['name']}", item)


@app.command("add")
def add_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Unique saved source name"),
    url: str | None = typer.Option(None, "--url", help="HTTP/HTTPS proxy-list URL"),
    protocol: str = typer.Option("http", "--protocol", "-p", help="Default protocol for --url"),
    links_file: Path | None = typer.Option(None, "--links-file", exists=True, dir_okay=False, readable=True),
    inactive: bool = typer.Option(False, "--inactive", help="Create source disabled"),
) -> None:
    """Save a URL source or grouped links config."""
    state = _state(ctx)
    if bool(url) == bool(links_file):
        emit_error(state, "choose exactly one of --url or --links-file", code=2)
    try:
        if links_file:
            content = read_links_file(links_file)
            item = add_source(name=name, mode="links", content=content, is_active=not inactive)
        else:
            item = add_source(
                name=name,
                mode="url",
                protocol=protocol,
                url=url,
                is_active=not inactive,
            )
    except Exception as exc:
        _fail(ctx, "could not add source", exc, code=1)
        return
    emit_kv(state, "Source Created", item)


@app.command("enable")
def enable_command(ctx: typer.Context, source: str = typer.Argument(..., help="Source ID or name")) -> None:
    """Enable a saved source."""
    state = _state(ctx)
    try:
        item = set_source_active(source, True)
    except Exception as exc:
        _fail(ctx, "could not enable source", exc, code=7)
        return
    if item is None:
        emit_error(state, f"source {source!r} not found", code=3)
    emit_kv(state, "Source Enabled", item)


@app.command("disable")
def disable_command(ctx: typer.Context, source: str = typer.Argument(..., help="Source ID or name")) -> None:
    """Disable a saved source."""
    state = _state(ctx)
    try:
        item = set_source_active(source, False)
    except Exception as exc:
        _fail(ctx, "could not disable source", exc, code=7)
        return
    if item is None:
        emit_error(state, f"source {source!r} not found", code=3)
    emit_kv(state, "Source Disabled", item)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Source ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a saved source (does not delete imported proxies)."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete saved source {source!r}? Imported proxies are kept."):
        raise typer.Abort()
    try:
        deleted = delete_source(source)
    except Exception as exc:
        _fail(ctx, "could not delete source", exc, code=7)
        return
    if deleted is None:
        emit_error(state, f"source {source!r} not found", code=3)
    if state.json_output:
        emit_json({"deleted": deleted})
    else:
        typer.echo(f"deleted source {deleted['name']} ({deleted['id']})")


@app.command("preview")
def preview_command(
    ctx: typer.Context,
    source: str | None = typer.Argument(None, help="Saved source ID/name"),
    file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False, readable=True),
    url: str | None = typer.Option(None, "--url"),
    links_file: Path | None = typer.Option(None, "--links-file", exists=True, dir_okay=False, readable=True),
    protocol: str = typer.Option("http", "--protocol", "-p"),
) -> None:
    """Preview a saved source or ad-hoc file/URL without writing proxies."""
    state = _state(ctx)
    selected = sum(bool(value) for value in (source, file, url, links_file))
    if selected != 1:
        emit_error(state, "choose exactly one: SOURCE, --file, --url, or --links-file", code=2)
    try:
        if source:
            result = preview_source(source)
            if result is None:
                emit_error(state, f"source {source!r} not found", code=3)
        elif file:
            result = preview_input(mode="manual", protocol=protocol, content=read_text_file(file))
        elif url:
            result = preview_input(mode="url", protocol=protocol, url=url)
        else:
            result = preview_input(mode="links", content=read_links_file(links_file))
    except Exception as exc:
        _fail(ctx, "could not preview import", exc, code=1)
        return
    _emit_preview(state, result)


@app.command("import")
def import_command(
    ctx: typer.Context,
    file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False, readable=True),
    url: str | None = typer.Option(None, "--url"),
    links_file: Path | None = typer.Option(None, "--links-file", exists=True, dir_okay=False, readable=True),
    protocol: str = typer.Option("http", "--protocol", "-p"),
    name: str | None = typer.Option(None, "--name", help="Audit label for this ad-hoc import"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Execute an ad-hoc import from file, URL, or grouped links config."""
    state = _state(ctx)
    selected = sum(bool(value) for value in (file, url, links_file))
    if selected != 1:
        emit_error(state, "choose exactly one of --file, --url, or --links-file", code=2)
    if not yes and not typer.confirm("Import new proxy rows into the configured database?"):
        raise typer.Abort()
    try:
        if file:
            result = import_input(
                mode="manual",
                protocol=protocol,
                content=read_text_file(file),
                source_name=name,
            )
        elif url:
            result = import_input(mode="url", protocol=protocol, url=url, source_name=name)
        else:
            result = import_input(mode="links", content=read_links_file(links_file), source_name=name)
    except Exception as exc:
        _fail(ctx, "import failed", exc, code=1)
        return
    _emit_import_result(state, result)


@app.command("run")
def run_command(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="Saved source ID or name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Fetch and import a saved enabled source."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Run saved source {source!r} and write new proxy rows?"):
        raise typer.Abort()
    try:
        result = run_source(source)
    except Exception as exc:
        _fail(ctx, "source run failed", exc, code=1)
        return
    if result is None:
        emit_error(state, f"source {source!r} not found", code=3)
    _emit_import_result(state, result)


@app.command("history")
def history_command(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100),
    source: str | None = typer.Option(None, "--source", help="Filter by source ID/name"),
) -> None:
    """Show recent import audit records."""
    state = _state(ctx)
    try:
        rows = import_history(limit=limit, source=source)
    except Exception as exc:
        _fail(ctx, "could not read import history", exc, code=7)
        return
    emit_table(
        state,
        title=f"Import History ({len(rows)})",
        columns=["ID", "Source", "Mode", "Status", "Valid", "Added", "Skipped", "Started"],
        rows=[
            (
                row["id"],
                row.get("source_name") or "-",
                row["mode"],
                row["status"],
                row.get("valid", 0),
                row.get("added", 0),
                row.get("skipped", 0),
                row.get("started_at") or "-",
            )
            for row in rows
        ],
        json_rows=rows,
    )
