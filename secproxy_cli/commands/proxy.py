from __future__ import annotations

from pathlib import Path
import sys

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.state import CLIState
from secproxy_core.errors import ConflictError
from secproxy_core import proxy_service as svc

app = typer.Typer(help="Inspect and manage proxy inventory.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception, *, code: int = 1) -> None:
    state = _state(ctx)
    emit_error(state, str(exc), code=code, details=str(exc) if state.verbose else None)


def _read_password(
    *,
    password: str | None,
    prompt_password: bool,
    password_stdin: bool,
) -> str | None:
    selected = sum(
        (
            password is not None,
            bool(prompt_password),
            bool(password_stdin),
        )
    )
    if selected > 1:
        raise ValueError(
            "choose only one of --password TEXT, --password-prompt, or --password-stdin"
        )
    if prompt_password:
        return typer.prompt("Password", hide_input=True)
    if password_stdin:
        value = sys.stdin.readline()
        if value == "":
            raise ValueError("--password-stdin received no input")
        return value.rstrip("\r\n")
    return password


@app.command("list")
def list_command(
    ctx: typer.Context,
    protocol: str | None = typer.Option(None, "--protocol", "-p"),
    status: str | None = typer.Option(None, "--status", "-s"),
    country: str | None = typer.Option(None, "--country"),
    https_only: bool = typer.Option(False, "--https"),
    remote_dns: bool = typer.Option(False, "--remote-dns"),
    telegram: bool = typer.Option(False, "--telegram"),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=10000),
    offset: int = typer.Option(0, "--offset", min=0),
) -> None:
    """List proxies with operational filters."""
    state = _state(ctx)
    try:
        proxies = svc.list_proxies(
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns,
            telegram_only=telegram,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return

    emit_table(
        state,
        title=f"Proxy Inventory ({len(proxies)})",
        columns=["ID", "Protocol", "Endpoint", "Status", "Latency", "Country", "HTTPS", "DNS", "TG", "Auth"],
        rows=[
            (
                p["id"],
                p["protocol"],
                f'{p["ip"]}:{p["port"]}',
                p["status"],
                f'{p["speed_ms"]} ms' if p["speed_ms"] is not None else "-",
                p["country"] or "-",
                "yes" if p["web_https_ok"] else "-",
                "yes" if p["remote_dns_ok"] else "-",
                "yes" if p["telegram_ok"] else "-",
                "yes" if p["has_auth"] else "-",
            )
            for p in proxies
        ],
        json_rows=proxies,
    )


@app.command("show")
def show_command(ctx: typer.Context, proxy_id: int = typer.Argument(..., min=1)) -> None:
    """Show one proxy without exposing stored credentials."""
    state = _state(ctx)
    try:
        proxy = svc.get_proxy(proxy_id)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if proxy is None:
        emit_error(state, f"proxy {proxy_id} not found", code=3)
    emit_kv(state, f"Proxy {proxy_id}", proxy)


@app.command("count")
def count_command(
    ctx: typer.Context,
    protocol: str | None = typer.Option(None, "--protocol", "-p"),
    status: str | None = typer.Option(None, "--status", "-s"),
    country: str | None = typer.Option(None, "--country"),
    https_only: bool = typer.Option(False, "--https"),
    remote_dns: bool = typer.Option(False, "--remote-dns"),
    telegram: bool = typer.Option(False, "--telegram"),
) -> None:
    """Count proxies matching filters."""
    state = _state(ctx)
    try:
        count = svc.count_proxies(
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns,
            telegram_only=telegram,
        )
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if state.json_output:
        emit_json({"count": count})
    else:
        typer.echo(str(count))


@app.command("add")
def add_command(
    ctx: typer.Context,
    protocol: str = typer.Argument(...),
    ip: str = typer.Argument(...),
    port: int = typer.Argument(..., min=1, max=65535),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(
        None, "--password", help="Password value (may be visible in shell history)"
    ),
    password_prompt: bool = typer.Option(
        False, "--password-prompt", help="Prompt for password with hidden input"
    ),
    password_stdin: bool = typer.Option(
        False, "--password-stdin", help="Read password from one stdin line"
    ),
) -> None:
    """Add one proxy. Credentials are accepted but never printed back."""
    state = _state(ctx)
    try:
        password = _read_password(
            password=password,
            prompt_password=password_prompt,
            password_stdin=password_stdin,
        )
        item = svc.add_proxy(
            protocol=protocol,
            ip=ip,
            port=port,
            username=username,
            password=password,
        )
    except ConflictError as exc:
        _fail(ctx, exc, code=5)
        return
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    emit_kv(state, "Proxy Added", item)


@app.command("edit")
def edit_command(
    ctx: typer.Context,
    proxy_id: int = typer.Argument(..., min=1),
    protocol: str | None = typer.Option(None, "--protocol"),
    ip: str | None = typer.Option(None, "--ip"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(
        None, "--password", help="Password value (may be visible in shell history)"
    ),
    password_prompt: bool = typer.Option(
        False, "--password-prompt", help="Prompt for password with hidden input"
    ),
    password_stdin: bool = typer.Option(
        False, "--password-stdin", help="Read password from one stdin line"
    ),
    clear_credentials: bool = typer.Option(False, "--clear-credentials"),
) -> None:
    """Edit proxy identity; changing identity resets validation state to untested."""
    state = _state(ctx)
    try:
        password = _read_password(
            password=password,
            prompt_password=password_prompt,
            password_stdin=password_stdin,
        )
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return

    changes = {
        key: value
        for key, value in {
            "protocol": protocol,
            "ip": ip,
            "port": port,
            "username": username,
            "password": password,
        }.items()
        if value is not None
    }
    if clear_credentials:
        changes["clear_credentials"] = True
    if not changes:
        emit_error(state, "no changes specified", code=2)

    try:
        item = svc.update_proxy(proxy_id, changes)
    except ConflictError as exc:
        _fail(ctx, exc, code=5)
        return
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"proxy {proxy_id} not found", code=3)
    emit_kv(state, "Proxy Updated", item)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    proxy_id: int = typer.Argument(..., min=1),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete one proxy."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete proxy {proxy_id}?", default=False):
        raise typer.Abort()
    try:
        item = svc.delete_proxy(proxy_id)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"proxy {proxy_id} not found", code=3)
    emit_kv(state, "Proxy Deleted", item)


