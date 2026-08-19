from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from secproxy_cli.output import console_for, emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services.server_service import (
    create_server,
    delete_server,
    get_server,
    list_servers,
    log_path,
    preview_server,
    read_logs,
    restart_server,
    start_server,
    stop_server,
    test_server,
    update_server,
)
from secproxy_cli.state import CLIState

app = typer.Typer(help="Create, inspect, run, and test local proxy listeners.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception, *, code: int = 1) -> None:
    state = _state(ctx)
    emit_error(state, str(exc), code=code, details=str(exc) if state.verbose else None)


def _server_data(
    *,
    name: str,
    protocol: str,
    bind: str,
    port: int,
    rotate: str,
    rotate_interval: int,
    min_cost: float,
    cost_threshold: float | None,
    threads: int,
    timeout: float,
    use_case: str,
    candidate_statuses: str,
    upstream_protocol: str,
    require_web_https: bool,
    require_remote_dns: bool,
    require_telegram: bool,
    username: str | None,
    password: str | None,
    allow_public_no_auth: bool,
    readonly: bool,
    country_codes: str,
    regions: str,
    cities: str,
    orgs: str,
    isp: str,
    asn: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "protocol": protocol,
        "bind": bind,
        "port": port,
        "rotate": rotate,
        "rotate_interval": rotate_interval,
        "min_cost": min_cost,
        "cost_threshold": cost_threshold,
        "threads": threads,
        "timeout": timeout,
        "use_case": use_case,
        "candidate_statuses": candidate_statuses,
        "upstream_protocol": upstream_protocol,
        "require_web_https": require_web_https,
        "require_remote_dns": require_remote_dns,
        "require_telegram": require_telegram,
        "username": username,
        "password": password,
        "allow_public_no_auth": allow_public_no_auth,
        "readonly": readonly,
        "countryCodes": country_codes,
        "regions": regions,
        "cities": cities,
        "orgs": orgs,
        "isp": isp,
        "asn": asn,
    }


def _rows(items: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            item["port"],
            item.get("name"),
            item.get("protocol"),
            item.get("uri"),
            "running" if item.get("running") else ("starting" if item.get("starting") else "stopped"),
            item.get("pid") or "-",
            item.get("scope"),
            "yes" if item.get("has_auth") else "no",
        )
        for item in items
    ]


def _emit_detail(state: CLIState, item: dict[str, Any]) -> None:
    if state.json_output:
        emit_json(item)
        return
    emit_kv(
        state,
        f"Server {item['port']}",
        {
            "Name": item.get("name"),
            "State": "running" if item.get("running") else ("starting" if item.get("starting") else "stopped"),
            "Protocol": item.get("protocol"),
            "Endpoint": item.get("uri"),
            "Scope": item.get("scope"),
            "PID": item.get("pid"),
            "Authentication": item.get("has_auth"),
        },
    )
    candidates = item.get("candidates")
    if candidates:
        emit_kv(
            state,
            "Candidates",
            {
                "Total": candidates.get("total", 0),
                "Protocols": candidates.get("by_protocol") or {},
                "Statuses": candidates.get("by_status") or {},
            },
        )
    emit_kv(state, "Profile", item.get("config") or {})


@app.command("list")
def list_command(ctx: typer.Context) -> None:
    """List configured proxy listeners and live runtime state."""
    state = _state(ctx)
    try:
        items = list_servers()
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    emit_table(
        state,
        title=f"Servers ({len(items)})",
        columns=["Port", "Name", "Protocol", "Endpoint", "State", "PID", "Scope", "Auth"],
        rows=_rows(items),
        json_rows=items,
    )


@app.command("show")
def show_command(ctx: typer.Context, port: int = typer.Argument(..., min=1, max=65535)) -> None:
    """Show listener config, runtime state, and candidate summary."""
    state = _state(ctx)
    try:
        item = get_server(port)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"server on port {port} not found", code=3)
    _emit_detail(state, item)


