from __future__ import annotations

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv
from secproxy_cli.services.status_service import collect_status
from secproxy_cli.state import CLIState


def _fraction(section: dict, numerator: str, denominator: str = "configured") -> str:
    return f'{section.get(numerator, 0)}/{section.get(denominator, 0)}'


def status_command(ctx: typer.Context) -> None:
    """Show a compact operational summary."""
    state: CLIState = ctx.obj
    try:
        data = collect_status()
    except Exception as exc:
        emit_error(state, "could not read project status", code=7, details=str(exc))
        return

    if state.json_output:
        emit_json(data)
        return

    proxies = data["proxies"]
    statuses = proxies["statuses"]
    caps = proxies["capabilities"]
    emit_kv(
        state,
        "SecProxy Status",
        {
            "Database": data["database"]["dialect"],
            "Proxies": proxies["total"],
            "Alive": statuses.get("alive", 0),
            "Untested": statuses.get("untested", 0),
            "Dead": statuses.get("dead", 0),
            "HTTPS capable": caps["web_https"],
            "Remote DNS": caps["remote_dns"],
            "Telegram": caps["telegram"],
            "Sources enabled": _fraction(data["sources"], "enabled"),
            "Monitors running": _fraction(data["monitors"], "running"),
            "Servers running": _fraction(data["servers"], "running"),
            "Users": data["users"]["configured"],
            "Backups": data["backups"]["configured"],
        },
    )
