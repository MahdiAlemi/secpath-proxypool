from typer.testing import CliRunner

from secproxy_cli.app import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "secproxy" in result.output.lower()
    assert "proxy" in result.output.lower()
    assert "doctor" in result.output.lower()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("secproxy ")