@app.command("status")
def status_command(ctx: typer.Context, port: int = typer.Argument(..., min=1, max=65535)) -> None:
    """Show compact listener runtime status."""
    state = _state(ctx)
    try:
        item = get_server(port, include_candidates=False)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"server on port {port} not found", code=3)
    if state.json_output:
        emit_json(item)
        return
    emit_kv(
        state,
        f"Server {port} Status",
        {
            "State": "running" if item.get("running") else ("starting" if item.get("starting") else "stopped"),
            "PID": item.get("pid"),
            "Protocol": item.get("protocol"),
            "Endpoint": item.get("uri"),
            "Scope": item.get("scope"),
            "Authentication": item.get("has_auth"),
        },
    )


@app.command("preview")
def preview_command(
    ctx: typer.Context,
    port: int = typer.Option(8080, "--port", min=1, max=65535),
    name: str = typer.Option("preview", "--name"),
    protocol: str = typer.Option("http", "--protocol", "-p"),
    bind: str = typer.Option("127.0.0.1", "--bind"),
    rotate: str = typer.Option("better_cost", "--rotate"),
    rotate_interval: int = typer.Option(60, "--rotate-interval", min=1, max=86400),
    min_cost: float = typer.Option(0.0, "--min-cost", min=0.0),
    cost_threshold: float | None = typer.Option(None, "--cost-threshold", min=0.0),
    threads: int = typer.Option(100, "--threads", min=1, max=1000),
    timeout: float = typer.Option(10.0, "--timeout", min=1.0, max=300.0),
    use_case: str = typer.Option("custom", "--use-case"),
    candidate_statuses: str = typer.Option("alive", "--status", help="Comma-separated candidate statuses"),
    upstream_protocol: str = typer.Option("", "--upstream-protocol", help="Comma-separated upstream protocols"),
    require_web_https: bool = typer.Option(False, "--require-https/--no-require-https"),
    require_remote_dns: bool = typer.Option(False, "--require-remote-dns/--no-require-remote-dns"),
    require_telegram: bool = typer.Option(False, "--require-telegram/--no-require-telegram"),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(None, "--password", hide_input=True),
    allow_public_no_auth: bool = typer.Option(False, "--allow-public-no-auth", help="Explicitly permit unauthenticated non-loopback bind"),
    readonly: bool = typer.Option(False, "--readonly/--read-write"),
    country_codes: str = typer.Option("", "--country"),
    regions: str = typer.Option("", "--region"),
    cities: str = typer.Option("", "--city"),
    orgs: str = typer.Option("", "--org"),
    isp: str = typer.Option("", "--isp"),
    asn: str = typer.Option("", "--asn"),
) -> None:
    """Preview matching upstream proxies without creating a listener."""
    state = _state(ctx)
    try:
        result = preview_server(
            _server_data(
                name=name, protocol=protocol, bind=bind, port=port, rotate=rotate,
                rotate_interval=rotate_interval, min_cost=min_cost, cost_threshold=cost_threshold,
                threads=threads, timeout=timeout, use_case=use_case,
                candidate_statuses=candidate_statuses, upstream_protocol=upstream_protocol,
                require_web_https=require_web_https, require_remote_dns=require_remote_dns,
                require_telegram=require_telegram, username=username, password=password,
                allow_public_no_auth=allow_public_no_auth, readonly=readonly,
                country_codes=country_codes, regions=regions, cities=cities, orgs=orgs, isp=isp, asn=asn,
            )
        )
    except Exception as exc:
        _fail(ctx, exc, code=2)
        return
    if state.json_output:
        emit_json(result)
        return
    emit_kv(state, "Server Preview", {"Candidates": result.get("total", 0), "Warnings": len(result.get("warnings", []))})
    emit_kv(state, "Protocols", result.get("by_protocol") or {})
    emit_kv(state, "Statuses", result.get("by_status") or {})
    for warning in result.get("warnings") or []:
        console_for(state).print(f"[yellow]warning:[/yellow] {warning}")


