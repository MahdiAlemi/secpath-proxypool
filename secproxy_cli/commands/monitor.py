from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.live import Live
from rich.table import Table

from secproxy_cli.output import console_for, emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services.monitor_service import (
    create_monitor,
    delete_monitor,
    get_monitor,
    list_monitors,
    log_path,
    monitor_results,
    preview_monitor,
    preview_profile,
    read_logs,
    remove_service,
    restart_monitor,
    resume_monitor,
    start_monitor,
    stop_monitor,
    update_monitor,
)
from secproxy_cli.state import CLIState

app = typer.Typer(help="Create, run, inspect, and control proxy monitors.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception, *, code: int = 1) -> None:
    state = _state(ctx)
    emit_error(state, str(exc), code=code, details=str(exc) if state.verbose else None)


def _profile_data(
    *,
    name: str,
    protocol: str,
    status: str,
    check_urls: str,
    threads: int,
    timeout: int,
    probes: int,
    run_mode: str,
    interval: int,
    schedule_time: str,
    schedule_days: str,
    custom_every: int,
    geo: bool,
    create_service: bool,
) -> dict:
    return {
        "name": name,
        "protocol": protocol,
        "status": status,
        "check_urls": check_urls,
        "threads": threads,
        "timeout": timeout,
        "probes": probes,
        "run_mode": run_mode,
        "interval": interval,
        "schedule_time": schedule_time,
        "schedule_days": schedule_days,
        "custom_every": custom_every,
        "geo": "true" if geo else "false",
        "create_service": "yes" if create_service else "no",
    }


def _monitor_rows(items: list[dict]) -> list[tuple]:
    rows = []
    for item in items:
        progress = item.get("progress") or {}
        tested = progress.get("tested", 0)
        total = progress.get("total", 0)
        progress_text = f"{tested}/{total}" if total else "-"
        rows.append(
            (
                item.get("id"),
                item.get("name"),
                item.get("state") or "-",
                "yes" if item.get("running") else ("starting" if item.get("starting") else "no"),
                item.get("pid") or "-",
                item.get("proxy_count", 0),
                progress_text,
                item.get("service") or "-",
            )
        )
    return rows


def _watch_table(item: dict) -> Table:
    progress = item.get("progress") or {}
    total = int(progress.get("total") or 0)
    tested = int(progress.get("tested") or 0)
    percent = progress.get("percent")
    if percent is None:
        percent = int((tested / total) * 100) if total else 0
    table = Table(title=f"Monitor {item.get('name')} ({item.get('id')})", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("State", str(item.get("state") or "-"))
    table.add_row("Running", "yes" if item.get("running") else "no")
    table.add_row("PID", str(item.get("pid") or "-"))
    table.add_row("Memory", f"{item.get('memory_mb', 0.0)} MB")
    table.add_row("Candidates", str(item.get("proxy_count", 0)))
    table.add_row("Tested", f"{tested}/{total}" if total else str(tested))
    table.add_row("Progress", f"{percent}%")
    table.add_row("Alive", str(progress.get("alive", 0)))
    table.add_row("Dead", str(progress.get("dead", 0)))
    table.add_row("Other", str(progress.get("other", 0)))
    if item.get("last_error"):
        table.add_row("Last error", str(item["last_error"]))
    return table


@app.command("list")
def list_command(ctx: typer.Context) -> None:
    """List monitor profiles with live runtime state."""
    state = _state(ctx)
    try:
        items = list_monitors()
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    emit_table(
        state,
        title=f"Monitors ({len(items)})",
        columns=["ID", "Name", "State", "Running", "PID", "Candidates", "Progress", "Service"],
        rows=_monitor_rows(items),
        json_rows=items,
    )


@app.command("show")
def show_command(ctx: typer.Context, monitor: str = typer.Argument(..., help="Monitor ID or name")) -> None:
    """Show monitor configuration, runtime state, and progress."""
    state = _state(ctx)
    try:
        item = get_monitor(monitor)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    if state.json_output:
        emit_json(item)
        return
    progress = item.get("progress") or {}
    emit_kv(
        state,
        f"Monitor {item['name']}",
        {
            "ID": item["id"],
            "State": item.get("state"),
            "Running": item.get("running"),
            "Starting": item.get("starting"),
            "PID": item.get("pid"),
            "Memory MB": item.get("memory_mb"),
            "Candidates": item.get("proxy_count"),
            "Progress": f"{progress.get('tested', 0)}/{progress.get('total', 0)}",
            "Alive": progress.get("alive", 0),
            "Dead": progress.get("dead", 0),
            "Other": progress.get("other", 0),
            "Service": item.get("service"),
            "Last error": item.get("last_error"),
        },
    )
    emit_kv(state, "Profile", item.get("config") or {})


@app.command("status")
def status_command(ctx: typer.Context, monitor: str = typer.Argument(..., help="Monitor ID or name")) -> None:
    """Show a compact status snapshot for one monitor."""
    state = _state(ctx)
    try:
        item = get_monitor(monitor)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if item is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    if state.json_output:
        emit_json(item)
    else:
        console_for(state).print(_watch_table(item))


@app.command("preview")
def preview_command(
    ctx: typer.Context,
    monitor: str | None = typer.Argument(None, help="Existing monitor ID/name; omit for ad-hoc preview"),
    name: str = typer.Option("preview", "--name", help="Name for ad-hoc preview"),
    protocol: str = typer.Option("", "--protocol", "-p", help="Comma-separated protocols"),
    status: str = typer.Option("", "--status", "-s", help="Comma-separated statuses"),
    check_urls: str = typer.Option("", "--check-urls", help="Comma-separated public HTTP/HTTPS check URLs"),
    threads: int = typer.Option(50, "--threads", min=1, max=200),
    timeout: int = typer.Option(5, "--timeout", min=1, max=60),
    probes: int = typer.Option(2, "--probes", min=1, max=5),
    run_mode: str = typer.Option("once", "--run-mode"),
    interval: int = typer.Option(60, "--interval", min=10, max=86400),
    schedule_time: str = typer.Option("", "--schedule-time"),
    schedule_days: str = typer.Option("daily", "--schedule-days"),
    custom_every: int = typer.Option(24, "--custom-every", min=1, max=720),
    geo: bool = typer.Option(True, "--geo/--no-geo"),
    create_service: bool = typer.Option(False, "--service/--no-service"),
) -> None:
    """Preview candidate proxies without starting a monitor."""
    state = _state(ctx)
    try:
        if monitor:
            result = preview_monitor(monitor)
            if result is None:
                emit_error(state, f"monitor {monitor!r} not found", code=3)
        else:
            result = preview_profile(
                _profile_data(
                    name=name,
                    protocol=protocol,
                    status=status,
                    check_urls=check_urls,
                    threads=threads,
                    timeout=timeout,
                    probes=probes,
                    run_mode=run_mode,
                    interval=interval,
                    schedule_time=schedule_time,
                    schedule_days=schedule_days,
                    custom_every=custom_every,
                    geo=geo,
                    create_service=create_service,
                )
            )
    except Exception as exc:
        _fail(ctx, exc, code=2)
        return
    if state.json_output:
        emit_json(result)
        return
    preview = result["preview"]
    emit_kv(
        state,
        "Monitor Preview",
        {
            "Monitor ID": result["monitor_id"],
            "Candidates": preview.get("total", 0),
            "HTTPS capable": (preview.get("capabilities") or {}).get("web_https", 0),
            "Remote DNS": (preview.get("capabilities") or {}).get("remote_dns", 0),
            "Telegram": (preview.get("capabilities") or {}).get("telegram", 0),
        },
    )
    if preview.get("protocols"):
        emit_table(
            state,
            title="Protocols",
            columns=["Protocol", "Count"],
            rows=sorted(preview["protocols"].items()),
        )
    if preview.get("statuses"):
        emit_table(
            state,
            title="Statuses",
            columns=["Status", "Count"],
            rows=sorted(preview["statuses"].items()),
        )
    if preview.get("samples"):
        emit_table(
            state,
            title="Sample Candidates",
            columns=["ID", "Protocol", "Endpoint", "Status"],
            rows=[(x["id"], x["protocol"], x["endpoint"], x["status"]) for x in preview["samples"]],
        )


@app.command("create")
def create_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Monitor profile name"),
    protocol: str = typer.Option("", "--protocol", "-p", help="Comma-separated protocols"),
    status: str = typer.Option("", "--status", "-s", help="Comma-separated statuses"),
    check_urls: str = typer.Option("", "--check-urls", help="Comma-separated public HTTP/HTTPS check URLs"),
    threads: int = typer.Option(50, "--threads", min=1, max=200),
    timeout: int = typer.Option(5, "--timeout", min=1, max=60),
    probes: int = typer.Option(2, "--probes", min=1, max=5),
    run_mode: str = typer.Option("once", "--run-mode", help="once|infinite|restart|schedule|custom"),
    interval: int = typer.Option(60, "--interval", min=10, max=86400),
    schedule_time: str = typer.Option("", "--schedule-time", help="HH:MM for schedule mode"),
    schedule_days: str = typer.Option("daily", "--schedule-days", help="daily|weekdays|weekends|mon,tue,..."),
    custom_every: int = typer.Option(24, "--custom-every", min=1, max=720, help="Hours for custom mode"),
    geo: bool = typer.Option(True, "--geo/--no-geo"),
    create_service: bool = typer.Option(False, "--service/--no-service", help="Create a systemd service (root required on start)"),
) -> None:
    """Create a saved monitor profile without starting it."""
    state = _state(ctx)
    try:
        result = create_monitor(
            _profile_data(
                name=name,
                protocol=protocol,
                status=status,
                check_urls=check_urls,
                threads=threads,
                timeout=timeout,
                probes=probes,
                run_mode=run_mode,
                interval=interval,
                schedule_time=schedule_time,
                schedule_days=schedule_days,
                custom_every=custom_every,
                geo=geo,
                create_service=create_service,
            )
        )
    except FileExistsError:
        emit_error(state, f"monitor {name!r} already exists", code=5)
    except Exception as exc:
        _fail(ctx, exc, code=2)
        return
    emit_kv(state, "Monitor Created", result)


@app.command("edit")
def edit_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(..., help="Monitor ID or name"),
    name: str | None = typer.Option(None, "--name"),
    protocol: str | None = typer.Option(None, "--protocol", "-p"),
    status: str | None = typer.Option(None, "--status", "-s"),
    check_urls: str | None = typer.Option(None, "--check-urls"),
    threads: int | None = typer.Option(None, "--threads", min=1, max=200),
    timeout: int | None = typer.Option(None, "--timeout", min=1, max=60),
    probes: int | None = typer.Option(None, "--probes", min=1, max=5),
    run_mode: str | None = typer.Option(None, "--run-mode"),
    interval: int | None = typer.Option(None, "--interval", min=10, max=86400),
    schedule_time: str | None = typer.Option(None, "--schedule-time"),
    schedule_days: str | None = typer.Option(None, "--schedule-days"),
    custom_every: int | None = typer.Option(None, "--custom-every", min=1, max=720),
    geo: str | None = typer.Option(None, "--geo", help="true or false"),
    service: str | None = typer.Option(None, "--service", help="yes or no"),
) -> None:
    """Edit a stopped monitor profile; unspecified values are preserved."""
    state = _state(ctx)
    changes = {
        key: value
        for key, value in {
            "name": name,
            "protocol": protocol,
            "status": status,
            "check_urls": check_urls,
            "threads": threads,
            "timeout": timeout,
            "probes": probes,
            "run_mode": run_mode,
            "interval": interval,
            "schedule_time": schedule_time,
            "schedule_days": schedule_days,
            "custom_every": custom_every,
            "geo": geo,
            "create_service": service,
        }.items()
        if value is not None
    }
    if not changes:
        emit_error(state, "no changes specified", code=2)
    try:
        result = update_monitor(monitor, changes)
    except FileExistsError:
        emit_error(state, "a monitor with the new name already exists", code=5)
    except RuntimeError as exc:
        _fail(ctx, exc, code=5)
        return
    except Exception as exc:
        _fail(ctx, exc, code=2)
        return
    if result is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    emit_kv(state, "Monitor Updated", result)


