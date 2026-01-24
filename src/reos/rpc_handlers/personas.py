"""Persona management RPC handlers.

These handlers manage agent personas - custom configurations
for the AI assistant's personality, system prompts, and parameters.
"""

from __future__ import annotations

from typing import Any

from reos.db import Database

from . import RpcError


# =============================================================================
# Persona Handlers
# =============================================================================


def handle_personas_list(db: Database) -> dict[str, Any]:
    """List all personas and the active persona ID."""
    return {
        "personas": db.iter_agent_personas(),
        "active_persona_id": db.get_active_persona_id(),
    }


def handle_persona_get(db: Database, *, persona_id: str) -> dict[str, Any]:
    """Get a specific persona by ID."""
    persona = db.get_agent_persona(persona_id=persona_id)
    return {"persona": persona}


def handle_persona_upsert(db: Database, *, persona: dict[str, Any]) -> dict[str, Any]:
    """Create or update a persona."""
    required = {
        "id",
        "name",
        "system_prompt",
        "default_context",
        "temperature",
        "top_p",
        "tool_call_limit",
    }
    missing = sorted(required - set(persona.keys()))
    if missing:
        raise RpcError(code=-32602, message=f"persona missing fields: {', '.join(missing)}")

    db.upsert_agent_persona(
        persona_id=str(persona["id"]),
        name=str(persona["name"]),
        system_prompt=str(persona["system_prompt"]),
        default_context=str(persona["default_context"]),
        temperature=float(persona["temperature"]),
        top_p=float(persona["top_p"]),
        tool_call_limit=int(persona["tool_call_limit"]),
    )
    return {"ok": True}


def handle_persona_set_active(db: Database, *, persona_id: str | None) -> dict[str, Any]:
    """Set the active persona (or clear it with None)."""
    if persona_id is not None and not isinstance(persona_id, str):
        raise RpcError(code=-32602, message="persona_id must be a string or null")
    db.set_active_persona_id(persona_id=persona_id)
    return {"ok": True}
