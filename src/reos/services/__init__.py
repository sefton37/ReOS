"""Services Layer - Unified business logic for RPC interfaces.

This module provides shared services for the Tauri RPC (ui_rpc_server.py) interface.

Architecture:
    services/           <- This package: shared business logic
        chat_service    <- Chat, streaming, model management
        play_service    <- The Play file management
        context_service <- Context management
        knowledge_service <- Knowledge base, archives
        archive_service <- LLM-driven conversation archival

Design Principles:
    - Services are stateless (accept db/dependencies via constructor)
    - All business logic lives here
    - RPC handlers translate between service interface and I/O format
"""

from .chat_service import ChatService
from .play_service import PlayService
from .context_service import ContextService
from .knowledge_service import KnowledgeService

__all__ = [
    "ChatService",
    "PlayService",
    "ContextService",
    "KnowledgeService",
]
