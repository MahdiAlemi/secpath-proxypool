from __future__ import annotations

import getpass

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services import user_service as svc
from secproxy_cli.state import CLIState

app = typer.Typer(help="Inspect and manage dashboard users from the local host.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception, code: int = 1) -> None:
    state = _state(ctx)
    emit_error(state, str(exc), code=code, details=str(exc) if state.verbose else None)


@app.command("schema")
def schema_command(ctx: typer.Context) -> None:
    """Show the detected User model without exposing password fields."""
    state = _state(ctx)
    try:
        data = svc.schema()
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(data)
        return
    emit_kv(
        state,
        "User Schema",
        {
            "Table": data["table"],
            "Password setter": data["password_setter"],
            "Columns": ", ".join(x["name"] for x in data["columns"]),
        },
    )


@app.command("list")
def list_command(ctx: typer.Context) -> None:
    """List dashboard users without credential material."""
    state = _state(ctx)
    try:
        rows = svc.list_users()
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if not rows:
        if state.json_output:
            emit_json([])
        else:
            emit_kv(state, "Users", {"Count": 0, "Status": "No users configured"})
        return
    keys = []
    if rows:
        preferred = ["id", "username", "email", "role", "is_active", "created_at", "last_login"]
        keys = [k for k in preferred if any(k in row for row in rows)]
        if not keys:
            keys = list(rows[0].keys())[:6]
    emit_table(
        state,
        title=f"Users ({len(rows)})",
        columns=[k.replace("_", " ").title() for k in keys],
        rows=[tuple(row.get(k) for k in keys) for row in rows],
        json_rows=rows,
    )


@app.command("show")
def show_command(ctx: typer.Context, user: str = typer.Argument(...)) -> None:
    """Show one dashboard user without credential material."""
    state = _state(ctx)
    try:
        item = svc.get_user(user)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    if state.json_output:
        emit_json(item)
    else:
        emit_kv(state, f"User {user}", item)


@app.command("create")
def create_command(
    ctx: typer.Context,
    username: str = typer.Argument(...),
    role: str | None = typer.Option(None, "--role"),
    active: bool = typer.Option(True, "--active/--disabled"),
    password: str | None = typer.Option(None, "--password", hide_input=True),
) -> None:
    """Create a dashboard user. Password is prompted securely when omitted."""
    state = _state(ctx)
    if password is None:
        password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        item = svc.create_user(username=username, password=password, role=role, active=active)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if state.json_output:
        emit_json(item)
    else:
        emit_kv(state, "User Created", item)


@app.command("enable")
def enable_command(ctx: typer.Context, user: str = typer.Argument(...)) -> None:
    """Enable a dashboard user."""
    state = _state(ctx)
    try:
        item = svc.set_active(user, True)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    emit_json(item) if state.json_output else emit_kv(state, "User Enabled", item)


@app.command("disable")
def disable_command(ctx: typer.Context, user: str = typer.Argument(...)) -> None:
    """Disable a dashboard user."""
    state = _state(ctx)
    try:
        item = svc.set_active(user, False)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    emit_json(item) if state.json_output else emit_kv(state, "User Disabled", item)


@app.command("role")
def role_command(
    ctx: typer.Context,
    user: str = typer.Argument(...),
    role: str = typer.Argument(...),
) -> None:
    """Change a dashboard user's role."""
    state = _state(ctx)
    try:
        item = svc.set_role(user, role)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    emit_json(item) if state.json_output else emit_kv(state, "User Role Updated", item)


@app.command("passwd")
def passwd_command(
    ctx: typer.Context,
    user: str = typer.Argument(...),
    password: str | None = typer.Option(None, "--password", hide_input=True),
) -> None:
    """Change a dashboard user's password."""
    state = _state(ctx)
    if password is None:
        password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    try:
        item = svc.set_password(user, password)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    emit_json(item) if state.json_output else emit_kv(state, "Password Updated", item)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    user: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a dashboard user; refuses to delete the last account."""
    state = _state(ctx)
    if not yes and not typer.confirm(f"Delete user {user!r}?", default=False):
        raise typer.Abort()
    try:
        item = svc.delete_user(user)
    except Exception as exc:
        _fail(ctx, exc, 7)
        return
    if item is None:
        emit_error(state, f"user {user!r} not found", code=3)
    emit_json(item) if state.json_output else emit_kv(state, "User Deleted", item)