@app.command("create")
def create_command(
    ctx: typer.Context,
    port: int = typer.Argument(..., min=1, max=65535),
    name: str = typer.Option("", "--name"),
    protocol: str = typer.Option("http", "--protocol", "-p"),
    bind: str = typer.Option("127.0.0.1", "--bind"),
    rotate: str = typer.Option("better_cost", "--rotate"),
    rotate_interval: int = typer.Option(60, "--rotate-interval", min=1, max=86400),
    min_cost: float = typer.Option(0.0, "--min-cost", min=0.0),
    cost_threshold: float | None = typer.Option(None, "--cost-threshold", min=0.0),
    threads: int = typer.Option(100, "--threads", min=1, max=1000),
    timeout: float = typer.Option(10.0, "--timeout", min=1.0, max=300.0),
    use_case: str = typer.Option("custom", "--use-case"),
    candidate_statuses: str = typer.Option("alive", "--status"),
    upstream_protocol: str = typer.Option("", "--upstream-protocol"),
    require_web_https: bool = typer.Option(False, "--require-https/--no-require-https"),
    require_remote_dns: bool = typer.Option(False, "--require-remote-dns/--no-require-remote-dns"),
    require_telegram: bool = typer.Option(False, "--require-telegram/--no-require-telegram"),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(None, "--password", hide_input=True),
    allow_public_no_auth: bool = typer.Option(False, "--allow-public-no-auth"),
    readonly: bool = typer.Option(False, "--readonly/--read-write"),
    country_codes: str = typer.Option("", "--country"),
    regions: str = typer.Option("", "--region"),
    cities: str = typer.Option("", "--city"),
    orgs: str = typer.Option("", "--org"),
    isp: str = typer.Option("", "--isp"),
    asn: str = typer.Option("", "--asn"),
) -> None:
    """Create a saved listener profile without starting it."""
    state = _state(ctx)
    try:
        item = create_server(
            _server_data(
                name=name, protocol=protocol, bind=bind, port=port, rotate=rotate,
                rotate_interval=rotate_interval, min_cost=min_cost, cost_threshold=cost_threshold,
                threads=threads, timeout=timeout, use_case=use_case,
                candidate_statuses=candidate_statuses, upstream_protocol=upstream_protocol,
                require_web_https=require_web_https, require_remote_dns=require_remote_dns,
                require_telegram=require_telegram, username=username, password=password,
                allow_public_no_auth=allow_public_no_auth, readonly=readonly,
                country_codes=country_codes, regions=regions, cities=cities, orgs=orgs, isp=isp, asn=asn,
            )
        )
    except Exception as exc:
        _fail(ctx, exc, code=2)
        return
    _emit_detail(state, item)


@app.command("edit")
def edit_command(
    ctx: typer.Context,
    port: int = typer.Argument(..., min=1, max=65535),
    name: str | None = typer.Option(None, "--name"),
    protocol: str | None = typer.Option(None, "--protocol", "-p"),
    bind: str | None = typer.Option(None, "--bind"),
    rotate: str | None = typer.Option(None, "--rotate"),
    rotate_interval: int | None = typer.Option(None, "--rotate-interval", min=1, max=86400),
    min_cost: float | None = typer.Option(None, "--min-cost", min=0.0),
    cost_threshold: float | None = typer.Option(None, "--cost-threshold", min=0.0),
    threads: int | None = typer.Option(None, "--threads", min=1, max=1000),
    timeout: float | None = typer.Option(None, "--timeout", min=1.0, max=300.0),
    use_case: str | None = typer.Option(None, "--use-case"),
    candidate_statuses: str | None = typer.Option(None, "--status"),
    upstream_protocol: str | None = typer.Option(None, "--upstream-protocol"),
    require_web_https: bool | None = typer.Option(None, "--require-https/--no-require-https"),
    require_remote_dns: bool | None = typer.Option(None, "--require-remote-dns/--no-require-remote-dns"),
    require_telegram: bool | None = typer.Option(None, "--require-telegram/--no-require-telegram"),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(None, "--password", hide_input=True),
    clear_credentials: bool = typer.Option(False, "--clear-credentials"),
    allow_public_no_auth: bool | None = typer.Option(None, "--allow-public-no-auth/--block-public-no-auth"),
    readonly: bool | None = typer.Option(None, "--readonly/--read-write"),
) -> None:
    """Edit a listener profile; a running listener is stopped before mutation."""
    state = _state(ctx)
    changes: dict[str, Any] = {
        "name": name, "protocol": protocol, "bind": bind, "rotate": rotate,
        "rotate_interval": rotate_interval, "min_cost": min_cost,
        "cost_threshold": cost_threshold, "threads": threads, "timeout": timeout,
        "use_case": use_case, "candidate_statuses": candidate_statuses,
        "upstream_protocol": upstream_protocol, "require_web_https": require_web_https,
        "require_remote_dns": require_remote_dns, "require_telegram": require_telegram,
        "username": username, "password": password, "allow_public_no_auth": allow_public_no_auth,
        "readonly": readonly,
    }
    changes = {key: value for key, value in changes.items() if value is not None}
    if clear_credentials:
        changes["clear_credentials"] = True
    try:
        item = update_server(port, changes)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if item is None:
        emit_error(state, f"server on port {port} not found", code=3)
    _emit_detail(state, item)
    if item.get("was_running") and not state.json_output:
        console_for(state).print("[yellow]note:[/yellow] listener was running and has been stopped; start it again after reviewing the new profile.")


