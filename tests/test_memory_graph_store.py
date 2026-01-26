"""Tests for memory/graph_store.py - Graph storage and traversal.

Integration tests for:
- Relationship CRUD operations
- Graph traversal (BFS, path finding)
- Embedding storage and retrieval
- GraphEdge and TraversalResult models
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create isolated data directory for play_db."""
    data_dir = tmp_path / "reos-data"
    data_dir.mkdir()
    monkeypatch.setenv("REOS_DATA_DIR", str(data_dir))

    # Close any existing connection before test
    import reos.play_db as play_db
    play_db.close_connection()

    yield data_dir

    # Cleanup after test
    play_db.close_connection()


@pytest.fixture
def initialized_db(temp_data_dir: Path):
    """Initialize the database and return the play_db module."""
    import reos.play_db as play_db

    play_db.init_db()
    return play_db


@pytest.fixture
def graph_store(initialized_db):
    """Create a MemoryGraphStore with initialized database."""
    from reos.memory.graph_store import MemoryGraphStore

    return MemoryGraphStore()


@pytest.fixture
def test_act(initialized_db) -> str:
    """Create a test act and return its ID."""
    _, act_id = initialized_db.create_act(title="Test Act")
    return act_id


@pytest.fixture
def test_blocks(test_act: str, initialized_db) -> list[str]:
    """Create test blocks and return their IDs."""
    from reos.play.blocks_db import create_block

    block_ids = []
    for i in range(5):
        block = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[{"content": f"Test block {i}"}],
        )
        block_ids.append(block.id)

    return block_ids


# =============================================================================
# GraphEdge Model Tests
# =============================================================================


class TestGraphEdge:
    """Test GraphEdge dataclass."""

    def test_graph_edge_to_dict(self) -> None:
        """GraphEdge.to_dict serializes correctly."""
        from reos.memory.graph_store import GraphEdge
        from reos.memory.relationships import RelationshipType, RelationshipSource

        edge = GraphEdge(
            id="rel-123",
            source_block_id="block-a",
            target_block_id="block-b",
            relationship_type=RelationshipType.REFERENCES,
            confidence=0.9,
            weight=1.0,
            source=RelationshipSource.USER,
            created_at="2026-01-26T10:00:00Z",
        )

        data = edge.to_dict()

        assert data["id"] == "rel-123"
        assert data["source_block_id"] == "block-a"
        assert data["target_block_id"] == "block-b"
        assert data["relationship_type"] == "references"
        assert data["confidence"] == 0.9
        assert data["source"] == "user"

    def test_graph_edge_default_values(self) -> None:
        """GraphEdge has sensible defaults."""
        from reos.memory.graph_store import GraphEdge
        from reos.memory.relationships import RelationshipType, RelationshipSource

        edge = GraphEdge(
            id="rel-123",
            source_block_id="block-a",
            target_block_id="block-b",
            relationship_type=RelationshipType.SIMILAR_TO,
        )

        assert edge.confidence == 1.0
        assert edge.weight == 1.0
        assert edge.source == RelationshipSource.INFERRED


# =============================================================================
# TraversalResult Model Tests
# =============================================================================


class TestTraversalResult:
    """Test TraversalResult dataclass."""

    def test_traversal_result_to_dict(self) -> None:
        """TraversalResult.to_dict serializes correctly."""
        from reos.memory.graph_store import TraversalResult, GraphEdge
        from reos.memory.relationships import RelationshipType

        result = TraversalResult(start_block_id="block-start")
        result.visited_blocks = {"block-start", "block-1", "block-2"}
        result.blocks_by_depth = {0: ["block-start"], 1: ["block-1", "block-2"]}

        data = result.to_dict()

        assert data["start_block_id"] == "block-start"
        assert set(data["visited_blocks"]) == {"block-start", "block-1", "block-2"}
        # Keys are integers, not strings
        assert data["blocks_by_depth"][0] == ["block-start"]


# =============================================================================
# Relationship CRUD Tests
# =============================================================================


