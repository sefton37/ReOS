#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "NOTE: run.sh is deprecated; use: $ROOT_DIR/reos" >&2
exec "$ROOT_DIR/reos" --ui pyside
