"""RPC handler modules for ui_rpc_server.

This package contains handler functions organized by domain:
- play: Play (Acts/Scenes) operations
- providers: LLM provider management (Ollama)
- chat: Chat and conversation handlers
- planning: Code planning and execution handlers
"""

from __future__ import annotations

from typing import Any


class RpcError(RuntimeError):
    """JSON-RPC error that can be returned to the client."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
