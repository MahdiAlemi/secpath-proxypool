import argparse
import requests
from urllib.parse import urlparse

from database import init_db, insert_proxy, get_proxy_count


def import_from_url(default_protocol, url):
    print(f"[+] Fetching {default_protocol} proxies from: {url}")
    
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[!] Failed to fetch {url}: {e}")
        return
    
    seen = set()
    added = 0
    skipped = 0
    
    for raw_line in r.text.splitlines():
        result = normalize_proxy_line(raw_line, default_protocol)
        
        if not result:
            skipped += 1
            continue
        
        protocol, ip, port, username, password = result
        key = (protocol, ip, port, username or '', password or '')
        
        if key in seen:
            continue
        seen.add(key)
        
        try:
            if insert_proxy(
                protocol=protocol,
                ip=ip,
                port=port,
                username=username or '',
                password=password or ''
            ):
                added += 1
        except Exception as e:
            print(f"[!] DB error {key}: {e}")
    
    print(f"[✓] Added {added} | Skipped {skipped} | Unique {len(seen)}")


def import_from_links(file_path):
    current_protocol = None
    protocols = {"http", "https", "socks4", "socks5"}
    
    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            
            if not line or line.startswith("#"):
                continue
            
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].lower()
                if section not in protocols:
                    print(f"[!] Unknown section: {section}, skipping")
                    current_protocol = None
                else:
                    current_protocol = section
                continue
            
            if current_protocol:
                import_from_url(current_protocol, line)


def import_from_manual(file_path):
    with open(file_path, "r", encoding="utf-8") as source:
        for raw_line in source:
            result = normalize_proxy_line(raw_line, "http")
            if not result:
                continue
            protocol, ip, port, username, password = result
            try:
                insert_proxy(protocol, ip, port, username or "", password or "")
            except Exception as exc:
                print(f"[!] Error inserting {ip}:{port} -> {exc}")


def normalize_proxy_line(line, default_protocol):
    """Normalize common proxy-list formats.

    Supported examples:
    - ``http://user:pass@host:8080``
    - ``http host:8080 user pass``
    - ``http host 8080 user pass``
    - ``host:8080:user:pass``
    - ``[2001:db8::1]:8080``
    """
    from urllib.parse import unquote

    line = str(line or "").strip()
    if not line or line.startswith("#"):
        return None

    protocol = str(default_protocol or "http").strip().lower()
    username = password = None

    if "://" in line:
        try:
            parsed = urlparse(line)
            if not parsed.scheme or not parsed.hostname or parsed.port is None:
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

    tokens = line.split()
    if tokens and tokens[0].lower() in {"http", "https", "socks4", "socks5"}:
        protocol = tokens.pop(0).lower()

    if len(tokens) >= 2 and tokens[1].isdigit():
        host = tokens[0].strip("[]")
        port_text = tokens[1]
        auth = tokens[2:4]
    elif tokens:
        address = tokens[0]
        auth = tokens[1:3]
        host = None
        port_text = None

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["links", "manual"], required=True)
    parser.add_argument("--file", required=True, help="Path to input file")
    args = parser.parse_args()
    
    print("[*] Initializing database...")
    init_db()
    
    initial_count = get_proxy_count()
    print(f"[*] Current proxy count: {initial_count}")
    
    if args.mode == "links":
        import_from_links(args.file)
    elif args.mode == "manual":
        import_from_manual(args.file)
    
    final_count = get_proxy_count()
    print(f"[+] Import finished! Added {final_count - initial_count} new proxies.")
    print(f"[+] Total proxies in database: {final_count}")


if __name__ == "__main__":
    main()
