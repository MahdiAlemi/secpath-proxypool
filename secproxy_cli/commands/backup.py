from __future__ import annotations

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services import backup_service as svc
from secproxy_cli.state import CLIState

app = typer.Typer(help="Create, verify, restore, and manage local database backups.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception, code: int = 1) -> None:
    state = _state(ctx)
    emit_error(state, str(exc), code=code, details=str(exc) if state.verbose else None)


@app.command("create")
def create_command(
    ctx: typer.Context,
    label: str | None = typer.Option(None, "--label"),
) -> None:
    """Create a consistent SQLite backup."""
    state = _state(ctx)
    try:
        item = svc.create_backup(label=label)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(item)
        return
    emit_kv(state, "Backup Created", item)


@app.command("list")
def list_command(ctx: typer.Context) -> None:
    """List SecProxy-managed database backups."""
    state = _state(ctx)
    try:
        rows = svc.list_backups()
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    emit_table(
        state,
        title=f"Backups ({len(rows)})",
        columns=["Name", "Created", "Bytes", "Integrity"],
        rows=[(x["name"], x["created_at"], x["bytes"], x.get("integrity")) for x in rows],
        json_rows=rows,
    )


@app.command("verify")
def verify_command(ctx: typer.Context, backup: str = typer.Argument(...)) -> None:
    """Run SQLite integrity_check and SHA-256 over a backup."""
    state = _state(ctx)
    try:
        item = svc.verify_backup(backup)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(item)
        return
    emit_kv(
        state,
        "Backup Verification",
        {
            "Name": item["name"],
            "OK": item["ok"],
            "Integrity": item["integrity"],
            "Bytes": item["bytes"],
            "SHA-256": item["sha256"],
            "Tables": len(item["tables"]),
        },
    )


@app.command("restore")
def restore_command(
    ctx: typer.Context,
    backup: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive restore"),
) -> None:
    """Restore a verified SQLite backup after creating a safety backup."""
    state = _state(ctx)
    if not yes:
        if state.json_output:
            emit_error(state, "restore requires --yes in JSON/non-interactive mode", code=2)
        confirmed = typer.confirm(
            "Restore replaces the active SQLite database. Stop the dashboard and all external writers first. Continue?",
            default=False,
        )
        if not confirmed:
            raise typer.Abort()
    try:
        item = svc.restore_backup(backup)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(item)
        return
    emit_kv(state, "Backup Restored", item)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    backup: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a SecProxy-managed backup."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete backup {backup!r}?", default=False):
        raise typer.Abort()
    try:
        item = svc.delete_backup(backup)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(item)
    else:
        emit_kv(state, "Backup Deleted", item)
