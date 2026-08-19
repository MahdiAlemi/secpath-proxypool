#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[secproxy] compile"
python3 -m compileall -q secproxy_cli secproxy_core

echo "[secproxy] critical lint"
if command -v ruff >/dev/null 2>&1; then
  ruff check --select E9,F63,F7,F82 secproxy_cli secproxy_core tests/test_secproxy*.py
else
  echo "warning: ruff not found; skipping lint" >&2
fi

echo "[secproxy] tests"
python3 -m pytest -q tests/test_secproxy*.py

echo "[secproxy] CLI smoke"
secproxy --version
secproxy --help >/dev/null
secproxy proxy --help >/dev/null
secproxy monitor --help >/dev/null
secproxy server --help >/dev/null

echo "[secproxy] wheel build"
TMPDIR_PATH="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_PATH"' EXIT
python3 -m pip wheel . --no-deps -w "$TMPDIR_PATH" >/dev/null
WHEEL="$(find "$TMPDIR_PATH" -maxdepth 1 -type f -name '*.whl' -print -quit)"
if [[ -z "$WHEEL" ]]; then
  echo "error: wheel build did not produce a wheel" >&2
  exit 1
fi
python3 scripts/verify_secproxy_wheel.py "$WHEEL"

echo "SecProxy CLI release checks passed."
