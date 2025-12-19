"""Run ReOS MCP server.

Usage:
  /path/to/python -m reos.mcp

This runs a stdio JSON-RPC server that exposes ReOS tools to an MCP client.
"""

from __future__ import annotations

from .mcp_server import run_stdio_server


def main() -> None:
    run_stdio_server()


if __name__ == "__main__":
    main()
