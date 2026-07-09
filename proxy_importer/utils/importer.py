import re
import time
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
        key = (protocol, ip, port)
        
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
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            protocol, ip, port = parts[:3]
            user = parts[3] if len(parts) > 3 else None
            password = parts[4] if len(parts) > 4 else None
            
            try:
                insert_proxy(protocol, ip, int(port), user or '', password or '')
            except Exception as e:
                print(f"[!] Error inserting {ip}:{port} -> {e}")


def normalize_proxy_line(line, default_protocol):
    line = line.strip()
    
    if not line:
        return None
    
    protocol = default_protocol
    username = password = None
    
    if "://" in line:
        parsed = urlparse(line)
        protocol = parsed.scheme.lower()
        ip = parsed.hostname
        port = parsed.port
        if not ip or not port:
            return None
        return protocol, ip, port, None, None
    
    parts = line.split(":")
    
    if len(parts) >= 2:
        ip = parts[0]
        port = parts[1]
        
        if not port.isdigit():
            return None
        
        port = int(port)
        
        if len(parts) >= 4:
            username = parts[2]
            password = parts[3]
        
        return protocol, ip, port, username, password
    
    return None


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
