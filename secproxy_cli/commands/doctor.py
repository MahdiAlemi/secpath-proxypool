from __future__ import annotations

import typer

from secproxy_cli.output import emit_table
from secproxy_cli.services.doctor_service import run_doctor
from secproxy_cli.state import CLIState


def doctor_command(ctx: typer.Context) -> None:
    """Run non-destructive environment, packaging, security, and database diagnostics."""
    state: CLIState = ctx.obj
    checks = run_doctor()

    def result(check: dict) -> str:
        if check["ok"]:
            return "OK"
        if check.get("level") == "warning":
            return "WARN"
        return "FAIL"

    emit_table(
        state,
        title="SecProxy Doctor",
        columns=["Check", "Result", "Detail"],
        rows=[(c["name"], result(c), c["detail"]) for c in checks],
        json_rows=checks,
    )

    fatal = any(
        not check["ok"] and check.get("level", "error") != "warning"
        for check in checks
    )
    if fatal:
        raise typer.Exit(code=1)
