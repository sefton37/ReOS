"""Context meter and knowledge management RPC handlers.

These handlers manage context window usage statistics
and context source toggles.
"""

from __future__ import annotations

import logging
from typing import Any

from reos.context_meter import calculate_context_stats
from reos.context_sources import VALID_SOURCE_NAMES, DISABLEABLE_SOURCES
from reos.db import Database
from reos.knowledge_store import KnowledgeStore
from reos.play_fs import list_acts as play_list_acts
from reos.play_fs import read_me_markdown as play_read_me_markdown

from . import RpcError


logger = logging.getLogger(__name__)


# =============================================================================
# Context Handlers
# =============================================================================


def handle_context_stats(
    db: Database,
    *,
    conversation_id: str | None = None,
    context_limit: int | None = None,
    include_breakdown: bool = False,
) -> dict[str, Any]:
    """Get context usage statistics for a conversation."""
    from agents import ChatAgent
    from reos.system_state import SteadyStateCollector

    messages: list[dict[str, Any]] = []
    if conversation_id:
        raw_messages = db.get_messages(conversation_id=conversation_id, limit=100)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in raw_messages
        ]

    # Get active act for learned KB
    acts, active_act_id = play_list_acts()
    learned_kb = ""
    store = KnowledgeStore()
    if active_act_id:
        learned_kb = store.get_learned_markdown(active_act_id)

    # Get system state context
    system_state = ""
    try:
        collector = SteadyStateCollector()
        state = collector.refresh_if_stale(max_age_seconds=3600)
        system_state = state.to_context_string()
    except Exception as e:
        logger.debug("Failed to get system state for context stats: %s", e)

    # Get system prompt from persona
    system_prompt = ""
    try:
        persona_id = db.get_active_persona_id()
        if persona_id:
            persona = db.get_agent_persona(persona_id=persona_id)
            if persona:
                system_prompt = persona.get("system_prompt", "")
        if not system_prompt:
            # Default system prompt estimate
            system_prompt = "x" * 8000  # ~2000 tokens
    except Exception as e:
        logger.debug("Failed to get persona for context stats: %s", e)
        system_prompt = "x" * 8000

    # Get play context
    play_context = ""
    try:
        play_context = play_read_me_markdown()
    except Exception as e:
        logger.debug("Failed to get play context for context stats: %s", e)

    # Get context limit from model settings if not provided
    if context_limit is None:
        num_ctx_raw = db.get_state(key="ollama_num_ctx")
        if num_ctx_raw:
            # num_ctx is stored as string, convert to int
            try:
                context_limit = int(num_ctx_raw)
            except (ValueError, TypeError):
                context_limit = 8192
        else:
            # Default to 8K if not set
            context_limit = 8192

    # Get disabled sources from settings
    disabled_sources_str = db.get_state(key="context_disabled_sources")
    disabled_sources: set[str] = set()
    if disabled_sources_str and isinstance(disabled_sources_str, str):
        disabled_sources = set(s.strip() for s in disabled_sources_str.split(",") if s.strip())

    stats = calculate_context_stats(
        messages=messages,
        system_prompt=system_prompt,
        play_context=play_context,
        learned_kb=learned_kb,
        system_state=system_state,
        context_limit=context_limit,
        include_breakdown=include_breakdown,
        disabled_sources=disabled_sources,
    )

    return stats.to_dict()


def handle_context_toggle_source(
    db: Database,
    *,
    source_name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle a context source on or off."""
    # Get current disabled sources
    disabled_sources_str = db.get_state(key="context_disabled_sources")
    disabled_sources: set[str] = set()
    if disabled_sources_str and isinstance(disabled_sources_str, str):
        disabled_sources = set(s.strip() for s in disabled_sources_str.split(",") if s.strip())

    # Validate source name (using shared constant)
    if source_name not in VALID_SOURCE_NAMES:
        raise RpcError(code=-32602, message=f"Invalid source name: {source_name}")

    # Don't allow disabling non-disableable sources (system_prompt, messages)
    if not enabled and source_name not in DISABLEABLE_SOURCES:
        raise RpcError(code=-32602, message=f"Cannot disable '{source_name}' - it is required for operation")

    # Update disabled sources
    if enabled:
        disabled_sources.discard(source_name)
    else:
        disabled_sources.add(source_name)

    # Save back to db
    db.set_state(key="context_disabled_sources", value=",".join(sorted(disabled_sources)))

    return {"ok": True, "disabled_sources": list(disabled_sources)}
