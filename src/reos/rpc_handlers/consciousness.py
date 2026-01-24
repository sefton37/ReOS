"""Consciousness streaming and async CAIRN chat RPC handlers.

These handlers provide real-time visibility into CAIRN's thinking
process through event streaming.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from reos.db import Database

from .chat import handle_chat_respond


# =============================================================================
# Module-level state for async chat tracking
# =============================================================================

@dataclass
class CairnChatContext:
    """Context for an async CAIRN chat request."""
    chat_id: str
    text: str
    conversation_id: str | None
    extended_thinking: bool
    is_complete: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None
    thread: threading.Thread | None = None


_cairn_chat_lock = threading.Lock()
_active_cairn_chats: dict[str, CairnChatContext] = {}


# =============================================================================
# Consciousness Streaming Handlers
# =============================================================================


def handle_consciousness_start(_db: Database) -> dict[str, Any]:
    """Start a consciousness streaming session.

    Clears previous events and activates event collection.
    Called when user sends a message.
    """
    from reos.cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    observer.start_session()
    return {"status": "started"}


def handle_consciousness_poll(_db: Database, *, since_index: int = 0) -> dict[str, Any]:
    """Poll for new consciousness events.

    Args:
        since_index: Return events starting from this index

    Returns:
        Dict with events list and next_index for pagination
    """
    from reos.cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    events = observer.poll(since_index)

    # Debug logging to file
    with open("/tmp/consciousness_debug.log", "a") as f:
        f.write(f"[POLL] since_index={since_index}, active={observer.is_active()}, events={len(events)}\n")

    return {
        "events": [
            {
                "type": e.event_type.name,
                "timestamp": e.timestamp.isoformat(),
                "title": e.title,
                "content": e.content,
                "metadata": e.metadata,
            }
            for e in events
        ],
        "next_index": since_index + len(events),
    }


def handle_consciousness_snapshot(_db: Database) -> dict[str, Any]:
    """Get all events from the current session.

    Returns all events without pagination.
    """
    from reos.cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    events = observer.get_all()

    return {
        "events": [
            {
                "type": e.event_type.name,
                "timestamp": e.timestamp.isoformat(),
                "title": e.title,
                "content": e.content,
                "metadata": e.metadata,
            }
            for e in events
        ],
    }


# =============================================================================
# Async CAIRN Chat Handlers
# =============================================================================


def handle_cairn_chat_async(
    db: Database,
    *,
    text: str,
    conversation_id: str | None = None,
    extended_thinking: bool = False,
) -> dict[str, Any]:
    """Start CAIRN chat processing in background thread.

    This allows the RPC server to handle consciousness/poll requests
    while chat is processing, enabling real-time event streaming.

    Returns immediately with a chat_id that can be used to poll for status.
    """
    from reos.cairn.consciousness_stream import ConsciousnessObserver

    chat_id = uuid.uuid4().hex[:12]

    # Start consciousness session
    observer = ConsciousnessObserver.get_instance()
    observer.start_session()
    # Debug logging to file
    with open("/tmp/consciousness_debug.log", "a") as f:
        f.write(f"[ASYNC CHAT] Started consciousness session for chat_id={chat_id}\n")

    context = CairnChatContext(
        chat_id=chat_id,
        text=text,
        conversation_id=conversation_id,
        extended_thinking=extended_thinking,
    )

    def run_chat() -> None:
        """Run the chat in background thread."""
        try:
            result = handle_chat_respond(
                db,
                text=text,
                conversation_id=conversation_id,
                agent_type="cairn",  # Use CAIRN's IntentEngine for consciousness events
                extended_thinking=extended_thinking,
            )
            context.result = result
            context.is_complete = True
        except Exception as e:
            context.error = str(e)
            context.is_complete = True
        finally:
            # End consciousness session
            observer.end_session()

    # Start background thread
    thread = threading.Thread(target=run_chat, daemon=True)
    context.thread = thread

    # Track the chat
    with _cairn_chat_lock:
        _active_cairn_chats[chat_id] = context

    thread.start()

    return {
        "chat_id": chat_id,
        "status": "started",
    }


def handle_cairn_chat_status(
    _db: Database,
    *,
    chat_id: str,
) -> dict[str, Any]:
    """Get the status of an async CAIRN chat request.

    Returns the result when complete, or status "processing" if still running.
    """
    with _cairn_chat_lock:
        context = _active_cairn_chats.get(chat_id)

    if not context:
        return {"error": f"Chat {chat_id} not found", "status": "not_found"}

    if not context.is_complete:
        return {"chat_id": chat_id, "status": "processing"}

    if context.error:
        return {"chat_id": chat_id, "status": "error", "error": context.error}

    # Clean up completed chat
    with _cairn_chat_lock:
        _active_cairn_chats.pop(chat_id, None)

    return {
        "chat_id": chat_id,
        "status": "complete",
        "result": context.result,
    }


# =============================================================================
# Handoff Handler
# =============================================================================


def handle_handoff_validate_all(_db: Database) -> dict[str, Any]:
    """Validate all agent manifests (15-tool cap check)."""
    from reos.handoff import validate_all_manifests

    return validate_all_manifests()
