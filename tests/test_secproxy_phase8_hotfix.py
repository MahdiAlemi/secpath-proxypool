from pathlib import Path

from typer.testing import CliRunner

from secproxy_cli.app import app

runner = CliRunner()


def test_proxy_help_has_secure_password_inputs():
    result = runner.invoke(app, ["proxy", "add", "--help"])
    assert result.exit_code == 0
    assert "--password-prompt" in result.stdout
    assert "--password-stdin" in result.stdout


def test_proxy_test_help_has_separate_timeouts():
    result = runner.invoke(app, ["proxy", "test", "--help"])
    assert result.exit_code == 0
    assert "--connect-timeout" in result.stdout
    assert "--timeout" in result.stdout


def test_proxy_service_remains_core_implementation():
    root = Path(__file__).resolve().parents[1]
    text = (root / "secproxy_core/proxy_service.py").read_text(encoding="utf-8")
    assert "trust_env = False" in text
    assert '"stage": "response"' in text
