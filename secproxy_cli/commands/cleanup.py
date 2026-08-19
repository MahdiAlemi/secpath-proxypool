from __future__ import annotations

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services import cleanup_service as svc
from secproxy_cli.state import CLIState

app = typer.Typer(help="Preview and remove stale SecProxy operational files.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _emit_plan(state: CLIState, title: str, rows: list[dict]) -> None:
    emit_table(
        state,
        title=f"{title} ({len(rows)})",
        columns=["Path", "Bytes", "Age days"],
        rows=[(x["path"], x["bytes"], x["age_days"]) for x in rows],
        json_rows=rows,
    )


@app.command("logs")
def logs_command(
    ctx: typer.Context,
    older_than: int = typer.Option(30, "--older-than", min=0, help="Age in days"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Actually delete files"),
) -> None:
    """Preview stale logs; pass --yes to delete them."""
    state = _state(ctx)
    try:
        rows = svc.log_candidates(older_than_days=older_than)
        if not yes:
            _emit_plan(state, "Log cleanup preview", rows)
            return
        result = svc.delete_logs(older_than_days=older_than)
    except Exception as exc:
        emit_error(state, str(exc), code=7)
        return
    if state.json_output:
        emit_json(result)
    else:
        emit_kv(state, "Log Cleanup", result)


@app.command("runtime")
def runtime_command(
    ctx: typer.Context,
    older_than: int = typer.Option(7, "--older-than", min=0, help="Age in days"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Actually delete files"),
) -> None:
    """Preview stale .runtime files; refuses while SecProxy processes are active."""
    state = _state(ctx)
    try:
        rows = svc.runtime_candidates(older_than_days=older_than)
        if not yes:
            _emit_plan(state, "Runtime cleanup preview", rows)
            return
        result = svc.delete_runtime(older_than_days=older_than)
    except Exception as exc:
        emit_error(state, str(exc), code=7)
        return
    if state.json_output:
        emit_json(result)
    else:
        emit_kv(state, "Runtime Cleanup", result)