def _control(ctx: typer.Context, monitor: str, operation: str) -> None:
    state = _state(ctx)
    try:
        if operation == "start":
            result = start_monitor(monitor)
        elif operation == "pause":
            result = stop_monitor(monitor, action="pause")
        elif operation == "resume":
            result = resume_monitor(monitor)
        elif operation == "stop":
            result = stop_monitor(monitor, action="stop")
        elif operation == "restart":
            result = restart_monitor(monitor)
        else:
            raise RuntimeError(f"unsupported operation: {operation}")
    except PermissionError as exc:
        _fail(ctx, exc, code=4)
        return
    except RuntimeError as exc:
        _fail(ctx, exc, code=5)
        return
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    emit_kv(state, f"Monitor {operation.title()}", result)


@app.command("start")
def start_command(ctx: typer.Context, monitor: str = typer.Argument(...)) -> None:
    """Start a monitor profile."""
    _control(ctx, monitor, "start")


@app.command("pause")
def pause_command(ctx: typer.Context, monitor: str = typer.Argument(...)) -> None:
    """Gracefully pause a running monitor."""
    _control(ctx, monitor, "pause")


@app.command("resume")
def resume_command(ctx: typer.Context, monitor: str = typer.Argument(...)) -> None:
    """Resume a paused monitor session."""
    _control(ctx, monitor, "resume")


