"""Tests for rpc_handlers/memory.py - Memory RPC handlers.

Contract tests for the memory RPC API:
- Relationship CRUD endpoints
- Search and retrieval endpoints
- Index management endpoints
- Learning endpoints
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

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

    import reos.play_db as play_db
    play_db.close_connection()

    yield data_dir

    play_db.close_connection()


@pytest.fixture
def initialized_db(temp_data_dir: Path):
    """Initialize the database and return the play_db module."""
    import reos.play_db as play_db

    play_db.init_db()

    # Reset memory RPC singletons to ensure test isolation
    import reos.rpc_handlers.memory as memory_rpc
    memory_rpc._graph_store = None
    memory_rpc._retriever = None
    memory_rpc._extractor = None

    yield play_db

    # Cleanup singletons after test
    memory_rpc._graph_store = None
    memory_rpc._retriever = None
    memory_rpc._extractor = None


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
            rich_text=[{"content": f"Test block content {i}"}],
        )
        block_ids.append(block.id)

    return block_ids


@pytest.fixture
def mock_embedding_service(monkeypatch):
    """Create a mock embedding service."""
    from reos.memory import embeddings as emb_mod

    mock = Mock()
    mock.is_available = True
    mock.embedding_dim = 384
    mock.model_name = "all-MiniLM-L6-v2"

    def mock_embed(text):
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        seed = int(h[:8], 16)
        rng = np.random.RandomState(seed)
        return rng.randn(384).astype(np.float32).tobytes()

    mock.embed = mock_embed

    def mock_find_similar(query_emb, candidates, threshold=0.5, top_k=10):
        results = []
        for block_id, emb in candidates[:top_k]:
            query_vec = np.frombuffer(query_emb, dtype=np.float32)
            cand_vec = np.frombuffer(emb, dtype=np.float32)
            norm_q = np.linalg.norm(query_vec)
            norm_c = np.linalg.norm(cand_vec)
            if norm_q > 0 and norm_c > 0:
                sim = float(np.dot(query_vec, cand_vec) / (norm_q * norm_c))
                if sim >= threshold:
                    results.append((block_id, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    mock.find_similar = mock_find_similar

    monkeypatch.setattr(emb_mod, "get_embedding_service", lambda: mock)

    return mock


# =============================================================================
# Relationship CRUD Tests
# =============================================================================


class TestRelationshipCreateHandler:
    """Test memory/relationships/create handler."""

    def test_create_relationship(self, initialized_db, test_blocks) -> None:
        """Create relationship returns relationship data."""
        from reos.rpc_handlers.memory import handle_memory_relationships_create

        result = handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )

        assert result is not None
        assert "relationship" in result
        assert result["relationship"]["source_block_id"] == test_blocks[0]
        assert result["relationship"]["target_block_id"] == test_blocks[1]
        assert result["relationship"]["relationship_type"] == "references"

    def test_create_relationship_with_options(self, initialized_db, test_blocks) -> None:
        """Create relationship accepts confidence and source."""
        from reos.rpc_handlers.memory import handle_memory_relationships_create

        result = handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="similar_to",
            confidence=0.85,
            source="embedding",
        )

        assert result["relationship"]["confidence"] == 0.85
        assert result["relationship"]["source"] == "embedding"

    def test_create_duplicate_relationship_fails(self, initialized_db, test_blocks) -> None:
        """Create duplicate relationship raises error."""
        from reos.rpc_handlers.memory import handle_memory_relationships_create
        from reos.rpc_handlers import RpcError

        # Create first
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )

        # Try duplicate - should raise RpcError
        with pytest.raises(RpcError):
            handle_memory_relationships_create(
                initialized_db,
                source_id=test_blocks[0],
                target_id=test_blocks[1],
                rel_type="references",
            )


class TestRelationshipListHandler:
    """Test memory/relationships/list handler."""

    def test_list_relationships(self, initialized_db, test_blocks) -> None:
        """List relationships returns edges for block."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_relationships_list,
        )

        # Create some relationships
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[2],
            rel_type="supports",
        )

        result = handle_memory_relationships_list(
            initialized_db,
            block_id=test_blocks[0],
        )

        assert "relationships" in result
        assert len(result["relationships"]) == 2

    def test_list_relationships_filter_direction(
        self, initialized_db, test_blocks
    ) -> None:
        """List relationships filters by direction."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_relationships_list,
        )

        # Create outgoing
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        # Create incoming
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[2],
            target_id=test_blocks[0],
            rel_type="supports",
        )

        # Get outgoing only
        result = handle_memory_relationships_list(
            initialized_db,
            block_id=test_blocks[0],
            direction="outgoing",
        )

        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["source_block_id"] == test_blocks[0]

    def test_list_relationships_filter_types(
        self, initialized_db, test_blocks
    ) -> None:
        """List relationships filters by type."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_relationships_list,
        )

        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[2],
            rel_type="similar_to",
        )

        # Filter for references only
        result = handle_memory_relationships_list(
            initialized_db,
            block_id=test_blocks[0],
            rel_types=["references"],
        )

        # All returned relationships should be of type "references"
        assert len(result["relationships"]) >= 1
        for rel in result["relationships"]:
            assert rel["relationship_type"] == "references"


