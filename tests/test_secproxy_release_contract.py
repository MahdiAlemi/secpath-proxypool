from pathlib import Path
import tomllib

from typer.testing import CliRunner

from secproxy_cli.app import app
from secproxy_core.server import _normalize_server_config

runner = CliRunner()


def test_release_command_tree():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "status",
        "doctor",
        "proxy",
        "source",
        "monitor",
        "server",
        "insights",
        "backup",
        "cleanup",
        "user",
        "config",
    ):
        assert command in result.stdout


def test_credential_export_cannot_go_to_stdout():
    result = runner.invoke(app, ["proxy", "export", "--include-credentials"])
    assert result.exit_code == 2
    normalized = " ".join(result.output.split())
    assert "credentials are never emitted to stdout" in normalized


def test_public_unauthenticated_listener_stays_blocked():
    try:
        _normalize_server_config(
            {
                "port": 18081,
                "protocol": "http",
                "bind": "0.0.0.0",
                "candidate_statuses": "dead",
            }
        )
    except ValueError as exc:
        assert "unauthenticated listeners beyond loopback are blocked" in str(exc)
    else:
        raise AssertionError("public unauthenticated listener was accepted")


def test_cli_services_do_not_import_flask_routes():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "secproxy_cli/services/monitor_service.py",
        "secproxy_cli/services/server_service.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "dashboard.routes" not in text


def test_packaging_declares_console_script_and_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["secproxy"] == "secproxy_cli.app:main"
    assert "dependencies" in data["project"]["dynamic"]
    assert data["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == [
        "requirements.txt"
    ]
    includes = data["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "secproxy_cli*" in includes
    assert "secproxy_core*" in includes



def test_dev_requirements_include_pytest():
    root = Path(__file__).resolve().parents[1]
    text = (root / "requirements-dev.txt").read_text(encoding="utf-8").lower()
    active = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any(line.startswith("pytest") for line in active)
