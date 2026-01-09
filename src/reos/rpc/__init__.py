"""RPC module for Talking Rock.

Decomposed JSON-RPC 2.0 server with domain-specific handlers.
"""

from __future__ import annotations

from reos.rpc.types import (
    JSON,
    RpcError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    RATE_LIMIT_ERROR,
    AUTH_ERROR,
    NOT_FOUND_ERROR,
    SAFETY_ERROR,
    jsonrpc_error,
    jsonrpc_result,
    readline,
    write,
)

from reos.rpc.router import (
    register,
    dispatch,
    get_handler,
    list_methods,
    register_handlers,
)

__all__ = [
    # Types
    "JSON",
    "RpcError",
    # Error codes
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "VALIDATION_ERROR",
    "RATE_LIMIT_ERROR",
    "AUTH_ERROR",
    "NOT_FOUND_ERROR",
    "SAFETY_ERROR",
    # Utilities
    "jsonrpc_error",
    "jsonrpc_result",
    "readline",
    "write",
    # Router
    "register",
    "dispatch",
    "get_handler",
    "list_methods",
    "register_handlers",
]
