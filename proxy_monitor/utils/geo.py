import socket
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

from proxy_monitor.utils.logging import log


def resolve_host(host: str) -> Optional[str]:
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def geo_expired(last_geo) -> bool:
    if last_geo is None:
        return True
    if isinstance(last_geo, str):
        try:
            last_geo = datetime.fromisoformat(last_geo.replace("Z", "+00:00"))
        except Exception:
            return True
    if isinstance(last_geo, datetime):
        now = datetime.now(timezone.utc)
        if last_geo.tzinfo is None:
            last_geo = last_geo.replace(tzinfo=timezone.utc)
        age = now - last_geo
        return age > timedelta(days=7)
    return True


def fetch_geo_info(ip: str) -> Optional[dict]:
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,continent,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,mobile,hosting,query", timeout=5)
        data = r.json()
        if data.get("status") == "success":
            return data
    except Exception as e:
        log("[GEO] Failed to fetch geo for {}: {}", ip, e)
    return None