@app.command("stop")
def stop_command(ctx: typer.Context, monitor: str = typer.Argument(...)) -> None:
    """Gracefully stop a monitor."""
    _control(ctx, monitor, "stop")


@app.command("restart")
def restart_command(ctx: typer.Context, monitor: str = typer.Argument(...)) -> None:
    """Stop (if needed) and start a fresh monitor run."""
    _control(ctx, monitor, "restart")


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a monitor profile, runtime state, progress, results, and log."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete monitor {monitor!r} and its monitor-session results?"):
        raise typer.Abort()
    try:
        result = delete_monitor(monitor)
    except PermissionError as exc:
        _fail(ctx, exc, code=4)
        return
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    emit_kv(state, "Monitor Deleted", result)


@app.command("remove-service")
def remove_service_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Remove a systemd service created for a monitor (root required)."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Remove systemd service for {monitor!r}?"):
        raise typer.Abort()
    try:
        result = remove_service(monitor)
    except PermissionError as exc:
        _fail(ctx, exc, code=4)
        return
    except RuntimeError as exc:
        _fail(ctx, exc, code=5)
        return
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if result is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    emit_kv(state, "Service Removed", result)


@app.command("results")
def results_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(...),
    limit: int = typer.Option(25, "--limit", "-n", min=1, max=1000),
) -> None:
    """Show recently tested proxies for a monitor session."""
    state = _state(ctx)
    try:
        payload = monitor_results(monitor, limit=limit)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if payload is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    if state.json_output:
        emit_json(payload)
        return
    if payload.get("session"):
        emit_kv(state, "Session", payload["session"])
    results = payload.get("results") or []
    emit_table(
        state,
        title=f"Monitor Results ({len(results)})",
        columns=["Proxy", "Protocol", "Endpoint", "Status", "Latency", "Country", "HTTPS", "DNS", "TG", "Tested"],
        rows=[
            (
                row["proxy_id"],
                row["protocol"],
                row["endpoint"],
                row["status"],
                f"{row['speed_ms']} ms" if row.get("speed_ms") is not None else "-",
                row.get("country_code") or "-",
                "yes" if row.get("web_https_ok") else "-",
                "yes" if row.get("remote_dns_ok") else "-",
                "yes" if row.get("telegram_ok") else "-",
                row.get("tested_at") or "-",
            )
            for row in results
        ],
    )


