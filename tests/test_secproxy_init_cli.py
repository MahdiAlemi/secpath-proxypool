from __future__ import annotations

from typer.main import get_command
from typer.testing import CliRunner

from secproxy_cli.app import app

runner = CliRunner()


def test_init_command_is_registered():
    root = get_command(app)
    assert "init" in root.commands


def test_init_help_is_available():
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0


def test_init_service_is_idempotent_on_current_database():
    from secproxy_cli.services.init_service import initialize_database

    first = initialize_database()
    second = initialize_database()

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["database"] == second["database"]
    assert first["tables"] == second["tables"]
    assert "proxies" in second["tables"]
    assert "import_sources" in second["tables"]
