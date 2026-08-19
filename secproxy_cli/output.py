from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from secproxy_cli.state import CLIState


def console_for(state: CLIState, *, stderr: bool = False) -> Console:
    return Console(stderr=stderr, no_color=state.no_color)


def emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str, sort_keys=True))


def emit_error(state: CLIState, message: str, *, code: int = 1, details: Any = None) -> None:
    if state.json_output:
        payload: dict[str, Any] = {"ok": False, "error": message, "code": code}
        if details is not None:
            payload["details"] = details
        emit_json(payload)
    else:
        console_for(state, stderr=True).print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=code)


def emit_kv(state: CLIState, title: str, values: Mapping[str, Any]) -> None:
    if state.json_output:
        emit_json(dict(values))
        return

    table = Table(title=title, show_header=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in values.items():
        table.add_row(str(key), _display(value))
    console_for(state).print(table)


def emit_table(
    state: CLIState,
    *,
    title: str,
    columns: list[str],
    rows: Iterable[Iterable[Any]],
    json_rows: list[Mapping[str, Any]] | None = None,
) -> None:
    if state.json_output:
        emit_json(json_rows if json_rows is not None else [dict(zip(columns, row)) for row in rows])
        return

    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*[_display(value) for value in row])
    console_for(state).print(table)


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
