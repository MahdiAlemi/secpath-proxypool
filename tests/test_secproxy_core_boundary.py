from pathlib import Path
from secproxy_core.server import _is_local_bind, _normalize_server_config
from secproxy_core.monitor import _normalize_profile

def test_core_server_is_framework_neutral_for_cli():
    assert _is_local_bind("127.0.0.1")
    cfg = _normalize_server_config({
        "port": 18080,
        "protocol": "http",
        "bind": "127.0.0.1",
        "candidate_statuses": "dead",
        "upstream_protocol": "socks5",
    })
    assert cfg["port"] == 18080
    assert cfg["candidate_statuses"] == "dead"

def test_core_server_blocks_public_unauthenticated_bind():
    try:
        _normalize_server_config({"port": 18081, "protocol": "http", "bind": "0.0.0.0"})
    except ValueError as exc:
        assert "unauthenticated listeners beyond loopback are blocked" in str(exc)
    else:
        raise AssertionError("public unauthenticated bind was not blocked")

def test_core_monitor_profile_normalization_without_flask_route_import():
    profile, safe = _normalize_profile({
        "name": "Core Test",
        "protocol": "socks5",
        "status": "dead",
        "threads": 20,
        "timeout": 3,
        "probes": 1,
    })
    assert safe == "core-test"
    assert profile["protocol"] == "socks5"

def test_cli_services_do_not_import_dashboard_routes():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "secproxy_cli/services/monitor_service.py",
        "secproxy_cli/services/server_service.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "dashboard.routes" not in text
