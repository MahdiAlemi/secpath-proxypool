from __future__ import annotations

import typer

from secproxy_cli.output import emit_kv
from secproxy_cli.services.init_service import initialize_database
from secproxy_cli.state import CLIState


def init_command(ctx: typer.Context) -> None:
    """Initialize or repair the SecProxy database schema without deleting data."""
    state: CLIState = ctx.obj
    result = initialize_database()

    emit_kv(
        state,
        "SecProxy Init",
        {
            "Database": result["database"],
            "Schema ready": result["schema_ready"],
            "Tables": result["table_count"],
        },
    )
