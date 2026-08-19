from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Any


def _check(
    name: str,
    ok: bool,
    detail: str,
    *,
    level: str = "error",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "level": level,
        "detail": detail,
    }


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _mode_detail(path: Path) -> str:
    return f"{path} mode={oct(_mode(path))}"


def _private_file_check(name: str, path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        mode = _mode(path)
        return _check(
            name,
            (mode & 0o077) == 0,
            _mode_detail(path),
        )
    except OSError as exc:
        return _check(name, False, str(exc))


def _metadata_check() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        dist = importlib.metadata.distribution("secpath-proxypool")
        entry_points = list(dist.entry_points)
        has_secproxy = any(
            ep.group == "console_scripts"
            and ep.name == "secproxy"
            and ep.value == "secproxy_cli.app:main"
            for ep in entry_points
        )
        requirements = list(dist.requires or [])
        requirement_names = {
            re.split(r"[\s\[<>=!~]", item.split(";", 1)[0].strip(), maxsplit=1)[0].lower()
            for item in requirements
        }
        runtime_metadata_ok = {"typer", "rich"}.issubset(requirement_names)
        return (
            _check(
                "cli_entrypoint",
                has_secproxy,
                "secproxy -> secproxy_cli.app:main" if has_secproxy else "console entry point missing",
            ),
            _check(
                "package_dependencies",
                runtime_metadata_ok,
                (
                    "runtime dependency metadata present"
                    if runtime_metadata_ok
                    else "wheel/editable metadata is missing typer/rich requirements"
                ),
            ),
        )
    except Exception as exc:
        failed = _check("cli_entrypoint", False, str(exc))
        return failed, _check("package_dependencies", False, str(exc))


def _server_security_check(root: Path) -> dict[str, Any]:
    path = root / ".servers.json"
    if not path.exists():
        return _check("listener_security", True, "no saved listener profiles")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("server config is not a JSON object")

        from secproxy_core.server import _is_local_bind

        unsafe = []
        explicit_public = []
        for port, record in payload.items():
            config = dict((record or {}).get("config") or {})
            bind = str(config.get("bind") or "127.0.0.1")
            if _is_local_bind(bind):
                continue
            has_auth = bool(config.get("username"))
            if has_auth:
                continue
            if config.get("allow_public_no_auth"):
                explicit_public.append(str(port))
            else:
                unsafe.append(str(port))

        if unsafe:
            return _check(
                "listener_security",
                False,
                "public unauthenticated listener profiles without override: " + ", ".join(unsafe),
            )
        if explicit_public:
            return _check(
                "listener_security",
                False,
                "explicit public no-auth override on ports: " + ", ".join(explicit_public),
                level="warning",
            )
        return _check("listener_security", True, "saved listeners are loopback or authenticated")
    except Exception as exc:
        return _check("listener_security", False, str(exc))


def _architecture_check(root: Path) -> dict[str, Any]:
    paths = [
        root / "secproxy_cli" / "services" / "monitor_service.py",
        root / "secproxy_cli" / "services" / "server_service.py",
    ]
    try:
        bad = []
        for path in paths:
            if not path.is_file():
                bad.append(f"missing:{path.name}")
                continue
            if "dashboard.routes" in path.read_text(encoding="utf-8"):
                bad.append(path.name)
        return _check(
            "cli_core_boundary",
            not bad,
            "CLI services are detached from Flask routes" if not bad else ", ".join(bad),
        )
    except Exception as exc:
        return _check("cli_core_boundary", False, str(exc))


def run_doctor() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "python",
            sys.version_info >= (3, 11),
            platform.python_version(),
        )
    )

    try:
        import config as config_module

        root = Path(config_module.__file__).resolve().parent
        env_path = root / ".env"
        checks.append(_check("env_file", env_path.exists(), str(env_path)))
        if env_path.exists():
            private_env = _private_file_check("env_permissions", env_path)
            if private_env:
                checks.append(private_env)
    except Exception as exc:
        root = Path.cwd()
        checks.append(_check("config", False, str(exc)))

    try:
        for module in (
            "secproxy_core",
            "secproxy_core.monitor_service",
            "secproxy_core.server_service",
            "secproxy_core.proxy_service",
        ):
            importlib.import_module(module)
        checks.append(_check("cli_core_imports", True, "secproxy_core imports succeeded"))
    except Exception as exc:
        checks.append(_check("cli_core_imports", False, str(exc)))

    entrypoint_check, dependency_check = _metadata_check()
    checks.extend([entrypoint_check, dependency_check])

    try:
        from sqlalchemy import text
        from database import db

        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks.append(_check("database_connection", True, db.engine.dialect.name))
    except Exception as exc:
        checks.append(_check("database_connection", False, str(exc)))

    try:
        from sqlalchemy import inspect
        from database import db

        tables = set(inspect(db.engine).get_table_names())
        required = {
            "proxies",
            "users",
            "tokens",
            "import_sources",
            "import_runs",
            "monitor_sessions",
            "monitor_tested",
        }
        missing = sorted(required - tables)
        checks.append(
            _check(
                "database_schema",
                not missing,
                "ok" if not missing else f"missing: {', '.join(missing)}",
            )
        )
    except Exception as exc:
        checks.append(_check("database_schema", False, str(exc)))

    runtime = root / ".runtime"
    if runtime.exists():
        checks.append(
            _check(
                "runtime_directory",
                os.access(runtime, os.R_OK | os.W_OK),
                str(runtime.resolve()),
            )
        )
    else:
        checks.append(_check("runtime_directory", True, "not created yet"))

    for name, filename in (
        ("server_config_permissions", ".servers.json"),
        ("monitor_config_permissions", ".monitors.json"),
    ):
        result = _private_file_check(name, root / filename)
        if result:
            checks.append(result)

    backups = root / "backups" / "secproxy"
    if backups.exists():
        try:
            mode = _mode(backups)
            checks.append(
                _check(
                    "backup_directory_permissions",
                    (mode & 0o077) == 0,
                    _mode_detail(backups),
                )
            )
        except OSError as exc:
            checks.append(_check("backup_directory_permissions", False, str(exc)))

    checks.append(_server_security_check(root))
    checks.append(_architecture_check(root))
    return checks
