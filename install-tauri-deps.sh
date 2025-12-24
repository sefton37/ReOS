#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This helper currently supports Ubuntu/Debian (apt-get)." >&2
  echo "Install Tauri system deps manually for your distro, then rerun: $ROOT_DIR/run-tauri.sh" >&2
  exit 1
fi

# Choose webkitgtk dev package name (Ubuntu 24.04 typically has 4.1)
WEBKIT_DEV_PKG="libwebkit2gtk-4.1-dev"
if ! apt-cache show "$WEBKIT_DEV_PKG" >/dev/null 2>&1; then
  WEBKIT_DEV_PKG="libwebkit2gtk-4.0-dev"
fi

# AppIndicator dev package name varies; try ayatana first on newer Ubuntu.
APPINDICATOR_DEV_PKG="libayatana-appindicator3-dev"
if ! apt-cache show "$APPINDICATOR_DEV_PKG" >/dev/null 2>&1; then
  APPINDICATOR_DEV_PKG="libappindicator3-dev"
fi

echo "Installing Tauri Linux system dependencies (requires sudo)…"

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  lsof \
  pkg-config \
  libglib2.0-dev \
  libgtk-3-dev \
  "$WEBKIT_DEV_PKG" \
  "$APPINDICATOR_DEV_PKG" \
  librsvg2-dev

echo
echo "Done. Now run: $ROOT_DIR/run-tauri.sh"
