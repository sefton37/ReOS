"""ReOS MCP server (stdio bridge).

This is a lightweight MCP-compatible JSON-RPC server over stdio.

Goal (MVP): allow a local MCP client (no VS Code extension) to interrogate a
project via:
- project_charter (ground truth)
- git metadata (and optional diff by explicit opt-in)
- bounded repo file operations (read/grep/list)

Security / attention principles:
- Local-only.
- Metadata-first by default.
- File operations are sandboxed to the *active project's linked repo*.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools, render_tool_result
from .repo_sandbox import RepoSandboxError, safe_repo_path


_JSON = dict[str, Any]


class McpError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _jsonrpc_error(*, req_id: Any, code: int, message: str, data: Any | None = None) -> _JSON:
    err: _JSON = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _jsonrpc_result(*, req_id: Any, result: Any) -> _JSON:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _readline() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line


def _write(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _repo_root_from_active_project(db: Database) -> Path:
    repo_path = db.get_active_project_repo_path()
    if not repo_path:
        raise McpError(
            code=-32000,
            message="No active project repo is configured.",
            data={"hint": "Call reos_project_active_set or set active_project_id in app_state."},
        )
    return Path(repo_path).resolve()


def _safe_repo_path(repo_root: Path, rel_path: str) -> Path:
    try:
        return safe_repo_path(repo_root, rel_path)
    except RepoSandboxError as exc:
        raise McpError(code=-32001, message="Path escapes repo root", data={"path": rel_path}) from exc


def _tool_text(content: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": content}]}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]


def _tools() -> list[Tool]:
    return [Tool(name=t.name, description=t.description, input_schema=t.input_schema) for t in list_tools()]


def _tool_list_response() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in _tools()
        ]
    }


def _handle_tool_call(db: Database, *, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    try:
        result = call_tool(db, name=name, arguments=arguments)
        return _tool_text(render_tool_result(result))
    except ToolError as exc:
        # Map to JSON-RPC-ish error codes for MCP.
        code = -32602 if exc.code in {"invalid_args"} else -32000
        raise McpError(code=code, message=exc.message, data=exc.data) from exc


def run_stdio_server() -> None:
    """Run an MCP JSON-RPC server over stdio."""

    db = get_db()
    db.migrate()

    while True:
        line = _readline()
        if line is None:
            return

        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(req, dict):
            continue

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params")

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "reos-mcp", "version": "0.1.0"},
                }
                _write(_jsonrpc_result(req_id=req_id, result=result))
                continue

            # Notifications can omit id; ignore.
            if req_id is None:
                continue

            if method == "tools/list":
                _write(_jsonrpc_result(req_id=req_id, result=_tool_list_response()))
                continue

            if method == "tools/call":
                if not isinstance(params, dict):
                    raise McpError(code=-32602, message="params must be an object")
                name = params.get("name")
                arguments = params.get("arguments")
                if not isinstance(name, str) or not name:
                    raise McpError(code=-32602, message="name is required")
                if arguments is not None and not isinstance(arguments, dict):
                    raise McpError(code=-32602, message="arguments must be an object")

                result = _handle_tool_call(db, name=name, arguments=arguments)
                _write(_jsonrpc_result(req_id=req_id, result=result))
                continue

            raise McpError(code=-32601, message=f"Method not found: {method}")

        except McpError as exc:
            _write(_jsonrpc_error(req_id=req_id, code=exc.code, message=exc.message, data=exc.data))
        except Exception as exc:  # noqa: BLE001
            _write(
                _jsonrpc_error(
                    req_id=req_id,
                    code=-32099,
                    message="Internal error",
                    data={"error": str(exc)},
                )
            )


__all__ = ["run_stdio_server", "_safe_repo_path"]