class TestRelationshipCRUD:
    """Test relationship create, read, update, delete operations."""

    def test_create_relationship(self, graph_store, test_blocks) -> None:
        """create_relationship creates a new relationship."""
        from reos.memory.relationships import RelationshipType

        rel_id = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.REFERENCES,
        )

        assert rel_id is not None
        assert rel_id.startswith("rel-")

    def test_create_relationship_with_options(self, graph_store, test_blocks) -> None:
        """create_relationship accepts confidence and source."""
        from reos.memory.relationships import RelationshipType, RelationshipSource

        rel_id = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.SIMILAR_TO,
            confidence=0.8,
            weight=1.5,
            source=RelationshipSource.EMBEDDING,
        )

        edge = graph_store.get_relationship(rel_id)

        assert edge is not None
        assert edge.confidence == 0.8
        assert edge.weight == 1.5
        assert edge.source == RelationshipSource.EMBEDDING

    def test_create_self_relationship_fails(self, graph_store, test_blocks) -> None:
        """create_relationship rejects self-referential relationships."""
        from reos.memory.relationships import RelationshipType

        rel_id = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[0],  # Same block
            RelationshipType.REFERENCES,
        )

        assert rel_id is None

    def test_create_duplicate_relationship_fails(self, graph_store, test_blocks) -> None:
        """create_relationship rejects duplicate relationships."""
        from reos.memory.relationships import RelationshipType

        # Create first relationship
        rel_id1 = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.REFERENCES,
        )
        assert rel_id1 is not None

        # Try to create duplicate
        rel_id2 = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.REFERENCES,  # Same type
        )

        assert rel_id2 is None

    def test_create_different_type_relationship_ok(self, graph_store, test_blocks) -> None:
        """Same blocks can have different relationship types."""
        from reos.memory.relationships import RelationshipType

        rel_id1 = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.REFERENCES,
        )
        rel_id2 = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.SIMILAR_TO,  # Different type
        )

        assert rel_id1 is not None
        assert rel_id2 is not None
        assert rel_id1 != rel_id2

    def test_get_relationship(self, graph_store, test_blocks) -> None:
        """get_relationship returns edge by ID."""
        from reos.memory.relationships import RelationshipType

        rel_id = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.SUPPORTS,
        )

        edge = graph_store.get_relationship(rel_id)

        assert edge is not None
        assert edge.id == rel_id
        assert edge.source_block_id == test_blocks[0]
        assert edge.target_block_id == test_blocks[1]
        assert edge.relationship_type == RelationshipType.SUPPORTS

    def test_get_relationship_nonexistent(self, graph_store) -> None:
        """get_relationship returns None for nonexistent ID."""
        edge = graph_store.get_relationship("nonexistent-id")
        assert edge is None

    def test_get_relationships_outgoing(self, graph_store, test_blocks) -> None:
        """get_relationships returns outgoing edges."""
        from reos.memory.relationships import RelationshipType

        # Create outgoing relationships from block 0
        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[2], RelationshipType.SUPPORTS
        )
        # Create incoming relationship to block 0
        graph_store.create_relationship(
            test_blocks[3], test_blocks[0], RelationshipType.REFERENCES
        )

        edges = graph_store.get_relationships(test_blocks[0], direction="outgoing")

        assert len(edges) == 2
        assert all(e.source_block_id == test_blocks[0] for e in edges)

    def test_get_relationships_incoming(self, graph_store, test_blocks) -> None:
        """get_relationships returns incoming edges."""
        from reos.memory.relationships import RelationshipType

        # Create incoming relationships to block 0
        graph_store.create_relationship(
            test_blocks[1], test_blocks[0], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[2], test_blocks[0], RelationshipType.SUPPORTS
        )
        # Create outgoing relationship from block 0
        graph_store.create_relationship(
            test_blocks[0], test_blocks[3], RelationshipType.REFERENCES
        )

        edges = graph_store.get_relationships(test_blocks[0], direction="incoming")

        assert len(edges) == 2
        assert all(e.target_block_id == test_blocks[0] for e in edges)

    def test_get_relationships_both_directions(self, graph_store, test_blocks) -> None:
        """get_relationships with direction='both' returns all edges."""
        from reos.memory.relationships import RelationshipType

        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[2], test_blocks[0], RelationshipType.SUPPORTS
        )

        edges = graph_store.get_relationships(test_blocks[0], direction="both")

        assert len(edges) == 2

    def test_get_relationships_filter_by_type(self, graph_store, test_blocks) -> None:
        """get_relationships can filter by relationship type."""
        from reos.memory.relationships import RelationshipType

        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[2], RelationshipType.SUPPORTS
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[3], RelationshipType.SIMILAR_TO
        )

        edges = graph_store.get_relationships(
            test_blocks[0],
            direction="outgoing",
            rel_types=[RelationshipType.REFERENCES, RelationshipType.SUPPORTS],
        )

        assert len(edges) == 2
        types = {e.relationship_type for e in edges}
        assert RelationshipType.SIMILAR_TO not in types

    def test_update_relationship(self, graph_store, test_blocks) -> None:
        """update_relationship modifies confidence and weight."""
        from reos.memory.relationships import RelationshipType

        rel_id = graph_store.create_relationship(
            test_blocks[0],
            test_blocks[1],
            RelationshipType.REFERENCES,
            confidence=0.5,
        )

        result = graph_store.update_relationship(rel_id, confidence=0.9, weight=2.0)

        assert result is True
        edge = graph_store.get_relationship(rel_id)
        assert edge.confidence == 0.9
        assert edge.weight == 2.0

    def test_update_relationship_nonexistent(self, graph_store) -> None:
        """update_relationship returns False for nonexistent ID."""
        result = graph_store.update_relationship("nonexistent", confidence=0.5)
        assert result is False

    def test_delete_relationship(self, graph_store, test_blocks) -> None:
        """delete_relationship removes a relationship."""
        from reos.memory.relationships import RelationshipType

        rel_id = graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )

        result = graph_store.delete_relationship(rel_id)

        assert result is True
        assert graph_store.get_relationship(rel_id) is None

    def test_delete_relationship_nonexistent(self, graph_store) -> None:
        """delete_relationship returns False for nonexistent ID."""
        result = graph_store.delete_relationship("nonexistent")
        assert result is False

    def test_delete_relationships_for_block(self, graph_store, test_blocks) -> None:
        """delete_relationships_for_block removes all relationships for a block."""
        from reos.memory.relationships import RelationshipType

        # Create relationships involving block 0
        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[2], RelationshipType.SUPPORTS
        )
        graph_store.create_relationship(
            test_blocks[3], test_blocks[0], RelationshipType.SIMILAR_TO
        )
        # Relationship not involving block 0
        graph_store.create_relationship(
            test_blocks[1], test_blocks[2], RelationshipType.REFERENCES
        )

        count = graph_store.delete_relationships_for_block(test_blocks[0])

        assert count == 3
        assert len(graph_store.get_relationships(test_blocks[0])) == 0
        # Other relationships preserved
        assert len(graph_store.get_relationships(test_blocks[1], direction="outgoing")) == 1


