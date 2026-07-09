#!/usr/bin/env python3
"""
Migrate data from SQLite to MySQL
Usage: python migrate.py
"""
import sqlite3
from tqdm import tqdm
from database import db, Proxy, init_db
from config import config

def migrate_sqlite_to_mysql():
    """Migrate all data from SQLite to MySQL"""
    
    print("[*] Starting migration from SQLite to MySQL...")
    print(f"[*] SQLite DB: {config.SQLITE_DB_PATH}")
    print(f"[*] MySQL: {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    
    # Connect to SQLite
    try:
        sqlite_conn = sqlite3.connect(config.SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()
        print("[+] Connected to SQLite")
    except Exception as e:
        print(f"[!] Failed to connect to SQLite: {e}")
        return
    
    # Get count
    sqlite_cur.execute("SELECT COUNT(*) as cnt FROM proxies")
    total = sqlite_cur.fetchone()['cnt']
    print(f"[*] Found {total} proxies in SQLite")
    
    if total == 0:
        print("[!] No data to migrate")
        sqlite_conn.close()
        return
    
    # Initialize MySQL tables
    print("[*] Creating MySQL tables...")
    init_db()
    
    # Fetch all data from SQLite
    print("[*] Fetching data from SQLite...")
    sqlite_cur.execute("""
        SELECT * FROM proxies
    """)
    
    rows = sqlite_cur.fetchall()
    
    # Migrate in batches
    batch_size = 1000
    migrated = 0
    errors = 0
    
    print(f"[*] Migrating {total} proxies to MySQL...")
    
    with db.session() as session:
        for i, row in enumerate(tqdm(rows, desc="Migrating", unit="proxies")):
            try:
                proxy = Proxy(
                    id=row['id'],
                    protocol=row['protocol'],
                    ip=row['ip'],
                    port=row['port'],
                    username=row['username'] or '',
                    password=row['password'] or '',
                    resolved_ip=row['resolved_ip'],
                    cost=row['cost'] or 1.0,
                    alive_hits=row['alive_hits'] or 0,
                    last_alive=_parse_datetime(row['last_alive']),
                    last_checked=_parse_datetime(row['last_checked']),
                    fail_hits=row['fail_hits'] or 0,
                    last_fail=_parse_datetime(row['last_fail']),
                    speed_ms=row['speed_ms'],
                    continent=row['continent'],
                    continentCode=row['continentCode'],
                    country=row['country'],
                    countryCode=row['countryCode'],
                    region=row['region'],
                    regionName=row['regionName'],
                    city=row['city'],
                    district=row['district'],
                    zip=row['zip'],
                    lat=row['lat'],
                    lon=row['lon'],
                    timezone=row['timezone'],
                    isp=row['isp'],
                    org=row['org'],
                    asn=row['asn'],
                    asname=row['asname'],
                    mobile=row['mobile'],
                    proxy=row['proxy'],
                    hosting=row['hosting'],
                    last_geo=_parse_datetime(row['last_geo']),
                )
                session.add(proxy)
                migrated += 1
                
                # Commit every batch
                if (i + 1) % batch_size == 0:
                    session.commit()
                    session.expunge_all()
                    
            except Exception as e:
                errors += 1
                if errors < 5:  # Show first few errors
                    print(f"[!] Error migrating proxy {row.get('id', 'unknown')}: {e}")
                continue
    
    sqlite_conn.close()
    
    # Verify migration
    with db.session() as session:
        mysql_count = session.query(Proxy).count()
    
    print("\n" + "="*50)
    print("Migration Complete!")
    print(f"SQLite count: {total}")
    print(f"MySQL count:  {mysql_count}")
    print(f"Migrated:     {migrated}")
    print(f"Errors:       {errors}")
    
    if mysql_count == total:
        print("[✓] Migration successful - counts match!")
    else:
        print("[!] Warning - counts don't match. Some records may have been skipped.")
    print("="*50)

def _parse_datetime(dt_str):
    """Parse ISO datetime string to datetime object"""
    if not dt_str:
        return None
    try:
        from datetime import datetime
        # Handle ISO format with timezone
        if 'T' in dt_str:
            # Remove timezone info for simplicity
            dt_str = dt_str.replace('Z', '+00:00')
            if '+' in dt_str:
                dt_str = dt_str.split('+')[0]
            return datetime.fromisoformat(dt_str)
        return None
    except:
        return None

if __name__ == "__main__":
    # Check if we should add tqdm
    try:
        from tqdm import tqdm
    except ImportError:
        print("[!] Installing tqdm for progress bar...")
        import subprocess
        subprocess.run(["pip", "install", "tqdm"], check=True)
        from tqdm import tqdm
    
    migrate_sqlite_to_mysql()
