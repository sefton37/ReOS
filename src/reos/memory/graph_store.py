"""Graph store for block relationships.

Provides CRUD operations and graph traversal for the memory system.
Uses the play.db SQLite database for persistent storage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .relationships import RelationshipType, RelationshipSource

logger = logging.getLogger(__name__)


@dataclass
class GraphEdge:
    """A relationship edge between two blocks."""

    id: str
    source_block_id: str
    target_block_id: str
    relationship_type: RelationshipType
    confidence: float = 1.0
    weight: float = 1.0
    source: RelationshipSource = RelationshipSource.INFERRED
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "source_block_id": self.source_block_id,
            "target_block_id": self.target_block_id,
            "relationship_type": self.relationship_type.value,
            "confidence": self.confidence,
            "weight": self.weight,
            "source": self.source.value,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> "GraphEdge":
        """Create from database row."""
        return cls(
            id=row["id"],
            source_block_id=row["source_block_id"],
            target_block_id=row["target_block_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            confidence=row["confidence"],
            weight=row["weight"],
            source=RelationshipSource(row["source"]),
            created_at=row["created_at"],
        )


@dataclass
class TraversalResult:
    """Result of a graph traversal operation."""

    start_block_id: str
    visited_blocks: set[str] = field(default_factory=set)
    edges: list[GraphEdge] = field(default_factory=list)
    blocks_by_depth: dict[int, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_block_id": self.start_block_id,
            "visited_blocks": list(self.visited_blocks),
            "edges": [e.to_dict() for e in self.edges],
            "blocks_by_depth": {k: list(v) for k, v in self.blocks_by_depth.items()},
        }


class MemoryGraphStore:
    """Graph operations for block relationships.

    Provides CRUD for relationships and graph traversal algorithms
    for expanding from seed blocks to related content.
    """

    def __init__(self) -> None:
        """Initialize the graph store."""
        pass

    def _get_connection(self):
        """Get database connection from play_db."""
        from reos.play_db import _get_connection, init_db

        init_db()
        return _get_connection()

    def _now_iso(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self) -> str:
        """Generate a new relationship ID."""
        return f"rel-{uuid4().hex[:12]}"

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        *,
        confidence: float = 1.0,
        weight: float = 1.0,
        source: RelationshipSource = RelationshipSource.INFERRED,
    ) -> str | None:
        """Create a new relationship between blocks.

        Args:
            source_id: Source block ID.
            target_id: Target block ID.
            rel_type: Type of relationship.
            confidence: Confidence score (0.0-1.0).
            weight: Weight for graph algorithms.
            source: Origin of this relationship.

        Returns:
            Relationship ID if created, None if failed (e.g., duplicate).
        """
        if source_id == target_id:
            logger.warning("Cannot create self-referential relationship")
            return None

        conn = self._get_connection()
        rel_id = self._new_id()
        now = self._now_iso()

        try:
            conn.execute(
                """
                INSERT INTO block_relationships
                (id, source_block_id, target_block_id, relationship_type,
                 confidence, weight, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel_id,
                    source_id,
                    target_id,
                    rel_type.value,
                    confidence,
                    weight,
                    source.value,
                    now,
                ),
            )
            conn.commit()
            logger.debug(
                "Created relationship %s: %s -[%s]-> %s",
                rel_id,
                source_id,
                rel_type.value,
                target_id,
            )
            return rel_id
        except Exception as e:
            conn.rollback()
            # May be a unique constraint violation (duplicate relationship) or other error
            if "UNIQUE constraint" in str(e):
                logger.debug(
                    "Relationship already exists: %s -[%s]-> %s",
                    source_id,
                    rel_type.value,
                    target_id,
                )
            else:
                logger.warning(
                    "Failed to create relationship %s -[%s]-> %s: %s",
                    source_id,
                    rel_type.value,
                    target_id,
                    e,
                )
            return None

    def get_relationship(self, rel_id: str) -> GraphEdge | None:
        """Get a relationship by ID.

        Args:
            rel_id: Relationship ID.

        Returns:
            GraphEdge if found, None otherwise.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id, source_block_id, target_block_id, relationship_type,
                   confidence, weight, source, created_at
            FROM block_relationships
            WHERE id = ?
            """,
            (rel_id,),
        )
        row = cursor.fetchone()
        if row:
            return GraphEdge.from_row(row)
        return None

    def get_relationships(
        self,
        block_id: str,
        *,
        direction: str = "both",
        rel_types: list[RelationshipType] | None = None,
    ) -> list[GraphEdge]:
        """Get relationships for a block.

        Args:
            block_id: Block ID to query.
            direction: "outgoing", "incoming", or "both".
            rel_types: Filter by relationship types (None = all).

        Returns:
            List of matching edges.
        """
        conn = self._get_connection()

        # Build query based on direction
        if direction == "outgoing":
            base_query = "SELECT * FROM block_relationships WHERE source_block_id = ?"
            params: list[Any] = [block_id]
        elif direction == "incoming":
            base_query = "SELECT * FROM block_relationships WHERE target_block_id = ?"
            params = [block_id]
        else:  # both
            base_query = """
                SELECT * FROM block_relationships
                WHERE (source_block_id = ? OR target_block_id = ?)
            """
            params = [block_id, block_id]

        # Add type filter
        if rel_types:
            type_placeholders = ",".join("?" * len(rel_types))
            base_query += f" AND relationship_type IN ({type_placeholders})"
            params.extend(rt.value for rt in rel_types)

        cursor = conn.execute(base_query, params)
        return [GraphEdge.from_row(row) for row in cursor.fetchall()]

    def update_relationship(
        self,
        rel_id: str,
        *,
        confidence: float | None = None,
        weight: float | None = None,
    ) -> bool:
        """Update a relationship's confidence or weight.

        Args:
            rel_id: Relationship ID.
            confidence: New confidence value.
            weight: New weight value.

        Returns:
            True if updated, False if not found.
        """
        conn = self._get_connection()

        # SAFETY: updates list MUST only contain hardcoded "column = ?" strings.
        # Never add user-controlled column names here.
        updates = []
        params: list[Any] = []

        if confidence is not None:
            updates.append("confidence = ?")
            params.append(confidence)

        if weight is not None:
            updates.append("weight = ?")
            params.append(weight)

        if not updates:
            return False

        _ALLOWED_COLUMNS = {"confidence", "weight"}
        assert all(u.split(" = ?")[0] in _ALLOWED_COLUMNS for u in updates), (
            f"SQL injection guard: unexpected column in updates: {updates}"
        )

        params.append(rel_id)

        try:
            cursor = conn.execute(
                f"UPDATE block_relationships SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.warning(
                "Failed to update relationship %s (confidence=%s, weight=%s): %s",
                rel_id,
                confidence,
                weight,
                e,
            )
            return False

    def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship.

        Args:
            rel_id: Relationship ID.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                "DELETE FROM block_relationships WHERE id = ?",
                (rel_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.warning("Failed to delete relationship %s: %s", rel_id, e)
            return False

    def delete_relationships_for_block(self, block_id: str) -> int:
        """Delete all relationships involving a block.

        Args:
            block_id: Block ID.

        Returns:
            Number of relationships deleted.
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                """
                DELETE FROM block_relationships
                WHERE source_block_id = ? OR target_block_id = ?
                """,
                (block_id, block_id),
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            logger.warning(
                "Failed to delete relationships for block %s: %s", block_id, e
            )
            return 0

    # =========================================================================
    # Graph Traversal
    # =========================================================================

    def traverse(
        self,
        start_id: str,
        *,
        max_depth: int = 2,
        rel_types: list[RelationshipType] | None = None,
        direction: str = "both",
        max_nodes: int = 100,
    ) -> TraversalResult:
        """Traverse the graph from a starting block.

        Breadth-first traversal that expands relationships up to max_depth.

        Args:
            start_id: Starting block ID.
            max_depth: Maximum traversal depth (default 2).
            rel_types: Filter by relationship types (None = all).
            direction: "outgoing", "incoming", or "both".
            max_nodes: Maximum nodes to visit.

        Returns:
            TraversalResult with visited blocks and edges.
        """
        result = TraversalResult(start_block_id=start_id)
        result.visited_blocks.add(start_id)
        result.blocks_by_depth[0] = [start_id]

        # BFS queue: (block_id, depth)
        queue: list[tuple[str, int]] = [(start_id, 0)]

        while queue and len(result.visited_blocks) < max_nodes:
            current_id, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            # Get edges from current node
            edges = self.get_relationships(
                current_id,
                direction=direction,
                rel_types=rel_types,
            )

            for edge in edges:
                result.edges.append(edge)

                # Determine the "other" node in the edge
                if edge.source_block_id == current_id:
                    other_id = edge.target_block_id
                else:
                    other_id = edge.source_block_id

                # Visit if not seen
                if other_id not in result.visited_blocks:
                    result.visited_blocks.add(other_id)
                    next_depth = depth + 1
                    if next_depth not in result.blocks_by_depth:
                        result.blocks_by_depth[next_depth] = []
                    result.blocks_by_depth[next_depth].append(other_id)
                    queue.append((other_id, next_depth))

        return result

    def find_path(
        self,
        start_id: str,
        end_id: str,
        *,
        max_depth: int = 5,
        rel_types: list[RelationshipType] | None = None,
    ) -> list[GraphEdge] | None:
        """Find a path between two blocks.

        BFS to find shortest path.

        Args:
            start_id: Starting block ID.
            end_id: Target block ID.
            max_depth: Maximum path length.
            rel_types: Filter by relationship types.

        Returns:
            List of edges forming the path, or None if no path found.
        """
        if start_id == end_id:
            return []

        # BFS with parent tracking
        visited: set[str] = {start_id}
        parent: dict[str, tuple[str, GraphEdge]] = {}  # child -> (parent, edge)
        queue: list[tuple[str, int]] = [(start_id, 0)]

        while queue:
            current_id, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            edges = self.get_relationships(
                current_id,
                direction="both",
                rel_types=rel_types,
            )

            for edge in edges:
                if edge.source_block_id == current_id:
                    other_id = edge.target_block_id
                else:
                    other_id = edge.source_block_id

                if other_id in visited:
                    continue

                visited.add(other_id)
                parent[other_id] = (current_id, edge)

                if other_id == end_id:
                    # Reconstruct path
                    path: list[GraphEdge] = []
                    node = end_id
                    while node in parent:
                        prev_node, edge = parent[node]
                        path.append(edge)
                        node = prev_node
                    path.reverse()
                    return path

                queue.append((other_id, depth + 1))

        return None

    # =========================================================================
    # Embedding Storage
    # =========================================================================

    def store_embedding(
        self,
        block_id: str,
        embedding: bytes,
        content_hash: str,
        model_name: str = "all-MiniLM-L6-v2",
    ) -> bool:
        """Store or update a block's embedding.

        Args:
            block_id: Block ID.
            embedding: Embedding as bytes.
            content_hash: Hash of the content that was embedded.
            model_name: Name of the embedding model.

        Returns:
            True if stored/updated, False on error.
        """
        conn = self._get_connection()
        now = self._now_iso()

        try:
            conn.execute(
                """
                INSERT INTO block_embeddings (block_id, embedding, content_hash,
                                              embedding_model, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(block_id) DO UPDATE SET
                    embedding = excluded.embedding,
                    content_hash = excluded.content_hash,
                    embedding_model = excluded.embedding_model,
                    created_at = excluded.created_at
                """,
                (block_id, embedding, content_hash, model_name, now),
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.warning(
                "Failed to store embedding for block %s (model=%s): %s",
                block_id,
                model_name,
                e,
            )
            return False

    def get_embedding(self, block_id: str) -> tuple[bytes, str] | None:
        """Get a block's embedding.

        Args:
            block_id: Block ID.

        Returns:
            Tuple of (embedding bytes, content_hash), or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT embedding, content_hash FROM block_embeddings WHERE block_id = ?",
            (block_id,),
        )
        row = cursor.fetchone()
        if row:
            return row["embedding"], row["content_hash"]
        return None

    def get_all_embeddings(
        self,
        act_id: str | None = None,
    ) -> list[tuple[str, bytes]]:
        """Get all embeddings, optionally filtered by act.

        Args:
            act_id: Optional act ID to filter by.

        Returns:
            List of (block_id, embedding) tuples.
        """
        conn = self._get_connection()

        if act_id:
            cursor = conn.execute(
                """
                SELECT be.block_id, be.embedding
                FROM block_embeddings be
                JOIN blocks b ON be.block_id = b.id
                WHERE b.act_id = ?
                """,
                (act_id,),
            )
        else:
            cursor = conn.execute(
                "SELECT block_id, embedding FROM block_embeddings"
            )

        return [(row["block_id"], row["embedding"]) for row in cursor.fetchall()]

    def delete_embedding(self, block_id: str) -> bool:
        """Delete a block's embedding.

        Args:
            block_id: Block ID.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()

        try:
            cursor = conn.execute(
                "DELETE FROM block_embeddings WHERE block_id = ?",
                (block_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            logger.warning("Failed to delete embedding for block %s: %s", block_id, e)
            return False

    def is_embedding_stale(self, block_id: str, current_hash: str) -> bool:
        """Check if a block's embedding is stale.

        Args:
            block_id: Block ID.
            current_hash: Current content hash.

        Returns:
            True if stale or missing, False if up-to-date.
        """
        result = self.get_embedding(block_id)
        if result is None:
            return True
        _, stored_hash = result
        return stored_hash != current_hash
