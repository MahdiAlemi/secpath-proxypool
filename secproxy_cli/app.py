from __future__ import annotations

import typer

from secproxy_cli.commands.backup import app as backup_app
from secproxy_cli.commands.cleanup import app as cleanup_app
from secproxy_cli.commands.config import app as config_app
from secproxy_cli.commands.doctor import doctor_command
from secproxy_cli.commands.insights import app as insights_app
from secproxy_cli.commands.monitor import app as monitor_app
from secproxy_cli.commands.proxy import app as proxy_app
from secproxy_cli.commands.server import app as server_app
from secproxy_cli.commands.source import app as source_app
from secproxy_cli.commands.status import status_command
from secproxy_cli.commands.user import app as user_app
from secproxy_cli.state import CLIState

app = typer.Typer(
    name="secproxy",
    help="Operator CLI for SecPath ProxyPool.",
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_show_locals=False,
)

app.add_typer(proxy_app, name="proxy")
app.add_typer(source_app, name="source")
app.add_typer(monitor_app, name="monitor")
app.add_typer(server_app, name="server")
app.add_typer(insights_app, name="insights")
app.add_typer(backup_app, name="backup")
app.add_typer(cleanup_app, name="cleanup")
app.add_typer(user_app, name="user")
app.add_typer(config_app, name="config")
app.command("status")(status_command)
app.command("doctor")(doctor_command)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        from secpath_meta import VERSION
    except Exception:
        VERSION = "unknown"
    typer.echo(f"secproxy {VERSION}")
    raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose diagnostics"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show CLI/project version and exit",
    ),
) -> None:
    """SecProxy command-line control plane."""
    ctx.obj = CLIState(json_output=json_output, no_color=no_color, verbose=verbose)


def main() -> None:
    app()
