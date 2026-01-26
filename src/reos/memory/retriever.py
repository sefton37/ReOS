"""Memory retriever for CAIRN context building.

Implements three-stage retrieval:
1. Semantic search: Find blocks similar to the query
2. Graph expansion: Traverse relationships from semantic matches
3. Rank and merge: Combine results with scoring

This provides relevant memory context for CAIRN's reasoning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .embeddings import EmbeddingService, get_embedding_service, content_hash
from .graph_store import MemoryGraphStore, GraphEdge
from .relationships import (
    RelationshipType,
    LOGICAL_RELATIONSHIPS,
    SEMANTIC_RELATIONSHIPS,
)

logger = logging.getLogger(__name__)


@dataclass
class MemoryMatch:
    """A single memory match from retrieval."""

    block_id: str
    block_type: str
    content: str
    score: float  # Combined relevance score
    source: str  # "semantic", "graph", or "both"
    relationship_chain: list[str] = field(default_factory=list)

    # Block metadata
    act_id: str = ""
    page_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "block_id": self.block_id,
            "block_type": self.block_type,
            "content": self.content,
            "score": self.score,
            "source": self.source,
            "relationship_chain": self.relationship_chain,
            "act_id": self.act_id,
            "page_id": self.page_id,
            "created_at": self.created_at,
        }


@dataclass
class MemoryContext:
    """Result of memory retrieval for CAIRN."""

    query: str
    matches: list[MemoryMatch] = field(default_factory=list)
    total_semantic_matches: int = 0
    total_graph_expansions: int = 0

    def to_markdown(self) -> str:
        """Format memory context as markdown for CAIRN prompt."""
        if not self.matches:
            return ""

        lines = ["## Relevant Memory\n"]
        lines.append(
            f"*Retrieved {len(self.matches)} relevant memories "
            f"({self.total_semantic_matches} semantic, "
            f"{self.total_graph_expansions} via relationships)*\n"
        )

        for i, match in enumerate(self.matches, 1):
            score_bar = "█" * int(match.score * 5)
            lines.append(f"### Memory #{i} [{score_bar}] ({match.source})")
            lines.append(f"*Type: {match.block_type} | Score: {match.score:.2f}*\n")
            lines.append(match.content)
            if match.relationship_chain:
                lines.append(f"\n*Connected via: {' → '.join(match.relationship_chain)}*")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "matches": [m.to_dict() for m in self.matches],
            "total_semantic_matches": self.total_semantic_matches,
            "total_graph_expansions": self.total_graph_expansions,
        }


class MemoryRetriever:
    """Retrieves relevant memory for CAIRN context.

    Three-stage retrieval pipeline:
    1. Semantic Search: Embed query, find similar blocks
    2. Graph Expansion: Traverse relationships from matches
    3. Rank & Merge: Combine and score results
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        graph_store: MemoryGraphStore | None = None,
    ) -> None:
        """Initialize the retriever.

        Args:
            embedding_service: Optional embedding service (uses global if None).
            graph_store: Optional graph store (creates new if None).
        """
        self._embedding_service = embedding_service or get_embedding_service()
        self._graph_store = graph_store or MemoryGraphStore()

    def retrieve(
        self,
        query: str,
        *,
        act_id: str | None = None,
        max_results: int = 20,
        semantic_threshold: float = 0.5,
        graph_depth: int = 1,
        include_graph_expansion: bool = True,
    ) -> MemoryContext:
        """Retrieve relevant memory for a query.

        Args:
            query: The user's query/message.
            act_id: Optional act ID to scope the search.
            max_results: Maximum number of results to return.
            semantic_threshold: Minimum similarity for semantic matches.
            graph_depth: How deep to traverse relationships.
            include_graph_expansion: Whether to expand via graph.

        Returns:
            MemoryContext with relevant matches.
        """
        context = MemoryContext(query=query)

        # Stage 1: Semantic Search
        semantic_matches = self._semantic_search(
            query,
            act_id=act_id,
            threshold=semantic_threshold,
            top_k=max_results,
        )
        context.total_semantic_matches = len(semantic_matches)

        # Build initial result set
        results: dict[str, MemoryMatch] = {}
        for block_id, similarity in semantic_matches:
            block_data = self._get_block_data(block_id)
            if block_data:
                results[block_id] = MemoryMatch(
                    block_id=block_id,
                    block_type=block_data.get("type", "unknown"),
                    content=block_data.get("content", ""),
                    score=similarity,
                    source="semantic",
                    act_id=block_data.get("act_id", ""),
                    page_id=block_data.get("page_id"),
                    created_at=block_data.get("created_at", ""),
                )

        # Stage 2: Graph Expansion
        if include_graph_expansion and semantic_matches:
            graph_expanded = self._expand_via_graph(
                [m[0] for m in semantic_matches],
                depth=graph_depth,
                existing_ids=set(results.keys()),
            )
            context.total_graph_expansions = len(graph_expanded)

            for block_id, (base_score, chain) in graph_expanded.items():
                if block_id in results:
                    # Boost existing match
                    results[block_id].score = min(1.0, results[block_id].score + 0.1)
                    results[block_id].source = "both"
                    if chain:
                        results[block_id].relationship_chain = chain
                else:
                    # Add new graph-discovered match
                    block_data = self._get_block_data(block_id)
                    if block_data:
                        results[block_id] = MemoryMatch(
                            block_id=block_id,
                            block_type=block_data.get("type", "unknown"),
                            content=block_data.get("content", ""),
                            score=base_score,
                            source="graph",
                            relationship_chain=chain,
                            act_id=block_data.get("act_id", ""),
                            page_id=block_data.get("page_id"),
                            created_at=block_data.get("created_at", ""),
                        )

        # Stage 3: Rank and Merge
        context.matches = self._rank_and_merge(
            list(results.values()),
            max_results=max_results,
        )

        return context

    def _semantic_search(
        self,
        query: str,
        *,
        act_id: str | None = None,
        threshold: float = 0.5,
        top_k: int = 20,
    ) -> list[tuple[str, float]]:
        """Stage 1: Find semantically similar blocks.

        Args:
            query: Query text.
            act_id: Optional act filter.
            threshold: Minimum similarity.
            top_k: Maximum results.

        Returns:
            List of (block_id, similarity) tuples.
        """
        if not self._embedding_service.is_available:
            logger.warning("Embedding service not available, skipping semantic search")
            return []

        # Embed the query
        query_embedding = self._embedding_service.embed(query)
        if query_embedding is None:
            return []

        # Get all candidate embeddings
        candidates = self._graph_store.get_all_embeddings(act_id=act_id)
        if not candidates:
            return []

        # Find similar
        return self._embedding_service.find_similar(
            query_embedding,
            candidates,
            threshold=threshold,
            top_k=top_k,
        )

    def _expand_via_graph(
        self,
        seed_ids: list[str],
        *,
        depth: int = 1,
        existing_ids: set[str] | None = None,
    ) -> dict[str, tuple[float, list[str]]]:
        """Stage 2: Expand from seed blocks via relationships.

        Args:
            seed_ids: Block IDs to expand from.
            depth: Maximum traversal depth.
            existing_ids: IDs already in results (to avoid duplicates).

        Returns:
            Dict of block_id -> (score, relationship_chain).
        """
        existing = existing_ids or set()
        expanded: dict[str, tuple[float, list[str]]] = {}

        # Prioritize logical and semantic relationships
        priority_types = list(LOGICAL_RELATIONSHIPS | SEMANTIC_RELATIONSHIPS)

        for seed_id in seed_ids:
            traversal = self._graph_store.traverse(
                seed_id,
                max_depth=depth,
                rel_types=priority_types,
                max_nodes=50,
            )

            # Score based on depth (closer = higher score)
            for d, block_ids in traversal.blocks_by_depth.items():
                if d == 0:
                    continue  # Skip the seed itself

                depth_score = 0.6 - (d * 0.2)  # 0.4 at depth 1, 0.2 at depth 2
                depth_score = max(0.1, depth_score)

                for block_id in block_ids:
                    if block_id in existing:
                        continue

                    # Build relationship chain
                    chain = self._build_relationship_chain(
                        seed_id, block_id, traversal.edges
                    )

                    if block_id in expanded:
                        # Take higher score
                        if depth_score > expanded[block_id][0]:
                            expanded[block_id] = (depth_score, chain)
                    else:
                        expanded[block_id] = (depth_score, chain)

        return expanded

    def _build_relationship_chain(
        self,
        start_id: str,
        end_id: str,
        edges: list[GraphEdge],
    ) -> list[str]:
        """Build a human-readable relationship chain.

        Args:
            start_id: Starting block ID.
            end_id: Ending block ID.
            edges: All edges in the traversal.

        Returns:
            List of relationship type names forming the path.
        """
        # Simple approach: find edges connecting start to end
        path = self._graph_store.find_path(start_id, end_id, max_depth=3)
        if path:
            return [e.relationship_type.value for e in path]
        return []

    def _rank_and_merge(
        self,
        matches: list[MemoryMatch],
        *,
        max_results: int = 20,
    ) -> list[MemoryMatch]:
        """Stage 3: Rank and merge results.

        Scoring considers:
        - Base similarity/graph score
        - Source bonus (both > semantic > graph)
        - Type weights (reasoning_chain > knowledge_fact > paragraph)

        Args:
            matches: All candidate matches.
            max_results: Maximum to return.

        Returns:
            Sorted list of top matches.
        """
        # Type importance weights
        type_weights = {
            "reasoning_chain": 1.2,
            "knowledge_fact": 1.1,
            "feedback": 1.1,
            "heading_1": 1.0,
            "heading_2": 1.0,
            "paragraph": 0.9,
            "to_do": 0.8,
            "bulleted_list": 0.8,
        }

        # Source bonus
        source_bonus = {
            "both": 0.15,
            "semantic": 0.0,
            "graph": -0.05,  # Slight penalty for graph-only
        }

        for match in matches:
            # Apply type weight
            type_weight = type_weights.get(match.block_type, 0.9)
            match.score *= type_weight

            # Apply source bonus
            match.score += source_bonus.get(match.source, 0)

            # Clamp to [0, 1]
            match.score = max(0.0, min(1.0, match.score))

        # Sort by score descending
        matches.sort(key=lambda m: m.score, reverse=True)

        return matches[:max_results]

    def _get_block_data(self, block_id: str) -> dict[str, Any] | None:
        """Get block data including content.

        Args:
            block_id: Block ID.

        Returns:
            Dict with block data, or None if not found.
        """
        try:
            from reos.play.blocks_db import get_block

            block = get_block(block_id)
            if block is None:
                return None

            # Get text content from rich_text
            content = ""
            if block.rich_text:
                content = " ".join(rt.content for rt in block.rich_text)

            return {
                "type": block.type.value if hasattr(block.type, "value") else str(block.type),
                "content": content,
                "act_id": block.act_id,
                "page_id": block.page_id,
                "created_at": block.created_at,
            }
        except Exception as e:
            logger.debug("Failed to get block data for %s: %s", block_id, e)
            return None

    def index_block(self, block_id: str) -> bool:
        """Index a block's embedding for semantic search.

        Call this when a block is created or updated.

        Args:
            block_id: Block ID to index.

        Returns:
            True if indexed, False on error.
        """
        if not self._embedding_service.is_available:
            return False

        block_data = self._get_block_data(block_id)
        if not block_data or not block_data.get("content"):
            return False

        content = block_data["content"]
        current_hash = content_hash(content)

        # Check if already up-to-date
        if not self._graph_store.is_embedding_stale(block_id, current_hash):
            return True

        # Generate and store embedding
        embedding = self._embedding_service.embed(content)
        if embedding is None:
            return False

        return self._graph_store.store_embedding(block_id, embedding, current_hash)

    def remove_block_index(self, block_id: str) -> bool:
        """Remove a block from the index.

        Call this when a block is deleted.

        Args:
            block_id: Block ID to remove.

        Returns:
            True if removed, False if not found.
        """
        return self._graph_store.delete_embedding(block_id)
