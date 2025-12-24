# ReOS Tauri (TypeScript UI + Python kernel)

This is a minimal Tauri shell that spawns the ReOS kernel as a child process and talks to it over stdio JSON-RPC.

## Dev prerequisites
- Node + npm
- Rust toolchain
- Python 3.12+ with `reos` importable (e.g. `pip install -e .` from repo root)

## Run (dev)
From repo root:
- `pip install -e .`

From this folder:
- `npm install`
- `npm run tauri:dev`

## Kernel
The UI spawns:
- `python -m reos.ui_rpc_server`

You can override which Python is used:
- `export REOS_PYTHON=/home/kellogg/dev/ReOS/.venv/bin/python`

If `REOS_PYTHON` is not set, the app will try to auto-detect `.venv/bin/python` by walking upward from the Tauri executable.

RPC methods currently used:
- `chat/respond` with `{ "text": "..." }`

Intentionally *not* implemented yet:
- Event polling / triggers (we’ll add once the UI shell is stable)

