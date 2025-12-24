#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT_DIR/scripts/bootstrap.sh" >/dev/null

exec "$ROOT_DIR/.venv/bin/reos-gui"
