"""RPC types and utilities.

Core types, error handling, and JSON-RPC helpers used across all handlers.
"""

from __future__ import annotations

import sys
from typing import Any

# Type alias for JSON-serializable dict
JSON = dict[str, Any]


class RpcError(Exception):
    """JSON-RPC error with code, message, and optional data."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> JSON:
        """Convert to JSON-RPC error object."""
        result: JSON = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Application-specific error codes
VALIDATION_ERROR = -32000
RATE_LIMIT_ERROR = -32001
AUTH_ERROR = -32002
NOT_FOUND_ERROR = -32003
SAFETY_ERROR = -32004


def jsonrpc_error(request_id: str | int | None, error: RpcError) -> JSON:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error.to_dict(),
    }


def jsonrpc_result(request_id: str | int | None, result: Any) -> JSON:
    """Build a JSON-RPC 2.0 success response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def readline() -> str | None:
    """Read a line from stdin, returning None on EOF."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return line.strip()
    except Exception:
        return None


def write(response: JSON) -> None:
    """Write a JSON-RPC response to stdout."""
    import json

    try:
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Client disconnected - exit cleanly
        sys.exit(0)
