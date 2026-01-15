"""Context Sources - Single source of truth for context source definitions.

This module defines the available context sources that can be toggled
on/off in the context overlay. All modules should import from here
instead of defining their own lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextSourceDef:
    """Definition of a context source."""

    name: str  # Internal identifier (e.g., "play_context")
    display_name: str  # Human-readable name (e.g., "The Play")
    description: str  # Tooltip/help text
    can_disable: bool  # Whether user can toggle this off


# Single source of truth for context sources
# Order matters for display in the UI
CONTEXT_SOURCES: tuple[ContextSourceDef, ...] = (
    ContextSourceDef(
        name="system_prompt",
        display_name="System Prompt",
        description="Core instructions defining behavior and personality",
        can_disable=False,  # Cannot disable - essential for operation
    ),
    ContextSourceDef(
        name="play_context",
        display_name="The Play",
        description="Your story, goals, acts, scenes, and beats",
        can_disable=True,
    ),
    ContextSourceDef(
        name="learned_kb",
        display_name="Learned Knowledge",
        description="Facts and preferences learned from past conversations",
        can_disable=True,
    ),
    ContextSourceDef(
        name="system_state",
        display_name="System State",
        description="Current machine state - CPU, memory, services, containers",
        can_disable=True,
    ),
    ContextSourceDef(
        name="codebase",
        display_name="Architecture",
        description="System architecture for self-knowledge",
        can_disable=True,
    ),
    ContextSourceDef(
        name="messages",
        display_name="Conversation",
        description="Current chat messages",
        can_disable=False,  # Cannot disable - would break chat
    ),
)

# Convenience sets for validation
VALID_SOURCE_NAMES: frozenset[str] = frozenset(s.name for s in CONTEXT_SOURCES)
DISABLEABLE_SOURCES: frozenset[str] = frozenset(s.name for s in CONTEXT_SOURCES if s.can_disable)


def get_source_by_name(name: str) -> ContextSourceDef | None:
    """Get a source definition by name."""
    for source in CONTEXT_SOURCES:
        if source.name == name:
            return source
    return None


def to_dict_list() -> list[dict[str, Any]]:
    """Convert sources to list of dicts for JSON serialization."""
    return [
        {
            "name": s.name,
            "display_name": s.display_name,
            "description": s.description,
            "can_disable": s.can_disable,
        }
        for s in CONTEXT_SOURCES
    ]
