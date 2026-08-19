from __future__ import annotations

import typer

from secproxy_cli.output import emit_json, emit_kv, emit_table
from secproxy_cli.services.config_service import config_snapshot, env_path, validate_config
from secproxy_cli.state import CLIState

app = typer.Typer(help="Inspect and validate SecProxy configuration.", no_args_is_help=True)


@app.command("show")
def show(ctx: typer.Context) -> None:
    """Show effective non-secret configuration."""
    state: CLIState = ctx.obj
    data = config_snapshot()
    emit_kv(state, "SecProxy Configuration", data)


@app.command("path")
def path(ctx: typer.Context) -> None:
    """Print the .env path used by the project."""
    state: CLIState = ctx.obj
    value = str(env_path())
    if state.json_output:
        emit_json({"env_file": value})
    else:
        typer.echo(value)


@app.command("check")
def check(ctx: typer.Context) -> None:
    """Validate configuration without mutating anything."""
    state: CLIState = ctx.obj
    checks = validate_config()
    emit_table(
        state,
        title="Configuration Checks",
        columns=["Check", "Result", "Detail"],
        rows=[(c["name"], "OK" if c["ok"] else "FAIL", c["detail"]) for c in checks],
        json_rows=checks,
    )
    if not all(c["ok"] for c in checks):
        raise typer.Exit(code=1)
