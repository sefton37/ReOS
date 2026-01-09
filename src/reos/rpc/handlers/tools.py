"""Tool handlers.

MCP tool listing and invocation.
"""

from __future__ import annotations

from typing import Any

from reos.db import Database
from reos.mcp_tools import ToolError, call_tool, list_tools
from reos.rpc.router import register
from reos.rpc.types import INTERNAL_ERROR, RpcError


@register("tools/list")
def handle_list() -> dict[str, Any]:
    """List available MCP tools."""
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in list_tools()
        ]
    }


@register("tools/call", needs_db=True)
def handle_call(
    db: Database,
    *,
    name: str,
    arguments: dict[str, Any] | None,
) -> Any:
    """Call an MCP tool by name."""
    try:
        return call_tool(db, name=name, arguments=arguments)
    except ToolError as exc:
        raise RpcError(INTERNAL_ERROR, str(exc)) from exc
