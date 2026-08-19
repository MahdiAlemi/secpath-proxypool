from __future__ import annotations

import argparse
import email
import re
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a SecProxy wheel contract")
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    wheel = args.wheel
    if not wheel.is_file():
        raise SystemExit(f"wheel not found: {wheel}")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

        required_files = {
            "secproxy_cli/app.py",
            "secproxy_core/proxy_service.py",
            "secproxy_core/server_service.py",
            "secproxy_core/monitor_service.py",
        }
        missing = sorted(required_files - names)
        if missing:
            raise SystemExit("wheel is missing: " + ", ".join(missing))

        forbidden_suffixes = (
            "/.env",
            "/proxies.db",
            "/.servers.json",
            "/.monitors.json",
        )
        forbidden = [
            name
            for name in names
            if name.endswith(forbidden_suffixes)
            or name in {".env", "proxies.db", ".servers.json", ".monitors.json"}
        ]
        if forbidden:
            raise SystemExit("wheel contains local runtime state: " + ", ".join(forbidden))

        entry_name = next(
            (name for name in names if name.endswith(".dist-info/entry_points.txt")),
            None,
        )
        metadata_name = next(
            (name for name in names if name.endswith(".dist-info/METADATA")),
            None,
        )
        if entry_name is None or metadata_name is None:
            raise SystemExit("wheel metadata is incomplete")

        entry_points = archive.read(entry_name).decode("utf-8", errors="replace")
        if "secproxy = secproxy_cli.app:main" not in entry_points:
            raise SystemExit("secproxy console entry point is missing")

        metadata = email.message_from_bytes(archive.read(metadata_name))
        requires = metadata.get_all("Requires-Dist") or []
        normalized = {
            re.split(r"[\s\[;(<>=!~]", item, maxsplit=1)[0].strip().lower()
            for item in requires
        }
        missing_deps = {"typer", "rich"} - normalized
        if missing_deps:
            raise SystemExit(
                "wheel dependency metadata missing: " + ", ".join(sorted(missing_deps))
            )

    print(f"SecProxy wheel verified: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
