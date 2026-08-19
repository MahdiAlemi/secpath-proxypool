from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from secproxy_core.errors import ConflictError
from urllib.parse import quote


def _server_module():
    # Framework-neutral core: no Flask route import or request context.
    from secproxy_core import server as server_core
    return server_core


def _public_proxy(proxy: Any) -> dict[str, Any]:
    """Serialize an upstream proxy without exposing stored credentials."""
    data = proxy.to_dict()
    data.pop("username", None)
    data.pop("password", None)
    data["has_auth"] = bool(getattr(proxy, "username", None) or getattr(proxy, "password", None))
    return data


def _candidate_query(session: Any, data: dict[str, Any]):
    return _server_module()._candidate_query(session, data)

def _candidate_snapshot(session: Any, data: dict[str, Any], *, sample_limit: int = 5) -> dict[str, Any]:
    return _server_module()._candidate_snapshot(session, data, sample_limit=sample_limit)

def _config_api():
    from secproxy_core.config_store import load_servers_config, save_servers_config
    return load_servers_config, save_servers_config


def _root_dir() -> str:
    return _server_module()._project_root()


def _port(value: str | int) -> str:
    return str(_server_module()._parse_port(value))


def _public_profile(port: str, profile: dict[str, Any]) -> dict[str, Any]:
    from proxy_server.lifecycle import snapshot

    m = _server_module()
    saved = dict(profile.get("config") or {})
    try:
        normalized = m._normalize_server_config(saved, existing=saved)
    except Exception:
        normalized = saved
    status = snapshot(_root_dir(), port)
    bind = str(normalized.get("bind") or "127.0.0.1")
    protocol = str(normalized.get("protocol") or profile.get("protocol") or "http")
    safe_host = f"[{bind}]" if ":" in bind and not bind.startswith("[") else bind
    public_config = m._public_server_config(normalized)
    return {
        "port": int(port),
        "name": public_config.get("name") or f"{protocol.upper()} :{port}",
        "protocol": protocol,
        "bind": bind,
        "uri": f"{protocol}://{safe_host}:{port}",
        "scope": "local" if m._is_local_bind(bind) else "network",
        "running": bool(status.get("running")),
        "starting": bool(status.get("starting")),
        "pid": status.get("pid"),
        "process_create_time": status.get("process_create_time"),
        "has_auth": bool(public_config.get("has_auth")),
        "config": public_config,
    }


def list_servers() -> list[dict[str, Any]]:
    load_servers_config, _ = _config_api()
    config = load_servers_config()
    result = []
    for raw_port, profile in config.items():
        try:
            port = _port(raw_port)
        except ValueError:
            continue
        result.append(_public_profile(port, profile))
    result.sort(key=lambda item: item["port"])
    return result


def get_server(port: str | int, *, include_candidates: bool = True, sample_limit: int = 6) -> dict[str, Any] | None:
    load_servers_config, _ = _config_api()
    port_key = _port(port)
    profile = load_servers_config().get(port_key)
    if not profile:
        return None
    item = _public_profile(port_key, profile)
    if include_candidates:
        from database import db

        m = _server_module()
        saved = profile.get("config", {})
        normalized = m._normalize_server_config(saved, existing=saved)
        with db.session() as session:
            item["candidates"] = _candidate_snapshot(session, normalized, sample_limit=sample_limit)
    return item