@app.command("purge")
def purge_command(
    ctx: typer.Context,
    protocol: str | None = typer.Option(None, "--protocol"),
    status: str | None = typer.Option(None, "--status"),
    country: str | None = typer.Option(None, "--country"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    max_delete: int = typer.Option(100000, "--max-delete", min=1),
) -> None:
    """Preview a filtered bulk delete; pass --yes to actually delete."""
    state = _state(ctx)
    try:
        result = svc.purge_proxies(
            protocol=protocol,
            status=status,
            country=country,
            dry_run=not yes,
            max_delete=max_delete,
        )
    except ConflictError as exc:
        _fail(ctx, exc, code=5)
        return
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return

    if state.json_output:
        emit_json(result)
        return

    emit_kv(
        state,
        "Proxy Purge" if yes else "Proxy Purge Preview",
        {
            "Matched": result["matched"],
            "Deleted": result["deleted"],
            "Dry run": result["dry_run"],
            "Filters": result["filters"],
        },
    )
    if result["sample"]:
        emit_table(
            state,
            title="Sample",
            columns=["ID", "Protocol", "Endpoint", "Status"],
            rows=[
                (x["id"], x["protocol"], f'{x["ip"]}:{x["port"]}', x["status"])
                for x in result["sample"]
            ],
        )


@app.command("test")
def test_command(
    ctx: typer.Context,
    proxy_id: int = typer.Argument(..., min=1),
    url: str = typer.Option("https://example.com/", "--url"),
    connect_timeout: float = typer.Option(
        3.0, "--connect-timeout", min=0.5, max=30.0
    ),
    timeout: float = typer.Option(
        5.0, "--timeout", min=1.0, max=60.0, help="Read timeout in seconds"
    ),
) -> None:
    """Run an ad-hoc non-mutating request through one stored proxy."""
    state = _state(ctx)

    if not state.json_output:
        typer.echo(
            f"Testing proxy {proxy_id} -> {url} "
            f"(connect {connect_timeout:g}s, read {timeout:g}s)...",
            err=True,
        )

    try:
        result = svc.test_proxy(
            proxy_id,
            url=url,
            connect_timeout=connect_timeout,
            read_timeout=timeout,
        )
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return

    if result is None:
        emit_error(state, f"proxy {proxy_id} not found", code=3)

    if state.json_output:
        emit_json(result)
    else:
        emit_kv(
            state,
            f"Proxy {proxy_id} Test",
            {
                "OK": result["ok"],
                "Stage": result.get("stage"),
                "Target": result["target"],
                "HTTP status": result.get("status_code"),
                "Elapsed": f'{result["elapsed_ms"]} ms',
                "Error type": result.get("error_type"),
                "Error": result.get("error"),
                "Database mutated": result["mutated"],
            },
        )

    if not result["ok"]:
        raise typer.Exit(code=6)


@app.command("export")
def export_command(
    ctx: typer.Context,
    format: str = typer.Option("txt", "--format", "-f", help="txt, urls, csv, json"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    protocol: str | None = typer.Option(None, "--protocol"),
    status: str | None = typer.Option(None, "--status"),
    country: str | None = typer.Option(None, "--country"),
    https_only: bool = typer.Option(False, "--https"),
    remote_dns: bool = typer.Option(False, "--remote-dns"),
    telegram: bool = typer.Option(False, "--telegram"),
    limit: int = typer.Option(100000, "--limit", min=1, max=1000000),
    include_credentials: bool = typer.Option(False, "--include-credentials"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Export filtered proxies; credentials require an explicit protected output file."""
    state = _state(ctx)

    if include_credentials and output is None:
        emit_error(
            state,
            "--include-credentials requires --output FILE; credentials are never emitted to stdout",
            code=2,
        )
    if include_credentials and not yes:
        emit_error(
            state,
            "--include-credentials requires --yes",
            code=2,
        )

    try:
        rows = svc.export_rows(
            protocol=protocol,
            status=status,
            country=country,
            https_only=https_only,
            remote_dns_only=remote_dns,
            telegram_only=telegram,
            include_credentials=include_credentials,
            limit=limit,
        )
        content = svc.render_export(
            rows,
            format="json" if state.json_output and output is None else format,
            include_credentials=include_credentials,
        )
    except ValueError as exc:
        _fail(ctx, exc, code=2)
        return
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return

    if output is None:
        typer.echo(content, nl=False)
        return

    try:
        result = svc.write_export(output, content)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    result["count"] = len(rows)
    result["format"] = format
    result["include_credentials"] = include_credentials
    emit_kv(state, "Proxy Export", result)
