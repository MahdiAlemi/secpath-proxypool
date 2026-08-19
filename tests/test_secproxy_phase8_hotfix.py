from pathlib import Path

from typer.testing import CliRunner

from secproxy_cli.app import app
from typer.main import get_command

runner = CliRunner()

def _subcommand(group: str, command: str):
    root = get_command(app)
    return root.commands[group].commands[command]

def _option_map(command):
    options = {}
    for param in command.params:
        for opt in getattr(param, "opts", ()) or ():
            options[opt] = param
    return options


def test_proxy_help_has_secure_password_inputs():
    options = _option_map(_subcommand("proxy", "add"))
    assert "--password-prompt" in options
    assert "--password-stdin" in options


def test_proxy_test_help_has_separate_timeouts():
    options = _option_map(_subcommand("proxy", "test"))
    assert "--connect-timeout" in options
    assert "--timeout" in options


def test_proxy_service_remains_core_implementation():
    root = Path(__file__).resolve().parents[1]
    text = (root / "secproxy_core/proxy_service.py").read_text(encoding="utf-8")
    assert "trust_env = False" in text
    assert '"stage": "response"' in text
