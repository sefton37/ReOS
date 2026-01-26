"""Memory RPC handlers - Graph-based memory operations.

These handlers manage the hybrid vector-graph memory system for
relationship CRUD, semantic search, and graph traversal.
"""

from __future__ import annotations

import logging
from typing import Any

from reos.db import Database
from reos.memory import (
    RelationshipType,
    RelationshipSource,
    MemoryGraphStore,
    MemoryRetriever,
)
from reos.memory.extractor import RelationshipExtractor

from . import RpcError

logger = logging.getLogger(__name__)

# Singleton instances (created on first use)
_graph_store: MemoryGraphStore | None = None
_retriever: MemoryRetriever | None = None
_extractor: RelationshipExtractor | None = None


def _get_graph_store() -> MemoryGraphStore:
    """Get or create the graph store singleton."""
    global _graph_store
    if _graph_store is None:
        _graph_store = MemoryGraphStore()
    return _graph_store


def _get_retriever() -> MemoryRetriever:
    """Get or create the retriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = MemoryRetriever(graph_store=_get_graph_store())
    return _retriever


def _get_extractor() -> RelationshipExtractor:
    """Get or create the extractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = RelationshipExtractor(graph_store=_get_graph_store())
    return _extractor


# =============================================================================
# Relationship CRUD
# =============================================================================


def handle_memory_relationships_create(
    _db: Database,
    *,
    source_id: str,
    target_id: str,
    rel_type: str,
    confidence: float = 1.0,
    weight: float = 1.0,
    source: str = "user",
) -> dict[str, Any]:
    """Create a relationship between two blocks.

    Args:
        source_id: Source block ID.
        target_id: Target block ID.
        rel_type: Relationship type (e.g., "references", "follows_from").
        confidence: Confidence score (0.0-1.0).
        weight: Weight for graph algorithms.
        source: Origin of relationship ("user", "cairn", "inferred").

    Returns:
        Created relationship data or error.
    """
    # Validate relationship type
    try:
        relationship_type = RelationshipType(rel_type)
    except ValueError:
        valid_types = [t.value for t in RelationshipType]
        raise RpcError(
            code=-32602,
            message=f"Invalid relationship type: {rel_type}. Valid: {valid_types}",
        )

    # Validate source
    try:
        rel_source = RelationshipSource(source)
    except ValueError:
        valid_sources = [s.value for s in RelationshipSource]
        raise RpcError(
            code=-32602,
            message=f"Invalid source: {source}. Valid: {valid_sources}",
        )

    store = _get_graph_store()
    rel_id = store.create_relationship(
        source_id,
        target_id,
        relationship_type,
        confidence=confidence,
        weight=weight,
        source=rel_source,
    )

    if rel_id is None:
        raise RpcError(
            code=-32000,
            message="Failed to create relationship. May already exist or invalid blocks.",
        )

    edge = store.get_relationship(rel_id)
    return {"relationship": edge.to_dict() if edge else {"id": rel_id}}


def handle_memory_relationships_list(
    _db: Database,
    *,
    block_id: str,
    direction: str = "both",
    rel_types: list[str] | None = None,
) -> dict[str, Any]:
    """List relationships for a block.

    Args:
        block_id: Block ID to query.
        direction: "outgoing", "incoming", or "both".
        rel_types: Optional filter by relationship types.

    Returns:
        List of relationships.
    """
    # Validate direction
    if direction not in ("outgoing", "incoming", "both"):
        raise RpcError(
            code=-32602,
            message=f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'.",
        )

    # Parse relationship types
    parsed_types: list[RelationshipType] | None = None
    if rel_types:
        parsed_types = []
        for rt in rel_types:
            try:
                parsed_types.append(RelationshipType(rt))
            except ValueError:
                raise RpcError(
                    code=-32602,
                    message=f"Invalid relationship type: {rt}",
                )

    store = _get_graph_store()
    edges = store.get_relationships(
        block_id,
        direction=direction,
        rel_types=parsed_types,
    )

    return {"relationships": [e.to_dict() for e in edges]}


def handle_memory_relationships_update(
    _db: Database,
    *,
    relationship_id: str,
    confidence: float | None = None,
    weight: float | None = None,
) -> dict[str, Any]:
    """Update a relationship's confidence or weight.

    Args:
        relationship_id: Relationship ID.
        confidence: New confidence value (0.0-1.0).
        weight: New weight value.

    Returns:
        Updated relationship data.
    """
    store = _get_graph_store()

    if not store.update_relationship(
        relationship_id,
        confidence=confidence,
        weight=weight,
    ):
        raise RpcError(
            code=-32602,
            message=f"Relationship not found: {relationship_id}",
        )

    edge = store.get_relationship(relationship_id)
    return {"relationship": edge.to_dict() if edge else {"id": relationship_id}}


