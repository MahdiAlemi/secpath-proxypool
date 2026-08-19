from pathlib import Path

from typer.testing import CliRunner

from secproxy_cli.app import app
from secproxy_core.proxy_service import render_export

runner = CliRunner()


def test_proxy_commands_registered():
    result = runner.invoke(app, ["proxy", "--help"])
    assert result.exit_code == 0
    for name in ("list", "show", "count", "add", "edit", "delete", "purge", "test", "export"):
        assert name in result.stdout


def test_export_never_needs_credentials_by_default():
    rows = [{
        "id": 1,
        "protocol": "socks5",
        "ip": "1.2.3.4",
        "port": 1080,
        "status": "alive",
        "speed_ms": 100,
        "country": "DE",
        "web_http_ok": True,
        "web_https_ok": True,
        "remote_dns_ok": True,
        "telegram_ok": False,
        "has_auth": True,
    }]
    text = render_export(rows, format="urls", include_credentials=False)
    assert text == "socks5://1.2.3.4:1080\n"
    assert "@" not in text


def test_cli_proxy_service_is_core_forwarder():
    root = Path(__file__).resolve().parents[1]
    text = (root / "secproxy_cli/services/proxy_service.py").read_text(encoding="utf-8")
    assert "secproxy_core.proxy_service" in text
