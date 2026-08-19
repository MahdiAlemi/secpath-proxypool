from typer.testing import CliRunner
from secproxy_cli.app import app

runner = CliRunner()


def test_phase5_groups_register():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("insights", "backup", "cleanup", "user"):
        assert name in result.stdout


def test_insights_commands():
    result = runner.invoke(app, ["insights", "--help"])
    assert result.exit_code == 0
    for name in ("summary", "health", "protocols", "capabilities", "latency", "countries", "providers"):
        assert name in result.stdout


def test_backup_commands():
    result = runner.invoke(app, ["backup", "--help"])
    assert result.exit_code == 0
    for name in ("create", "list", "verify", "restore", "delete"):
        assert name in result.stdout


def test_cleanup_commands():
    result = runner.invoke(app, ["cleanup", "--help"])
    assert result.exit_code == 0
    assert "logs" in result.stdout
    assert "runtime" in result.stdout


def test_user_commands():
    result = runner.invoke(app, ["user", "--help"])
    assert result.exit_code == 0
    for name in ("schema", "list", "show", "create", "enable", "disable", "role", "passwd", "delete"):
        assert name in result.stdout