def normalize_config(data: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    return _server_module()._normalize_server_config(data, existing=existing)


def preview_server(data: dict[str, Any], *, existing_port: str | int | None = None) -> dict[str, Any]:
    from database import db

    load_servers_config, _ = _config_api()
    existing = None
    if existing_port is not None:
        port_key = _port(existing_port)
        profile = load_servers_config().get(port_key)
        if not profile:
            raise LookupError(f"No server profile on port {port_key}")
        existing = profile.get("config", {})
    normalized = normalize_config(data, existing=existing)
    m = _server_module()
    with db.session() as session:
        snap = _candidate_snapshot(session, normalized, sample_limit=6)
    warnings: list[str] = []
    if snap["total"] == 0:
        warnings.append("No proxies match this server profile. Loosen filters or run a monitor first.")
    if normalized.get("require_telegram") and not normalized.get("require_remote_dns"):
        warnings.append("Telegram routing usually needs remote DNS; enable the Remote DNS requirement.")
    if not normalized.get("require_web_https") and normalized.get("use_case") in {"web", "telegram"}:
        warnings.append("This preset normally requires verified HTTPS capability.")
    if (
        not m._is_local_bind(normalized.get("bind"))
        and not normalized.get("username")
        and not normalized.get("allow_public_no_auth")
    ):
        warnings.append("A network listener needs authentication or an explicit public no-auth override.")
    return {"config": m._public_server_config(normalized), **snap, "warnings": warnings}


def create_server(data: dict[str, Any], *, include_candidates: bool = True) -> dict[str, Any]:
    load_servers_config, save_servers_config = _config_api()
    normalized = normalize_config(data)
    port = str(normalized["port"])
    config = load_servers_config()
    if port in config:
        raise ConflictError(f"A server on port {port} already exists")
    config[port] = {"pid": None, "process_create_time": None, "protocol": normalized["protocol"], "config": normalized}
    save_servers_config(config)
    return get_server(port, include_candidates=include_candidates) or {"port": int(port)}


def update_server(port: str | int, changes: dict[str, Any], *, include_candidates: bool = True) -> dict[str, Any] | None:
    from proxy_server.lifecycle import snapshot, terminate

    load_servers_config, save_servers_config = _config_api()
    port_key = _port(port)
    config = load_servers_config()
    profile = config.get(port_key)
    if not profile:
        return None
    existing = profile.get("config", {})
    payload = dict(changes)
    payload["port"] = int(port_key)
    normalized = normalize_config(payload, existing=existing)
    status = snapshot(_root_dir(), port_key)
    was_running = bool(status.get("running"))
    if was_running:
        result = terminate(_root_dir(), port_key)
        if not result.get("stopped"):
            raise ConflictError("Server did not stop cleanly; profile was not changed")
    config = load_servers_config()
    config[port_key] = {
        "pid": None,
        "process_create_time": None,
        "protocol": normalized["protocol"],
        "config": normalized,
    }
    save_servers_config(config)
    _server_module()._remove_runtime_profile(port_key)
    item = get_server(port_key, include_candidates=include_candidates)
    if item is not None:
        item["was_running"] = was_running
    return item


def start_server(port: str | int, *, overrides: dict[str, Any] | None = None, allow_create: bool = False, include_candidates: bool = True) -> dict[str, Any] | None:
    from proxy_server.lifecycle import atomic_write_json, profile_path, release, reserve_start, terminate, wait_until_claimed
    load_servers_config, save_servers_config = _config_api()
    port_key = _port(port)
    config = load_servers_config()
    profile = config.get(port_key)
    if profile is None and not allow_create:
        return None
    saved = dict((profile or {}).get("config", {}) or {})
    if overrides is None:
        source = saved
    else:
        payload = dict(overrides); payload["port"] = int(port_key)
        source = saved if saved and not payload.get("config") and set(payload) <= {"port"} else payload
    if not source and profile is None:
        source = {"port": int(port_key)}
    normalized = normalize_config(source, existing=saved or None); normalized["port"] = int(port_key)
    root = _root_dir(); server_path=os.path.join(root,"proxy_server","app.py"); log_file=os.path.join(root,f"server_{port_key}.log"); runtime_profile=profile_path(root,port_key)
    reserved=False
    try:
        try: token=reserve_start(root,port_key)
        except RuntimeError as exc: raise ConflictError(str(exc)) from exc
        reserved=True; atomic_write_json(runtime_profile,normalized,mode=0o600)
        cmd=[sys.executable,"-u",server_path,"--server-id",port_key,"--claim-token",token,"--config-file",str(runtime_profile)]
        with open(log_file,"ab",buffering=0) as handle:
            proc=subprocess.Popen(cmd,cwd=root,stdout=handle,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,close_fds=True)
        claimed=wait_until_claimed(root,port_key,proc.pid,timeout=3.0)
        if claimed is None or proc.poll() is not None:
            with contextlib.suppress(Exception): terminate(root,port_key,grace_seconds=1)
            _server_module()._remove_runtime_profile(port_key)
            raise RuntimeError(f"Server exited during startup. Check server_{port_key}.log")
        config=load_servers_config(); config[port_key]={"pid":proc.pid,"process_create_time":claimed.get("process_create_time"),"protocol":normalized["protocol"],"config":normalized}; save_servers_config(config)
        item=get_server(port_key,include_candidates=include_candidates) or {"port":int(port_key),"pid":proc.pid}; item["started"]=True; return item
    except Exception:
        if reserved:
            release(root,port_key); _server_module()._remove_runtime_profile(port_key)
        raise

def stop_server(port: str | int) -> dict[str, Any] | None:
    from proxy_server.lifecycle import terminate

    load_servers_config, save_servers_config = _config_api()
    port_key = _port(port)
    config = load_servers_config()
    if port_key not in config:
        return None
    result = terminate(_root_dir(), port_key)
    if not result.get("stopped"):
        raise ConflictError("Server did not stop cleanly")
    config = load_servers_config()
    if port_key in config:
        config[port_key]["pid"] = None
        config[port_key]["process_create_time"] = None
        save_servers_config(config)
    _server_module()._remove_runtime_profile(port_key)
    return {"port": int(port_key), **result}


def restart_server(port: str | int) -> dict[str, Any] | None:
    from proxy_server.lifecycle import snapshot

    port_key = _port(port)
    item = get_server(port_key, include_candidates=False)
    if item is None:
        return None
    if snapshot(_root_dir(), port_key).get("running"):
        stop_server(port_key)
    return start_server(port_key)


def delete_server(port: str | int) -> dict[str, Any] | None:
    from proxy_server.lifecycle import release, snapshot

    load_servers_config, save_servers_config = _config_api()
    port_key = _port(port)
    config = load_servers_config()
    if port_key not in config:
        return None
    if snapshot(_root_dir(), port_key).get("running"):
        raise ConflictError("Server is running. Stop it first.")
    del config[port_key]
    save_servers_config(config)
    release(_root_dir(), port_key)
    _server_module()._remove_runtime_profile(port_key)
    return {"port": int(port_key), "deleted": True}


def log_path(port: str | int) -> Path:
    port_key = _port(port)
    return Path(_root_dir()) / f"server_{port_key}.log"


def read_logs(port: str | int, *, lines: int = 100) -> dict[str, Any] | None:
    if get_server(port, include_candidates=False) is None:
        return None
    count = max(1, min(int(lines), 5000))
    path = log_path(port)
    if not path.exists():
        return {"port": int(_port(port)), "path": str(path), "lines": []}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        payload = handle.readlines()[-count:]
    return {"port": int(_port(port)), "path": str(path), "lines": [line.rstrip("\n") for line in payload]}


def _proxy_uri(config: dict[str, Any]) -> str:
    protocol = str(config.get("protocol") or "http").lower()
    bind = str(config.get("bind") or "127.0.0.1")
    if bind in {"0.0.0.0", "::"}:
        bind = "127.0.0.1" if bind == "0.0.0.0" else "::1"
    host = f"[{bind}]" if ":" in bind and not bind.startswith("[") else bind
    username = config.get("username")
    password = config.get("password")
    auth = ""
    if username:
        auth = quote(str(username), safe="")
        if password:
            auth += ":" + quote(str(password), safe="")
        auth += "@"
    scheme = {"socks5": "socks5h", "socks4": "socks4a"}.get(protocol, protocol)
    return f"{scheme}://{auth}{host}:{int(config.get('port'))}"


def test_server(port: str | int, *, url: str = "https://example.com", timeout: float = 10.0, connect_only: bool = False) -> dict[str, Any] | None:
    import requests

    load_servers_config, _ = _config_api()
    port_key = _port(port)
    profile = load_servers_config().get(port_key)
    if not profile:
        return None
    config = normalize_config(profile.get("config", {}), existing=profile.get("config", {}))
    bind = str(config.get("bind") or "127.0.0.1")
    connect_host = "127.0.0.1" if bind == "0.0.0.0" else ("::1" if bind == "::" else bind)
    try:
        with socket.create_connection((connect_host, int(port_key)), timeout=min(float(timeout), 5.0)):
            pass
    except OSError as exc:
        return {"ok": False, "stage": "connect", "port": int(port_key), "error": str(exc)}
    if connect_only:
        return {"ok": True, "stage": "connect", "port": int(port_key), "endpoint": f"{connect_host}:{port_key}"}
    proxy = _proxy_uri(config)
    try:
        response = requests.get(url, proxies={"http": proxy, "https": proxy}, timeout=float(timeout), allow_redirects=True)
        return {
            "ok": 200 <= response.status_code < 500,
            "stage": "proxy_request",
            "port": int(port_key),
            "url": url,
            "status_code": response.status_code,
            "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 1),
        }
    except requests.RequestException as exc:
        return {"ok": False, "stage": "proxy_request", "port": int(port_key), "url": url, "error": str(exc)}