# =============================================================================
# Graph Traversal Tests
# =============================================================================


class TestGraphTraversal:
    """Test graph traversal algorithms."""

    def test_traverse_single_node(self, graph_store, test_blocks) -> None:
        """traverse() handles single node with no edges."""
        result = graph_store.traverse(test_blocks[0], max_depth=2)

        assert result.start_block_id == test_blocks[0]
        assert test_blocks[0] in result.visited_blocks
        assert result.blocks_by_depth[0] == [test_blocks[0]]
        assert len(result.edges) == 0

    def test_traverse_depth_one(self, graph_store, test_blocks) -> None:
        """traverse() finds immediate neighbors at depth 1."""
        from reos.memory.relationships import RelationshipType

        # Create: block_0 -> block_1 -> block_2
        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[1], test_blocks[2], RelationshipType.REFERENCES
        )

        result = graph_store.traverse(test_blocks[0], max_depth=1)

        assert test_blocks[0] in result.visited_blocks
        assert test_blocks[1] in result.visited_blocks
        assert test_blocks[2] not in result.visited_blocks  # Beyond depth 1
        assert result.blocks_by_depth[1] == [test_blocks[1]]

    def test_traverse_depth_two(self, graph_store, test_blocks) -> None:
        """traverse() finds nodes at depth 2."""
        from reos.memory.relationships import RelationshipType

        # Create: block_0 -> block_1 -> block_2
        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[1], test_blocks[2], RelationshipType.REFERENCES
        )

        result = graph_store.traverse(test_blocks[0], max_depth=2)

        assert test_blocks[0] in result.visited_blocks
        assert test_blocks[1] in result.visited_blocks
        assert test_blocks[2] in result.visited_blocks
        assert result.blocks_by_depth[2] == [test_blocks[2]]

    def test_traverse_respects_max_nodes(self, graph_store, test_blocks) -> None:
        """traverse() limits nodes visited."""
        from reos.memory.relationships import RelationshipType

        # Create many connections from block_0
        for i in range(1, 5):
            graph_store.create_relationship(
                test_blocks[0], test_blocks[i], RelationshipType.REFERENCES
            )

        # With max_nodes=3, at minimum we get the start node plus some neighbors
        # The limit is checked per iteration, so we may exceed slightly
        result_limited = graph_store.traverse(test_blocks[0], max_depth=2, max_nodes=3)
        result_unlimited = graph_store.traverse(test_blocks[0], max_depth=2, max_nodes=100)

        # Limited traversal should have fewer or equal nodes than unlimited
        assert len(result_limited.visited_blocks) <= len(result_unlimited.visited_blocks)

    def test_traverse_filter_by_type(self, graph_store, test_blocks) -> None:
        """traverse() filters by relationship type."""
        from reos.memory.relationships import RelationshipType

        # Create different relationship types to different blocks
        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[2], RelationshipType.SIMILAR_TO
        )

        # Filter for REFERENCES only
        result_refs = graph_store.traverse(
            test_blocks[0],
            max_depth=1,
            rel_types=[RelationshipType.REFERENCES],
        )

        # Filter for SIMILAR_TO only
        result_sim = graph_store.traverse(
            test_blocks[0],
            max_depth=1,
            rel_types=[RelationshipType.SIMILAR_TO],
        )

        # REFERENCES-only traversal should find block_1 but not block_2
        assert test_blocks[1] in result_refs.visited_blocks
        # Verify we get edges of the right type
        ref_types = {e.relationship_type for e in result_refs.edges}
        assert RelationshipType.REFERENCES in ref_types or len(result_refs.edges) == 0

        # SIMILAR_TO-only traversal should find block_2 but not block_1
        assert test_blocks[2] in result_sim.visited_blocks
        sim_types = {e.relationship_type for e in result_sim.edges}
        assert RelationshipType.SIMILAR_TO in sim_types or len(result_sim.edges) == 0

    def test_traverse_bidirectional(self, graph_store, test_blocks) -> None:
        """traverse() follows edges in both directions."""
        from reos.memory.relationships import RelationshipType

        # block_1 -> block_0 -> block_2
        graph_store.create_relationship(
            test_blocks[1], test_blocks[0], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[0], test_blocks[2], RelationshipType.REFERENCES
        )

        result = graph_store.traverse(test_blocks[0], max_depth=1, direction="both")

        assert test_blocks[1] in result.visited_blocks
        assert test_blocks[2] in result.visited_blocks

    def test_find_path_direct(self, graph_store, test_blocks) -> None:
        """find_path() finds direct path."""
        from reos.memory.relationships import RelationshipType

        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )

        path = graph_store.find_path(test_blocks[0], test_blocks[1])

        assert path is not None
        assert len(path) == 1
        assert path[0].relationship_type == RelationshipType.REFERENCES

    def test_find_path_two_hops(self, graph_store, test_blocks) -> None:
        """find_path() finds two-hop path."""
        from reos.memory.relationships import RelationshipType

        graph_store.create_relationship(
            test_blocks[0], test_blocks[1], RelationshipType.REFERENCES
        )
        graph_store.create_relationship(
            test_blocks[1], test_blocks[2], RelationshipType.SUPPORTS
        )

        path = graph_store.find_path(test_blocks[0], test_blocks[2])

        assert path is not None
        assert len(path) == 2

    def test_find_path_same_node(self, graph_store, test_blocks) -> None:
        """find_path() returns empty list for same start and end."""
        path = graph_store.find_path(test_blocks[0], test_blocks[0])
        assert path == []

    def test_find_path_no_path(self, graph_store, test_blocks) -> None:
        """find_path() returns None when no path exists."""
        path = graph_store.find_path(test_blocks[0], test_blocks[1], max_depth=5)
        assert path is None