@app.command("start")
def start_command(ctx: typer.Context, port: int = typer.Argument(..., min=1, max=65535)) -> None:
    """Start a saved listener profile."""
    state = _state(ctx)
    try:
        item = start_server(port)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if item is None:
        emit_error(state, f"server on port {port} not found", code=3)
    _emit_detail(state, item)


@app.command("stop")
def stop_command(ctx: typer.Context, port: int = typer.Argument(..., min=1, max=65535)) -> None:
    """Gracefully stop a listener."""
    state = _state(ctx)
    try:
        result = stop_server(port)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"server on port {port} not found", code=3)
    emit_kv(state, "Server Stop", result)


@app.command("restart")
def restart_command(ctx: typer.Context, port: int = typer.Argument(..., min=1, max=65535)) -> None:
    """Restart a saved listener profile."""
    state = _state(ctx)
    try:
        item = restart_server(port)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if item is None:
        emit_error(state, f"server on port {port} not found", code=3)
    _emit_detail(state, item)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    port: int = typer.Argument(..., min=1, max=65535),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a stopped listener profile."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete server profile on port {port}?", default=False):
        raise typer.Abort()
    try:
        result = delete_server(port)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"server on port {port} not found", code=3)
    emit_kv(state, "Server Deleted", result)


@app.command("logs")
def logs_command(
    ctx: typer.Context,
    port: int = typer.Argument(..., min=1, max=65535),
    lines: int = typer.Option(100, "--lines", "-n", min=1, max=5000),
    follow: bool = typer.Option(False, "--follow", "-f"),
) -> None:
    """Show or follow a listener worker log."""
    state = _state(ctx)
    if state.json_output and follow:
        emit_error(state, "--follow is not available with --json", code=2)
    try:
        result = read_logs(port, lines=lines)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if result is None:
        emit_error(state, f"server on port {port} not found", code=3)
    if state.json_output:
        emit_json(result)
        return
    for line in result["lines"]:
        typer.echo(line)
    if not follow:
        return
    path = log_path(port)
    pos = path.stat().st_size if path.exists() else 0
    try:
        while True:
            if path.exists():
                size = path.stat().st_size
                if size < pos:
                    pos = 0
                if size > pos:
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(pos)
                        chunk = handle.read()
                        pos = handle.tell()
                    if chunk:
                        typer.echo(chunk, nl=False)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


@app.command("test")
def test_command(
    ctx: typer.Context,
    port: int = typer.Argument(..., min=1, max=65535),
    url: str = typer.Option("https://example.com", "--url", help="HTTP/HTTPS URL fetched through the listener"),
    timeout: float = typer.Option(10.0, "--timeout", min=1.0, max=120.0),
    connect_only: bool = typer.Option(False, "--connect-only", help="Only verify that the listener accepts TCP connections"),
) -> None:
    """Test listener reachability and optionally make a request through it."""
    state = _state(ctx)
    try:
        result = test_server(port, url=url, timeout=timeout, connect_only=connect_only)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"server on port {port} not found", code=3)
    if state.json_output:
        emit_json(result)
    else:
        emit_kv(state, "Server Test", result)
    if not result.get("ok"):
        raise typer.Exit(code=6)