@app.command("logs")
def logs_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(...),
    lines: int = typer.Option(100, "--lines", "-n", min=1, max=5000),
    follow: bool = typer.Option(False, "--follow", "-f"),
) -> None:
    """Show or follow a monitor's worker log."""
    state = _state(ctx)
    try:
        payload = read_logs(monitor, lines=lines)
    except Exception as exc:
        _fail(ctx, exc, code=6)
        return
    if payload is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)
    if state.json_output:
        if follow:
            emit_error(state, "--follow is not supported with --json", code=2)
        emit_json(payload)
        return
    for line in payload["lines"]:
        typer.echo(line)
    if not follow:
        return

    path = Path(payload["path"])
    try:
        position = path.stat().st_size if path.exists() else 0
        while True:
            if path.exists():
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    for line in handle:
                        typer.echo(line.rstrip("\n"))
                    position = handle.tell()
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


@app.command("watch")
def watch_command(
    ctx: typer.Context,
    monitor: str = typer.Argument(...),
    interval: float = typer.Option(1.0, "--interval", min=0.2, max=30.0),
) -> None:
    """Live monitor progress until interrupted with Ctrl-C."""
    state = _state(ctx)
    if state.json_output:
        emit_error(state, "watch is an interactive command; use 'monitor status' with --json", code=2)
    try:
        first = get_monitor(monitor)
    except Exception as exc:
        _fail(ctx, exc, code=7)
        return
    if first is None:
        emit_error(state, f"monitor {monitor!r} not found", code=3)

    console = console_for(state)
    try:
        with Live(_watch_table(first), console=console, refresh_per_second=4) as live:
            while True:
                current = get_monitor(monitor)
                if current is None:
                    break
                live.update(_watch_table(current))
                time.sleep(interval)
    except KeyboardInterrupt:
        return