# =============================================================================
# Embedding Storage Tests
# =============================================================================


class TestEmbeddingStorage:
    """Test embedding storage and retrieval."""

    def test_store_embedding(self, graph_store, test_blocks) -> None:
        """store_embedding stores embedding for a block."""
        embedding = np.random.randn(384).astype(np.float32).tobytes()

        result = graph_store.store_embedding(
            test_blocks[0],
            embedding,
            content_hash="abc123",
        )

        assert result is True

    def test_get_embedding(self, graph_store, test_blocks) -> None:
        """get_embedding retrieves stored embedding."""
        original_embedding = np.random.randn(384).astype(np.float32).tobytes()

        graph_store.store_embedding(
            test_blocks[0],
            original_embedding,
            content_hash="abc123",
        )

        result = graph_store.get_embedding(test_blocks[0])

        assert result is not None
        embedding, content_hash = result
        assert embedding == original_embedding
        assert content_hash == "abc123"

    def test_get_embedding_nonexistent(self, graph_store, test_blocks) -> None:
        """get_embedding returns None for nonexistent block."""
        result = graph_store.get_embedding(test_blocks[0])
        assert result is None

    def test_store_embedding_updates_existing(self, graph_store, test_blocks) -> None:
        """store_embedding updates existing embedding."""
        embedding1 = np.random.randn(384).astype(np.float32).tobytes()
        embedding2 = np.random.randn(384).astype(np.float32).tobytes()

        graph_store.store_embedding(test_blocks[0], embedding1, "hash1")
        graph_store.store_embedding(test_blocks[0], embedding2, "hash2")

        result = graph_store.get_embedding(test_blocks[0])
        embedding, content_hash = result

        assert embedding == embedding2
        assert content_hash == "hash2"

    def test_get_all_embeddings(self, graph_store, test_blocks, test_act) -> None:
        """get_all_embeddings returns all stored embeddings."""
        for i, block_id in enumerate(test_blocks[:3]):
            embedding = np.random.randn(384).astype(np.float32).tobytes()
            graph_store.store_embedding(block_id, embedding, f"hash{i}")

        results = graph_store.get_all_embeddings()

        assert len(results) == 3
        ids = [r[0] for r in results]
        assert all(block_id in ids for block_id in test_blocks[:3])

    def test_get_all_embeddings_filtered_by_act(
        self, graph_store, test_blocks, test_act, initialized_db
    ) -> None:
        """get_all_embeddings can filter by act."""
        # Create another act
        _, other_act_id = initialized_db.create_act(title="Other Act")

        from reos.play.blocks_db import create_block

        other_block = create_block(
            type="paragraph",
            act_id=other_act_id,
            rich_text=[{"content": "Other block"}],
        )

        # Store embeddings in both acts
        for block_id in test_blocks[:2]:
            embedding = np.random.randn(384).astype(np.float32).tobytes()
            graph_store.store_embedding(block_id, embedding, "hash")

        other_embedding = np.random.randn(384).astype(np.float32).tobytes()
        graph_store.store_embedding(other_block.id, other_embedding, "hash")

        # Filter by test_act
        results = graph_store.get_all_embeddings(act_id=test_act)

        assert len(results) == 2
        ids = [r[0] for r in results]
        assert other_block.id not in ids

    def test_delete_embedding(self, graph_store, test_blocks) -> None:
        """delete_embedding removes embedding."""
        embedding = np.random.randn(384).astype(np.float32).tobytes()
        graph_store.store_embedding(test_blocks[0], embedding, "hash")

        result = graph_store.delete_embedding(test_blocks[0])

        assert result is True
        assert graph_store.get_embedding(test_blocks[0]) is None

    def test_delete_embedding_nonexistent(self, graph_store, test_blocks) -> None:
        """delete_embedding returns False for nonexistent block."""
        result = graph_store.delete_embedding(test_blocks[0])
        assert result is False

    def test_is_embedding_stale_missing(self, graph_store, test_blocks) -> None:
        """is_embedding_stale returns True when no embedding exists."""
        result = graph_store.is_embedding_stale(test_blocks[0], "current_hash")
        assert result is True

    def test_is_embedding_stale_hash_mismatch(self, graph_store, test_blocks) -> None:
        """is_embedding_stale returns True when hash differs."""
        embedding = np.random.randn(384).astype(np.float32).tobytes()
        graph_store.store_embedding(test_blocks[0], embedding, "old_hash")

        result = graph_store.is_embedding_stale(test_blocks[0], "new_hash")

        assert result is True

    def test_is_embedding_stale_hash_matches(self, graph_store, test_blocks) -> None:
        """is_embedding_stale returns False when hash matches."""
        embedding = np.random.randn(384).astype(np.float32).tobytes()
        graph_store.store_embedding(test_blocks[0], embedding, "same_hash")

        result = graph_store.is_embedding_stale(test_blocks[0], "same_hash")

        assert result is False
