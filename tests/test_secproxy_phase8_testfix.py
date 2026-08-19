from pathlib import Path


def test_proxy_test_exception_message_is_captured_inside_except():
    root = Path(__file__).resolve().parents[1]
    text = (root / "secproxy_core/proxy_service.py").read_text(encoding="utf-8")
    assert "error_text = str(exc)[:500]" in text
    assert '"error": error_text' in text
    # Guard against the exact regression we hit: using exc after the except block.
    tail = text[text.index("def test_proxy("):]
    assert '"error": str(exc)[:500]' not in tail
