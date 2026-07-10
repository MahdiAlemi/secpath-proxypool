#!/usr/bin/env python3
"""Rotate local Flask/JWT secrets without printing them to the terminal."""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path

SECRET_KEYS = ("FLASK_SECRET_KEY", "JWT_SECRET")


def rotate_env_file(path: Path) -> tuple[str, ...]:
    path = path.resolve()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacements = {key: secrets.token_hex(32) for key in SECRET_KEYS}
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped and not stripped.startswith("#") else ""
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(line)

    if output and output[-1] != "":
        output.append("")
    for key in SECRET_KEYS:
        if key not in seen:
            output.append(f"{key}={replacements[key]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        temp_path.unlink(missing_ok=True)

    return SECRET_KEYS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Environment file to update")
    args = parser.parse_args()
    changed = rotate_env_file(Path(args.env_file))
    print(f"Rotated {', '.join(changed)} in {args.env_file}; values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
