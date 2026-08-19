from typer.main import get_command

from secproxy_cli.app import app


def _server_command(name: str):
    root = get_command(app)
    server = root.commands["server"]
    return server.commands[name]


def _option_map(command):
    options = {}
    for param in command.params:
        for opt in getattr(param, "opts", ()) or ():
            options[opt] = param
    return options


def test_server_help_registers_commands():
    root = get_command(app)
    server = root.commands["server"]
    expected = {
        "list", "show", "status", "preview", "create", "edit",
        "start", "stop", "restart", "delete", "logs", "test",
    }
    assert expected.issubset(server.commands)


def test_server_create_help_exposes_safe_bind_default():
    options = _option_map(_server_command("create"))
    assert "--bind" in options
    assert options["--bind"].default == "127.0.0.1"
    assert "--allow-public-no-auth" in options
    assert options["--allow-public-no-auth"].default is False


def test_server_test_help_has_connect_only():
    options = _option_map(_server_command("test"))
    assert "--connect-only" in options