class TestRelationshipUpdateHandler:
    """Test memory/relationships/update handler."""

    def test_update_relationship(self, initialized_db, test_blocks) -> None:
        """Update relationship modifies confidence."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_relationships_update,
        )

        # Create
        create_result = handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
            confidence=0.5,
        )
        rel_id = create_result["relationship"]["id"]

        # Update - returns updated relationship
        result = handle_memory_relationships_update(
            initialized_db,
            relationship_id=rel_id,
            confidence=0.9,
        )

        assert "relationship" in result
        assert result["relationship"]["confidence"] == 0.9

    def test_update_nonexistent_relationship(self, initialized_db) -> None:
        """Update nonexistent relationship raises error."""
        from reos.rpc_handlers.memory import handle_memory_relationships_update
        from reos.rpc_handlers import RpcError

        with pytest.raises(RpcError):
            handle_memory_relationships_update(
                initialized_db,
                relationship_id="nonexistent",
                confidence=0.9,
            )


class TestRelationshipDeleteHandler:
    """Test memory/relationships/delete handler."""

    def test_delete_relationship(self, initialized_db, test_blocks) -> None:
        """Delete relationship removes it."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_relationships_delete,
            handle_memory_relationships_list,
        )

        # Create
        create_result = handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        rel_id = create_result["relationship"]["id"]

        # Delete
        result = handle_memory_relationships_delete(
            initialized_db,
            relationship_id=rel_id,
        )

        assert result["deleted"] is True

        # Verify gone
        list_result = handle_memory_relationships_list(
            initialized_db,
            block_id=test_blocks[0],
        )
        assert len(list_result["relationships"]) == 0


# =============================================================================
# Search and Retrieval Tests
# =============================================================================


class TestMemorySearchHandler:
    """Test memory/search handler."""

    def test_search_returns_context(
        self, initialized_db, test_blocks, mock_embedding_service, test_act
    ) -> None:
        """Search returns memory context."""
        from reos.rpc_handlers.memory import (
            handle_memory_index_block,
            handle_memory_search,
        )

        # Index blocks
        for block_id in test_blocks:
            handle_memory_index_block(initialized_db, block_id=block_id)

        result = handle_memory_search(
            initialized_db,
            query="test content",
            act_id=test_act,
        )

        assert "query" in result
        assert "matches" in result
        assert "stats" in result

    def test_search_respects_max_results(
        self, initialized_db, test_blocks, mock_embedding_service, test_act
    ) -> None:
        """Search respects max_results parameter."""
        from reos.rpc_handlers.memory import (
            handle_memory_index_block,
            handle_memory_search,
        )

        for block_id in test_blocks:
            handle_memory_index_block(initialized_db, block_id=block_id)

        result = handle_memory_search(
            initialized_db,
            query="test",
            max_results=2,
            act_id=test_act,
        )

        assert len(result["matches"]) <= 2