def handle_memory_relationships_delete(
    _db: Database,
    *,
    relationship_id: str,
) -> dict[str, Any]:
    """Delete a relationship.

    Args:
        relationship_id: Relationship ID.

    Returns:
        Success status.
    """
    store = _get_graph_store()

    if not store.delete_relationship(relationship_id):
        raise RpcError(
            code=-32602,
            message=f"Relationship not found: {relationship_id}",
        )

    return {"deleted": True, "relationship_id": relationship_id}


# =============================================================================
# Semantic Search & Retrieval
# =============================================================================


def handle_memory_search(
    _db: Database,
    *,
    query: str,
    act_id: str | None = None,
    max_results: int = 20,
    include_graph: bool = True,
) -> dict[str, Any]:
    """Search memory using semantic similarity and graph relationships.

    Args:
        query: Search query text.
        act_id: Optional act to scope the search.
        max_results: Maximum number of results.
        include_graph: Whether to expand via graph relationships.

    Returns:
        Search results with relevance scores.
    """
    if not query.strip():
        raise RpcError(code=-32602, message="query is required")

    retriever = _get_retriever()
    context = retriever.retrieve(
        query,
        act_id=act_id,
        max_results=max_results,
        include_graph_expansion=include_graph,
    )

    return {
        "query": context.query,
        "matches": [m.to_dict() for m in context.matches],
        "stats": {
            "total_semantic": context.total_semantic_matches,
            "total_graph": context.total_graph_expansions,
            "returned": len(context.matches),
        },
    }


def handle_memory_related(
    _db: Database,
    *,
    block_id: str,
    depth: int = 2,
    rel_types: list[str] | None = None,
    direction: str = "both",
    max_nodes: int = 50,
) -> dict[str, Any]:
    """Find blocks related to a given block via graph traversal.

    Args:
        block_id: Starting block ID.
        depth: Maximum traversal depth.
        rel_types: Optional filter by relationship types.
        direction: "outgoing", "incoming", or "both".
        max_nodes: Maximum nodes to return.

    Returns:
        Traversal result with related blocks and edges.
    """
    # Parse relationship types
    parsed_types: list[RelationshipType] | None = None
    if rel_types:
        parsed_types = []
        for rt in rel_types:
            try:
                parsed_types.append(RelationshipType(rt))
            except ValueError:
                raise RpcError(
                    code=-32602,
                    message=f"Invalid relationship type: {rt}",
                )

    store = _get_graph_store()
    result = store.traverse(
        block_id,
        max_depth=depth,
        rel_types=parsed_types,
        direction=direction,
        max_nodes=max_nodes,
    )

    return result.to_dict()


