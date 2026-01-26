"""Relationship extractor for automatic graph building.

Extracts relationships from:
- Reasoning chains (logical connectors, references)
- RLHF feedback (positive strengthens, negative creates corrections)
- Block content (semantic similarity)

This enables the memory graph to grow organically as Talking Rock
learns from interactions.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .embeddings import get_embedding_service, content_hash
from .graph_store import MemoryGraphStore
from .relationships import (
    RelationshipType,
    RelationshipSource,
    get_inverse_relationship,
)

logger = logging.getLogger(__name__)

# Patterns for detecting logical relationships in text
LOGICAL_PATTERNS = {
    RelationshipType.FOLLOWS_FROM: [
        r"\btherefore\b",
        r"\bthus\b",
        r"\bhence\b",
        r"\bconsequently\b",
        r"\bas a result\b",
        r"\bso\b(?=\s+(?:we|I|it|this))",
        r"\bwhich means\b",
        r"\bthis implies\b",
    ],
    RelationshipType.CAUSED_BY: [
        r"\bbecause\b",
        r"\bsince\b",
        r"\bdue to\b",
        r"\bas\b(?=\s+(?:a result|mentioned))",
        r"\bowing to\b",
        r"\bon account of\b",
    ],
    RelationshipType.SUPPORTS: [
        r"\bfor example\b",
        r"\bfor instance\b",
        r"\bsuch as\b",
        r"\beveridence\b",
        r"\bproof\b",
        r"\bdemonstrates\b",
        r"\bshows that\b",
    ],
    RelationshipType.CONTRADICTS: [
        r"\bhowever\b",
        r"\bbut\b",
        r"\balthough\b",
        r"\bdespite\b",
        r"\bcontrary to\b",
        r"\bon the other hand\b",
        r"\bnevertheless\b",
        r"\bconflicts with\b",
    ],
    RelationshipType.ELABORATES: [
        r"\bspecifically\b",
        r"\bmore specifically\b",
        r"\bin detail\b",
        r"\bto elaborate\b",
        r"\bnamely\b",
        r"\bthat is\b",
        r"\bi\.e\.\b",
    ],
}

# Compile patterns
COMPILED_PATTERNS = {
    rel_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for rel_type, patterns in LOGICAL_PATTERNS.items()
}

# Block reference pattern (e.g., "block-abc123" or "[block:xyz789]")
BLOCK_REF_PATTERN = re.compile(r"\b(?:block[-_]?)?([a-f0-9]{8,12})\b", re.IGNORECASE)


class RelationshipExtractor:
    """Extracts relationships from content and feedback.

    Can be used in two modes:
    1. Automatic: Called on block creation/update to find relationships
    2. Learning: Called on feedback to strengthen/weaken relationships
    """

    def __init__(
        self,
        graph_store: MemoryGraphStore | None = None,
        similarity_threshold: float = 0.7,
    ) -> None:
        """Initialize the extractor.

        Args:
            graph_store: Optional graph store (creates new if None).
            similarity_threshold: Threshold for SIMILAR_TO relationships.
        """
        self._graph_store = graph_store or MemoryGraphStore()
        self._embedding_service = get_embedding_service()
        self._similarity_threshold = similarity_threshold

    def extract_from_chain(
        self,
        chain_block_id: str,
        chain_content: str,
        *,
        act_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract relationships from a reasoning chain.

        Analyzes the chain content for:
        - Explicit block references
        - Logical connectors indicating relationships
        - Semantic similarity to existing blocks

        Args:
            chain_block_id: The reasoning chain block ID.
            chain_content: The text content of the chain.
            act_id: Optional act to scope similarity search.

        Returns:
            List of created relationships as dicts.
        """
        created: list[dict[str, Any]] = []

        # 1. Find explicit block references
        refs = self._extract_block_references(chain_content)
        for ref_id in refs:
            rel_id = self._graph_store.create_relationship(
                chain_block_id,
                ref_id,
                RelationshipType.REFERENCES,
                source=RelationshipSource.CAIRN,
            )
            if rel_id:
                created.append({
                    "id": rel_id,
                    "type": RelationshipType.REFERENCES.value,
                    "target": ref_id,
                })

        # 2. Detect logical patterns (for connecting to previous reasoning)
        detected_types = self._detect_logical_patterns(chain_content)
        # These would need a "previous" block to connect to - handled elsewhere

        # 3. Find semantically similar blocks
        if self._embedding_service.is_available:
            similar = self._find_similar_blocks(
                chain_content,
                exclude_id=chain_block_id,
                act_id=act_id,
            )
            for similar_id, similarity in similar[:3]:  # Top 3
                rel_id = self._graph_store.create_relationship(
                    chain_block_id,
                    similar_id,
                    RelationshipType.SIMILAR_TO,
                    confidence=similarity,
                    source=RelationshipSource.EMBEDDING,
                )
                if rel_id:
                    created.append({
                        "id": rel_id,
                        "type": RelationshipType.SIMILAR_TO.value,
                        "target": similar_id,
                        "similarity": similarity,
                    })

        logger.debug(
            "Extracted %d relationships from chain %s",
            len(created),
            chain_block_id,
        )
        return created

    def extract_from_conversation(
        self,
        message_block_id: str,
        previous_block_id: str | None,
        message_content: str,
    ) -> list[dict[str, Any]]:
        """Extract relationships for a conversation message.

        Creates temporal relationships (RESPONDS_TO) and detects
        logical relationships based on content.

        Args:
            message_block_id: The new message block ID.
            previous_block_id: The previous message in conversation (if any).
            message_content: The message text.

        Returns:
            List of created relationships.
        """
        created: list[dict[str, Any]] = []

        # Connect to previous message
        if previous_block_id:
            rel_id = self._graph_store.create_relationship(
                message_block_id,
                previous_block_id,
                RelationshipType.RESPONDS_TO,
                source=RelationshipSource.CAIRN,
            )
            if rel_id:
                created.append({
                    "id": rel_id,
                    "type": RelationshipType.RESPONDS_TO.value,
                    "target": previous_block_id,
                })

        # Detect logical patterns and extract references
        refs = self._extract_block_references(message_content)
        for ref_id in refs:
            rel_id = self._graph_store.create_relationship(
                message_block_id,
                ref_id,
                RelationshipType.REFERENCES,
                source=RelationshipSource.CAIRN,
            )
            if rel_id:
                created.append({
                    "id": rel_id,
                    "type": RelationshipType.REFERENCES.value,
                    "target": ref_id,
                })

        return created

    def extract_from_feedback(
        self,
        chain_block_id: str,
        rating: int,
        *,
        corrected_block_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Learn from RLHF feedback.

        Positive feedback (rating > 3): Strengthen relationships used.
        Negative feedback (rating <= 2): Create CORRECTS relationship if
        a corrected version is provided.

        Args:
            chain_block_id: The reasoning chain that received feedback.
            rating: 1-5 rating (1=bad, 5=great).
            corrected_block_id: If negative, ID of the corrected version.

        Returns:
            List of created/modified relationships.
        """
        created: list[dict[str, Any]] = []

        if rating >= 4:
            # Positive feedback - strengthen outgoing relationships
            edges = self._graph_store.get_relationships(
                chain_block_id,
                direction="outgoing",
            )
            for edge in edges:
                # Boost confidence
                new_confidence = min(1.0, edge.confidence + 0.1)
                if self._graph_store.update_relationship(
                    edge.id,
                    confidence=new_confidence,
                ):
                    created.append({
                        "id": edge.id,
                        "action": "strengthened",
                        "new_confidence": new_confidence,
                    })

        elif rating <= 2 and corrected_block_id:
            # Negative feedback with correction - create CORRECTS relationship
            rel_id = self._graph_store.create_relationship(
                corrected_block_id,
                chain_block_id,
                RelationshipType.CORRECTS,
                source=RelationshipSource.FEEDBACK,
            )
            if rel_id:
                created.append({
                    "id": rel_id,
                    "type": RelationshipType.CORRECTS.value,
                    "source": corrected_block_id,
                    "target": chain_block_id,
                })

            # Weaken the original chain's relationships
            edges = self._graph_store.get_relationships(
                chain_block_id,
                direction="outgoing",
            )
            for edge in edges:
                new_confidence = max(0.1, edge.confidence - 0.2)
                if self._graph_store.update_relationship(
                    edge.id,
                    confidence=new_confidence,
                ):
                    created.append({
                        "id": edge.id,
                        "action": "weakened",
                        "new_confidence": new_confidence,
                    })

        return created

    def connect_sequential_blocks(
        self,
        block_ids: list[str],
        relationship_type: RelationshipType = RelationshipType.PRECEDED_BY,
    ) -> list[str]:
        """Connect a sequence of blocks with temporal relationships.

        Useful for connecting reasoning chain steps or conversation messages.

        Args:
            block_ids: List of block IDs in order.
            relationship_type: Type of relationship (default PRECEDED_BY).

        Returns:
            List of created relationship IDs.
        """
        created_ids: list[str] = []

        for i in range(1, len(block_ids)):
            rel_id = self._graph_store.create_relationship(
                block_ids[i],
                block_ids[i - 1],
                relationship_type,
                source=RelationshipSource.CAIRN,
            )
            if rel_id:
                created_ids.append(rel_id)

        return created_ids

    def _extract_block_references(self, content: str) -> list[str]:
        """Extract block ID references from content.

        Args:
            content: Text content to search.

        Returns:
            List of referenced block IDs.
        """
        matches = BLOCK_REF_PATTERN.findall(content)
        # Verify these are actual block IDs
        valid_ids: list[str] = []
        for match in matches:
            # Check if block exists
            try:
                from reos.play.blocks_db import get_block

                if get_block(match) is not None:
                    valid_ids.append(match)
            except Exception:
                pass
        return valid_ids

    def _detect_logical_patterns(
        self,
        content: str,
    ) -> list[RelationshipType]:
        """Detect logical relationship patterns in content.

        Args:
            content: Text content to analyze.

        Returns:
            List of detected relationship types.
        """
        detected: list[RelationshipType] = []

        for rel_type, patterns in COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(content):
                    if rel_type not in detected:
                        detected.append(rel_type)
                    break

        return detected

    def _find_similar_blocks(
        self,
        content: str,
        *,
        exclude_id: str | None = None,
        act_id: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Find blocks semantically similar to content.

        Args:
            content: Content to find similar blocks for.
            exclude_id: Block ID to exclude from results.
            act_id: Optional act filter.
            top_k: Maximum results.

        Returns:
            List of (block_id, similarity) tuples.
        """
        if not self._embedding_service.is_available:
            return []

        # Embed the content
        embedding = self._embedding_service.embed(content)
        if embedding is None:
            return []

        # Get candidates
        candidates = self._graph_store.get_all_embeddings(act_id=act_id)
        if exclude_id:
            candidates = [(bid, emb) for bid, emb in candidates if bid != exclude_id]

        # Find similar
        return self._embedding_service.find_similar(
            embedding,
            candidates,
            threshold=self._similarity_threshold,
            top_k=top_k,
        )

    def auto_link_similar_blocks(
        self,
        act_id: str | None = None,
        threshold: float = 0.8,
        max_links_per_block: int = 3,
    ) -> int:
        """Automatically create SIMILAR_TO relationships for similar blocks.

        Run this periodically to build semantic connections.

        Args:
            act_id: Optional act filter.
            threshold: Similarity threshold (higher = stricter).
            max_links_per_block: Max similar links per block.

        Returns:
            Number of relationships created.
        """
        if not self._embedding_service.is_available:
            return 0

        all_embeddings = self._graph_store.get_all_embeddings(act_id=act_id)
        created_count = 0

        for i, (block_id, embedding) in enumerate(all_embeddings):
            # Find similar among remaining blocks
            candidates = all_embeddings[i + 1:]  # Only look forward to avoid duplicates
            similar = self._embedding_service.find_similar(
                embedding,
                candidates,
                threshold=threshold,
                top_k=max_links_per_block,
            )

            for similar_id, similarity in similar:
                rel_id = self._graph_store.create_relationship(
                    block_id,
                    similar_id,
                    RelationshipType.SIMILAR_TO,
                    confidence=similarity,
                    source=RelationshipSource.EMBEDDING,
                )
                if rel_id:
                    created_count += 1

        logger.info("Auto-linked %d similar block pairs", created_count)
        return created_count
