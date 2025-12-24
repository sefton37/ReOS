#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
TAURI_WEB_DIR="$ROOT_DIR/apps/reos-tauri"

choose_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    local ver
    ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [[ "$ver" == "3.12" ]]; then
      echo "python3"
      return 0
    fi
  fi

  echo "ERROR: Python 3.12 is required (requires-python >=3.12)." >&2
  echo "Install Python 3.12, then rerun: $0" >&2
  return 1
}

bootstrap_python() {
  local py
  py="$(choose_python)"

  if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating venv at $VENV_DIR using $py"
    (cd "$ROOT_DIR" && "$py" -m venv .venv)
  fi

  echo "Installing Python deps (editable + dev extras)"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -e ".[dev]"
}

bootstrap_typescript() {
  if [[ ! -d "$TAURI_WEB_DIR" ]]; then
    echo "ERROR: Expected Tauri web app dir at: $TAURI_WEB_DIR" >&2
    return 1
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm is required to install TypeScript dependencies for apps/reos-tauri." >&2
    echo "Install Node.js + npm, then rerun: $0" >&2
    return 1
  fi

  echo "Installing TypeScript deps in $TAURI_WEB_DIR"
  (cd "$TAURI_WEB_DIR" && npm install)
}

bootstrap_python
bootstrap_typescript

echo
echo "Bootstrap complete."
echo "Run GUI: $ROOT_DIR/scripts/run.sh"
