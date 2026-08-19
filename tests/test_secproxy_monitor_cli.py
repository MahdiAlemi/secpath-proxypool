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


def test_monitor_help_is_registered():
    result = runner.invoke(app, ["monitor", "--help"])
    assert result.exit_code == 0
    for command in ("list", "show", "preview", "create", "edit", "start", "pause", "resume", "stop", "restart", "results", "logs", "watch"):
        assert command in result.stdout


def test_monitor_create_help_is_available():
    options = _option_map(_subcommand("monitor", "create"))
    assert "--protocol" in options
