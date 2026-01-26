"""Relationship types for the memory graph.

Defines the typed edges that connect blocks in the memory system.
These relationships enable CAIRN to understand how ideas, facts,
reasoning chains, and user interactions relate to each other.
"""

from __future__ import annotations

from enum import Enum


class RelationshipType(str, Enum):
    """Types of relationships between blocks.

    Relationships are directional: source → target.
    Example: Block A REFERENCES Block B means A cites/mentions B.
    """

    # === Logical Relationships ===
    # For reasoning chains and knowledge connections

    REFERENCES = "references"
    """Source block cites or mentions target block."""

    FOLLOWS_FROM = "follows_from"
    """Source block is a logical consequence of target block."""

    CONTRADICTS = "contradicts"
    """Source block conflicts with or negates target block."""

    SUPPORTS = "supports"
    """Source block provides evidence for target block."""

    # === Semantic Relationships ===
    # For content similarity and thematic connections

    SIMILAR_TO = "similar_to"
    """Blocks are semantically similar (auto-detected via embeddings)."""

    RELATED_TO = "related_to"
    """Generic connection between blocks (user or AI defined)."""

    ELABORATES = "elaborates"
    """Source block provides more detail about target block."""

    # === Causal Relationships ===
    # For event chains and cause-effect

    CAUSED_BY = "caused_by"
    """Source event/state was caused by target event/action."""

    CAUSES = "causes"
    """Source event/action causes target event/state."""

    # === Feedback/Learning Relationships ===
    # For RLHF and preference learning

    CORRECTS = "corrects"
    """Source block is a correction/improvement of target block."""

    SUPERSEDES = "supersedes"
    """Source block replaces target block (newer version)."""

    DERIVED_FROM = "derived_from"
    """Source block was created from/based on target block."""

    # === Temporal Relationships ===
    # For conversation and event ordering

    PRECEDED_BY = "preceded_by"
    """Source block came after target block in time."""

    RESPONDS_TO = "responds_to"
    """Source block is a response to target block."""


class RelationshipSource(str, Enum):
    """Source/origin of a relationship.

    Tracks how a relationship was created for provenance and
    confidence weighting.
    """

    USER = "user"
    """Explicitly created by the user."""

    CAIRN = "cairn"
    """Created by CAIRN during reasoning."""

    INFERRED = "inferred"
    """Automatically inferred from content analysis."""

    FEEDBACK = "feedback"
    """Created from RLHF feedback (thumbs up/down)."""

    EMBEDDING = "embedding"
    """Created from embedding similarity detection."""


# Relationship categories for filtering
LOGICAL_RELATIONSHIPS = {
    RelationshipType.REFERENCES,
    RelationshipType.FOLLOWS_FROM,
    RelationshipType.CONTRADICTS,
    RelationshipType.SUPPORTS,
}

SEMANTIC_RELATIONSHIPS = {
    RelationshipType.SIMILAR_TO,
    RelationshipType.RELATED_TO,
    RelationshipType.ELABORATES,
}

CAUSAL_RELATIONSHIPS = {
    RelationshipType.CAUSED_BY,
    RelationshipType.CAUSES,
}

FEEDBACK_RELATIONSHIPS = {
    RelationshipType.CORRECTS,
    RelationshipType.SUPERSEDES,
    RelationshipType.DERIVED_FROM,
}

TEMPORAL_RELATIONSHIPS = {
    RelationshipType.PRECEDED_BY,
    RelationshipType.RESPONDS_TO,
}


def get_inverse_relationship(rel_type: RelationshipType) -> RelationshipType | None:
    """Get the inverse relationship type if one exists.

    Some relationships have natural inverses (e.g., CAUSES ↔ CAUSED_BY).
    Returns None if no inverse exists.
    """
    inverses = {
        RelationshipType.CAUSES: RelationshipType.CAUSED_BY,
        RelationshipType.CAUSED_BY: RelationshipType.CAUSES,
        RelationshipType.FOLLOWS_FROM: RelationshipType.SUPPORTS,
        RelationshipType.SUPPORTS: RelationshipType.FOLLOWS_FROM,
        RelationshipType.RESPONDS_TO: RelationshipType.PRECEDED_BY,
        RelationshipType.PRECEDED_BY: RelationshipType.RESPONDS_TO,
    }
    return inverses.get(rel_type)