def handle_memory_path(
    _db: Database,
    *,
    start_id: str,
    end_id: str,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Find a path between two blocks.

    Args:
        start_id: Starting block ID.
        end_id: Target block ID.
        max_depth: Maximum path length.

    Returns:
        Path as list of edges, or null if no path found.
    """
    store = _get_graph_store()
    path = store.find_path(start_id, end_id, max_depth=max_depth)

    if path is None:
        return {"path": None, "found": False}

    return {
        "path": [e.to_dict() for e in path],
        "found": True,
        "length": len(path),
    }


# =============================================================================
# Embedding Management
# =============================================================================


def handle_memory_index_block(
    _db: Database,
    *,
    block_id: str,
) -> dict[str, Any]:
    """Index a block for semantic search.

    Generates and stores the embedding for the block's content.

    Args:
        block_id: Block ID to index.

    Returns:
        Success status.
    """
    retriever = _get_retriever()

    if not retriever.index_block(block_id):
        raise RpcError(
            code=-32000,
            message=f"Failed to index block {block_id}. Check if embedding service is available.",
        )

    return {"indexed": True, "block_id": block_id}


def handle_memory_index_batch(
    _db: Database,
    *,
    block_ids: list[str],
) -> dict[str, Any]:
    """Index multiple blocks for semantic search.

    Args:
        block_ids: List of block IDs to index.

    Returns:
        Summary of indexing results.
    """
    retriever = _get_retriever()
    success = 0
    failed = 0

    for block_id in block_ids:
        if retriever.index_block(block_id):
            success += 1
        else:
            failed += 1

    return {
        "indexed": success,
        "failed": failed,
        "total": len(block_ids),
    }


def handle_memory_remove_index(
    _db: Database,
    *,
    block_id: str,
) -> dict[str, Any]:
    """Remove a block from the semantic index.

    Args:
        block_id: Block ID to remove.

    Returns:
        Success status.
    """
    retriever = _get_retriever()
    removed = retriever.remove_block_index(block_id)

    return {"removed": removed, "block_id": block_id}


# =============================================================================
# Relationship Extraction
# =============================================================================


def handle_memory_extract_relationships(
    _db: Database,
    *,
    block_id: str,
    content: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Extract and create relationships from block content.

    Analyzes content for block references, logical connectors,
    and semantic similarity to automatically build the memory graph.

    Args:
        block_id: The block to extract relationships from.
        content: The text content to analyze.
        act_id: Optional act to scope similarity search.

    Returns:
        List of created relationships.
    """
    extractor = _get_extractor()
    created = extractor.extract_from_chain(
        block_id,
        content,
        act_id=act_id,
    )

    return {
        "block_id": block_id,
        "relationships_created": created,
        "count": len(created),
    }


def handle_memory_learn_from_feedback(
    _db: Database,
    *,
    chain_block_id: str,
    rating: int,
    corrected_block_id: str | None = None,
) -> dict[str, Any]:
    """Learn from RLHF feedback.

    Positive feedback strengthens relationships.
    Negative feedback with correction creates CORRECTS relationship.

    Args:
        chain_block_id: The reasoning chain that received feedback.
        rating: 1-5 rating.
        corrected_block_id: If negative, ID of corrected version.

    Returns:
        Summary of relationship changes.
    """
    if rating < 1 or rating > 5:
        raise RpcError(
            code=-32602,
            message="rating must be between 1 and 5",
        )

    extractor = _get_extractor()
    changes = extractor.extract_from_feedback(
        chain_block_id,
        rating,
        corrected_block_id=corrected_block_id,
    )

    return {
        "chain_block_id": chain_block_id,
        "rating": rating,
        "changes": changes,
        "count": len(changes),
    }


def handle_memory_auto_link(
    _db: Database,
    *,
    act_id: str | None = None,
    threshold: float = 0.8,
    max_links: int = 3,
) -> dict[str, Any]:
    """Automatically create SIMILAR_TO relationships for similar blocks.

    Args:
        act_id: Optional act to scope.
        threshold: Similarity threshold (0.0-1.0).
        max_links: Maximum links per block.

    Returns:
        Number of relationships created.
    """
    extractor = _get_extractor()
    count = extractor.auto_link_similar_blocks(
        act_id=act_id,
        threshold=threshold,
        max_links_per_block=max_links,
    )

    return {"relationships_created": count}


# =============================================================================
# Statistics
# =============================================================================


def handle_memory_stats(
    _db: Database,
    *,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Get memory system statistics.

    Args:
        act_id: Optional act to scope.

    Returns:
        Statistics about relationships and embeddings.
    """
    from reos.play_db import _get_connection, init_db

    init_db()
    conn = _get_connection()

    # Count relationships
    if act_id:
        cursor = conn.execute(
            """
            SELECT relationship_type, COUNT(*) as count
            FROM block_relationships br
            JOIN blocks b ON br.source_block_id = b.id
            WHERE b.act_id = ?
            GROUP BY relationship_type
            """,
            (act_id,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT relationship_type, COUNT(*) as count
            FROM block_relationships
            GROUP BY relationship_type
            """
        )

    rel_counts = {row["relationship_type"]: row["count"] for row in cursor}
    total_relationships = sum(rel_counts.values())

    # Count embeddings
    if act_id:
        cursor = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM block_embeddings be
            JOIN blocks b ON be.block_id = b.id
            WHERE b.act_id = ?
            """,
            (act_id,),
        )
    else:
        cursor = conn.execute("SELECT COUNT(*) as count FROM block_embeddings")

    total_embeddings = cursor.fetchone()["count"]

    # Count total blocks
    if act_id:
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM blocks WHERE act_id = ?",
            (act_id,),
        )
    else:
        cursor = conn.execute("SELECT COUNT(*) as count FROM blocks")

    total_blocks = cursor.fetchone()["count"]

    return {
        "total_relationships": total_relationships,
        "relationships_by_type": rel_counts,
        "total_embeddings": total_embeddings,
        "total_blocks": total_blocks,
        "embedding_coverage": (
            total_embeddings / total_blocks if total_blocks > 0 else 0
        ),
    }
