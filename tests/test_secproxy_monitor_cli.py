from typer.testing import CliRunner

from secproxy_cli.app import app

runner = CliRunner()


def test_monitor_help_is_registered():
    result = runner.invoke(app, ["monitor", "--help"])
    assert result.exit_code == 0
    for command in ("list", "show", "preview", "create", "edit", "start", "pause", "resume", "stop", "restart", "results", "logs", "watch"):
        assert command in result.stdout


def test_monitor_create_help_is_available():
    result = runner.invoke(app, ["monitor", "create", "--help"])
    assert result.exit_code == 0
    assert "--protocol" in result.stdout
    assert "--status" in result.stdout
    assert "--run-mode" in result.stdout
