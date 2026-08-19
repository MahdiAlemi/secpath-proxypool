from __future__ import annotations

import typer

from secproxy_cli.output import emit_error, emit_json, emit_kv, emit_table
from secproxy_cli.services import insights_service as svc
from secproxy_cli.state import CLIState

app = typer.Typer(help="Inspect proxy-pool health and inventory analytics.", no_args_is_help=True)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.obj


def _fail(ctx: typer.Context, exc: Exception) -> None:
    emit_error(_state(ctx), str(exc), code=7, details=str(exc) if _state(ctx).verbose else None)


@app.command("summary")
def summary_command(ctx: typer.Context) -> None:
    """Show a compact inventory analytics summary."""
    state = _state(ctx)
    try:
        data = svc.summary()
    except Exception as exc:
        _fail(ctx, exc)
        return
    if state.json_output:
        emit_json(data)
        return
    emit_kv(
        state,
        "Insights Summary",
        {
            "Total proxies": data["total"],
            "Latency samples": data["latency"]["samples"],
            "Average latency": f'{data["latency"]["avg_ms"]} ms' if data["latency"]["avg_ms"] is not None else None,
        },
    )
    emit_table(
        state,
        title="Statuses",
        columns=["Status", "Count"],
        rows=[(x["value"], x["count"]) for x in data["statuses"]],
    )
    emit_table(
        state,
        title="Protocols",
        columns=["Protocol", "Count"],
        rows=[(x["value"], x["count"]) for x in data["protocols"]],
    )
    emit_table(
        state,
        title="Capabilities",
        columns=["Capability", "Count"],
        rows=[(k, v) for k, v in data["capabilities"].items()],
    )


@app.command("health")
def health_command(ctx: typer.Context) -> None:
    """Break down proxy health/status distribution."""
    state = _state(ctx)
    try:
        rows = svc.health()
    except Exception as exc:
        _fail(ctx, exc)
        return
    emit_table(
        state,
        title="Proxy Health",
        columns=["Status", "Count", "Percent"],
        rows=[(x["value"], x["count"], f'{x["percent"]}%') for x in rows],
        json_rows=rows,
    )


@app.command("protocols")
def protocols_command(ctx: typer.Context) -> None:
    """Break down proxy inventory by protocol."""
    state = _state(ctx)
    try:
        rows = svc.protocols()
    except Exception as exc:
        _fail(ctx, exc)
        return
    emit_table(
        state,
        title="Protocols",
        columns=["Protocol", "Count"],
        rows=[(x["value"], x["count"]) for x in rows],
        json_rows=rows,
    )


@app.command("capabilities")
def capabilities_command(ctx: typer.Context) -> None:
    """Show verified capability coverage."""
    state = _state(ctx)
    try:
        rows = svc.capabilities()
    except Exception as exc:
        _fail(ctx, exc)
        return
    emit_table(
        state,
        title="Capabilities",
        columns=["Capability", "Count", "Percent"],
        rows=[(x["capability"], x["count"], f'{x["percent"]}%') for x in rows],
        json_rows=rows,
    )


@app.command("latency")
def latency_command(ctx: typer.Context) -> None:
    """Show latency statistics and buckets."""
    state = _state(ctx)
    try:
        data = svc.latency()
    except Exception as exc:
        _fail(ctx, exc)
        return
    if state.json_output:
        emit_json(data)
        return
    emit_kv(
        state,
        "Latency",
        {
            "Samples": data.get("samples"),
            "Average": f'{data["avg_ms"]} ms' if data.get("avg_ms") is not None else None,
            "P50": f'{data["p50_ms"]} ms' if data.get("p50_ms") is not None else None,
            "P95": f'{data["p95_ms"]} ms' if data.get("p95_ms") is not None else None,
            "Minimum": f'{data["min_ms"]} ms' if data.get("min_ms") is not None else None,
            "Maximum": f'{data["max_ms"]} ms' if data.get("max_ms") is not None else None,
        },
    )
    emit_table(
        state,
        title="Latency Buckets",
        columns=["Bucket", "Count"],
        rows=[(x["bucket"], x["count"]) for x in data.get("buckets", [])],
    )


@app.command("countries")
def countries_command(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", min=1, max=500),
) -> None:
    """Show top proxy countries."""
    state = _state(ctx)
    try:
        rows = svc.countries(limit=limit)
    except Exception as exc:
        _fail(ctx, exc)
        return
    emit_table(
        state,
        title="Countries",
        columns=["Country", "Count"],
        rows=[(x["value"], x["count"]) for x in rows],
        json_rows=rows,
    )


@app.command("providers")
def providers_command(
    ctx: typer.Context,
    by: str = typer.Option("isp", "--by", help="isp, org, or asn"),
    limit: int = typer.Option(20, "--limit", min=1, max=500),
) -> None:
    """Show top ISP/organization/ASN values."""
    state = _state(ctx)
    try:
        rows = svc.providers(by=by, limit=limit)
    except Exception as exc:
        _fail(ctx, exc)
        return
    emit_table(
        state,
        title=f"Providers by {by}",
        columns=[by.upper(), "Count"],
        rows=[(x["value"], x["count"]) for x in rows],
        json_rows=rows,
    )