class TestMemoryRelatedHandler:
    """Test memory/related handler."""

    def test_related_returns_traversal(self, initialized_db, test_blocks) -> None:
        """Related returns graph traversal result."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_related,
        )

        # Create relationships
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )

        result = handle_memory_related(
            initialized_db,
            block_id=test_blocks[0],
            depth=1,
        )

        assert "start_block_id" in result
        assert "visited_blocks" in result
        assert test_blocks[0] in result["visited_blocks"]
        assert test_blocks[1] in result["visited_blocks"]


class TestMemoryPathHandler:
    """Test memory/path handler."""

    def test_path_finds_connection(self, initialized_db, test_blocks) -> None:
        """Path finds path between blocks."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_path,
        )

        # Create path: 0 -> 1 -> 2
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[1],
            target_id=test_blocks[2],
            rel_type="references",
        )

        result = handle_memory_path(
            initialized_db,
            start_id=test_blocks[0],
            end_id=test_blocks[2],
        )

        assert result["found"] is True
        assert len(result["path"]) == 2

    def test_path_not_found(self, initialized_db, test_blocks) -> None:
        """Path returns not found when no connection."""
        from reos.rpc_handlers.memory import handle_memory_path

        result = handle_memory_path(
            initialized_db,
            start_id=test_blocks[0],
            end_id=test_blocks[4],
        )

        assert result["found"] is False


# =============================================================================
# Index Management Tests
# =============================================================================


class TestMemoryIndexBlockHandler:
    """Test memory/index/block handler."""

    def test_index_block(
        self, initialized_db, test_blocks, mock_embedding_service
    ) -> None:
        """Index block stores embedding."""
        from reos.rpc_handlers.memory import handle_memory_index_block

        result = handle_memory_index_block(
            initialized_db,
            block_id=test_blocks[0],
        )

        assert result["indexed"] is True
        assert result["block_id"] == test_blocks[0]

    def test_index_nonexistent_block(
        self, initialized_db, mock_embedding_service
    ) -> None:
        """Index nonexistent block raises error."""
        from reos.rpc_handlers.memory import handle_memory_index_block
        from reos.rpc_handlers import RpcError

        with pytest.raises(RpcError):
            handle_memory_index_block(
                initialized_db,
                block_id="nonexistent",
            )


class TestMemoryIndexBatchHandler:
    """Test memory/index/batch handler."""

    def test_index_batch(
        self, initialized_db, test_blocks, mock_embedding_service
    ) -> None:
        """Index batch indexes multiple blocks."""
        from reos.rpc_handlers.memory import handle_memory_index_batch

        result = handle_memory_index_batch(
            initialized_db,
            block_ids=test_blocks[:3],
        )

        assert result["total"] == 3
        assert result["indexed"] >= 0
        assert result["failed"] >= 0
        assert result["indexed"] + result["failed"] == 3


class TestMemoryIndexRemoveHandler:
    """Test memory/index/remove handler."""

    def test_remove_index(
        self, initialized_db, test_blocks, mock_embedding_service
    ) -> None:
        """Remove index deletes embedding."""
        from reos.rpc_handlers.memory import (
            handle_memory_index_block,
            handle_memory_remove_index,
        )

        # Index first
        handle_memory_index_block(initialized_db, block_id=test_blocks[0])

        # Remove
        result = handle_memory_remove_index(
            initialized_db,
            block_id=test_blocks[0],
        )

        assert result["removed"] is True


# =============================================================================
# Learning Tests
# =============================================================================


class TestMemoryExtractHandler:
    """Test memory/extract handler."""

    def test_extract_from_chain(
        self, initialized_db, test_act, mock_embedding_service
    ) -> None:
        """Extract analyzes chain content."""
        from reos.play.blocks_db import create_block
        from reos.rpc_handlers.memory import handle_memory_extract_relationships

        chain = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Therefore, we should use authentication."}],
        )

        result = handle_memory_extract_relationships(
            initialized_db,
            block_id=chain.id,
            content="Therefore, we should use authentication.",
            act_id=test_act,
        )

        assert "relationships_created" in result


class TestMemoryLearnHandler:
    """Test memory/learn handler."""

    def test_learn_from_feedback(self, initialized_db, test_act) -> None:
        """Learn from feedback processes rating."""
        from reos.play.blocks_db import create_block
        from reos.rpc_handlers.memory import handle_memory_learn_from_feedback

        chain = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Test reasoning"}],
        )

        result = handle_memory_learn_from_feedback(
            initialized_db,
            chain_block_id=chain.id,
            rating=5,
        )

        assert "changes" in result


