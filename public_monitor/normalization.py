from __future__ import annotations

from urllib.parse import unquote, urlparse

SUPPORTED_PROTOCOLS = {"http", "https", "socks4", "socks5"}


def normalize_proxy_line(
    line: object,
    default_protocol: object = "http",
) -> tuple[str, str, int, str | None, str | None] | None:
    """Normalize common public proxy-list formats without application imports.

    Supported examples include URL form, ``host:port``, protocol-prefixed
    entries, whitespace-separated host/port pairs, legacy credentials, and
    bracketed IPv6 addresses.
    """

    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None

    protocol = str(default_protocol or "http").strip().lower()
    username: str | None = None
    password: str | None = None

    if "://" in text:
        try:
            parsed = urlparse(text)
            if (
                parsed.scheme.lower() not in SUPPORTED_PROTOCOLS
                or not parsed.hostname
                or parsed.port is None
            ):
                return None
            return (
                parsed.scheme.lower(),
                parsed.hostname,
                parsed.port,
                unquote(parsed.username) if parsed.username is not None else None,
                unquote(parsed.password) if parsed.password is not None else None,
            )
        except ValueError:
            return None

    tokens = text.split()
    if tokens and tokens[0].lower() in SUPPORTED_PROTOCOLS:
        protocol = tokens.pop(0).lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        return None

    auth: list[str]
    if len(tokens) >= 2 and tokens[1].isdigit():
        host = tokens[0].strip("[]")
        port_text = tokens[1]
        auth = tokens[2:4]
    elif tokens:
        address = tokens[0]
        auth = tokens[1:3]
        host: str | None = None
        port_text: str | None = None

        if address.startswith("["):
            closing = address.find("]")
            if closing <= 1 or closing + 1 >= len(address) or address[closing + 1] != ":":
                return None
            host = address[1:closing]
            port_text = address[closing + 2 :]
        else:
            legacy = address.split(":", 3)
            if len(legacy) == 4 and legacy[1].isdigit():
                host, port_text, embedded_user, embedded_password = legacy
                if not auth:
                    auth = [embedded_user, embedded_password]
            elif len(legacy) == 2:
                host, port_text = legacy
            else:
                return None
    else:
        return None

    if not host or not port_text or not port_text.isdigit():
        return None

    port = int(port_text)
    if not 1 <= port <= 65535:
        return None

    if auth:
        username = auth[0] if len(auth) >= 1 else None
        password = auth[1] if len(auth) >= 2 else None

    return protocol, host, port, username, password