class TestMemoryAutoLinkHandler:
    """Test memory/auto_link handler."""

    def test_auto_link(
        self, initialized_db, test_blocks, test_act, mock_embedding_service
    ) -> None:
        """Auto link creates similarity relationships."""
        from reos.rpc_handlers.memory import (
            handle_memory_index_batch,
            handle_memory_auto_link,
        )

        # Index blocks first
        handle_memory_index_batch(initialized_db, block_ids=test_blocks)

        result = handle_memory_auto_link(
            initialized_db,
            act_id=test_act,
            threshold=0.0,  # Accept all for testing
        )

        assert "relationships_created" in result


# =============================================================================
# Stats Tests
# =============================================================================


class TestMemoryStatsHandler:
    """Test memory/stats handler."""

    def test_stats_returns_counts(
        self, initialized_db, test_blocks, mock_embedding_service
    ) -> None:
        """Stats returns system statistics."""
        from reos.rpc_handlers.memory import (
            handle_memory_relationships_create,
            handle_memory_index_block,
            handle_memory_stats,
        )

        # Create some data
        handle_memory_relationships_create(
            initialized_db,
            source_id=test_blocks[0],
            target_id=test_blocks[1],
            rel_type="references",
        )
        handle_memory_index_block(initialized_db, block_id=test_blocks[0])

        result = handle_memory_stats(initialized_db)

        assert "total_relationships" in result
        assert "total_embeddings" in result
        assert "relationships_by_type" in result
        assert result["total_relationships"] >= 1
        assert result["total_embeddings"] >= 1


# =============================================================================
# Reasoning Feedback Integration Tests
# =============================================================================


class TestReasoningFeedbackMemoryIntegration:
    """Test that reasoning/feedback triggers memory learning."""

    def test_positive_feedback_triggers_memory_learning(
        self, initialized_db, test_act
    ) -> None:
        """Positive feedback via reasoning/feedback strengthens memory relationships."""
        from reos.play.blocks_db import create_block
        from reos.play.blocks_models import BlockType
        from reos.rpc_handlers.reasoning import handle_reasoning_feedback
        from reos.rpc_handlers.memory import handle_memory_relationships_create

        # Create a reasoning chain
        chain = create_block(
            type=BlockType.REASONING_CHAIN,
            act_id=test_act,
            rich_text=[{"content": "Test reasoning chain"}],
        )

        # Create a target block and relationship
        target = create_block(
            type=BlockType.PARAGRAPH,
            act_id=test_act,
            rich_text=[{"content": "Related knowledge"}],
        )

        # Create a relationship from chain to target
        handle_memory_relationships_create(
            initialized_db,
            source_id=chain.id,
            target_id=target.id,
            rel_type="references",
            confidence=0.5,  # Starting confidence
        )

        # Submit positive feedback via reasoning/feedback RPC
        result = handle_reasoning_feedback(
            initialized_db,
            chain_block_id=chain.id,
            rating=5,  # Thumbs up
        )

        # Verify feedback was stored
        assert result["ok"] is True
        assert result["feedback_status"] == "positive"
        # Verify memory learning was triggered
        assert "memory_changes" in result

    def test_negative_feedback_triggers_memory_learning(
        self, initialized_db, test_act
    ) -> None:
        """Negative feedback via reasoning/feedback triggers memory learning."""
        from reos.play.blocks_db import create_block
        from reos.play.blocks_models import BlockType
        from reos.rpc_handlers.reasoning import handle_reasoning_feedback

        # Create a reasoning chain
        chain = create_block(
            type=BlockType.REASONING_CHAIN,
            act_id=test_act,
            rich_text=[{"content": "Test reasoning chain with bad response"}],
        )

        # Submit negative feedback
        result = handle_reasoning_feedback(
            initialized_db,
            chain_block_id=chain.id,
            rating=1,  # Thumbs down
        )

        # Verify feedback was stored
        assert result["ok"] is True
        assert result["feedback_status"] == "negative"
        # Verify memory learning was triggered
        assert "memory_changes" in result
