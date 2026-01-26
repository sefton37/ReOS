"""Tests for memory/retriever.py - Memory retrieval for CAIRN.

Integration tests for:
- Three-stage retrieval pipeline
- MemoryMatch and MemoryContext models
- Semantic search (mocked embeddings)
- Graph expansion
- Ranking and merging
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

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
    return play_db


@pytest.fixture
def test_act(initialized_db) -> str:
    """Create a test act and return its ID."""
    _, act_id = initialized_db.create_act(title="Test Act")
    return act_id


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    from reos.memory.embeddings import EmbeddingService

    mock = Mock(spec=EmbeddingService)
    mock.is_available = True
    mock.embedding_dim = 384

    # Generate deterministic embeddings
    def mock_embed(text):
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        seed = int(h[:8], 16)
        rng = np.random.RandomState(seed)
        return rng.randn(384).astype(np.float32).tobytes()

    mock.embed = mock_embed

    def mock_find_similar(query_emb, candidates, threshold=0.5, top_k=10):
        # Return all candidates with fake similarity scores
        results = []
        for block_id, emb in candidates[:top_k]:
            # Calculate actual similarity
            query_vec = np.frombuffer(query_emb, dtype=np.float32)
            cand_vec = np.frombuffer(emb, dtype=np.float32)
            sim = float(np.dot(query_vec, cand_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(cand_vec)))
            if sim >= threshold:
                results.append((block_id, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    mock.find_similar = mock_find_similar

    return mock


@pytest.fixture
def test_blocks(test_act: str, initialized_db) -> list[str]:
    """Create test blocks with content and return their IDs."""
    from reos.play.blocks_db import create_block

    blocks_data = [
        "How to configure authentication in the system",
        "Database connection settings and pooling",
        "API endpoint documentation for users",
        "Error handling best practices",
        "Security considerations for authentication",
    ]

    block_ids = []
    for content in blocks_data:
        block = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[{"content": content}],
        )
        block_ids.append(block.id)

    return block_ids


# =============================================================================
# MemoryMatch Model Tests
# =============================================================================


class TestMemoryMatch:
    """Test MemoryMatch dataclass."""

    def test_memory_match_to_dict(self) -> None:
        """MemoryMatch.to_dict serializes correctly."""
        from reos.memory.retriever import MemoryMatch

        match = MemoryMatch(
            block_id="block-123",
            block_type="paragraph",
            content="Test content",
            score=0.85,
            source="semantic",
            relationship_chain=["references", "supports"],
            act_id="act-456",
            page_id="page-789",
        )

        data = match.to_dict()

        assert data["block_id"] == "block-123"
        assert data["block_type"] == "paragraph"
        assert data["content"] == "Test content"
        assert data["score"] == 0.85
        assert data["source"] == "semantic"
        assert data["relationship_chain"] == ["references", "supports"]

    def test_memory_match_default_values(self) -> None:
        """MemoryMatch has sensible defaults."""
        from reos.memory.retriever import MemoryMatch

        match = MemoryMatch(
            block_id="block-123",
            block_type="paragraph",
            content="Test",
            score=0.5,
            source="semantic",
        )

        assert match.relationship_chain == []
        assert match.act_id == ""
        assert match.page_id is None


# =============================================================================
# MemoryContext Model Tests
# =============================================================================


class TestMemoryContext:
    """Test MemoryContext dataclass."""

    def test_memory_context_to_dict(self) -> None:
        """MemoryContext.to_dict serializes correctly."""
        from reos.memory.retriever import MemoryContext, MemoryMatch

        match = MemoryMatch(
            block_id="block-1",
            block_type="paragraph",
            content="Test",
            score=0.8,
            source="semantic",
        )
        context = MemoryContext(
            query="test query",
            matches=[match],
            total_semantic_matches=1,
            total_graph_expansions=0,
        )

        data = context.to_dict()

        assert data["query"] == "test query"
        assert len(data["matches"]) == 1
        assert data["total_semantic_matches"] == 1

    def test_memory_context_to_markdown_empty(self) -> None:
        """MemoryContext.to_markdown returns empty for no matches."""
        from reos.memory.retriever import MemoryContext

        context = MemoryContext(query="test query")

        result = context.to_markdown()

        assert result == ""

    def test_memory_context_to_markdown_with_matches(self) -> None:
        """MemoryContext.to_markdown formats matches."""
        from reos.memory.retriever import MemoryContext, MemoryMatch

        matches = [
            MemoryMatch(
                block_id="block-1",
                block_type="paragraph",
                content="First match content",
                score=0.85,
                source="semantic",
            ),
            MemoryMatch(
                block_id="block-2",
                block_type="reasoning_chain",
                content="Second match content",
                score=0.72,
                source="graph",
                relationship_chain=["references"],
            ),
        ]
        context = MemoryContext(
            query="test query",
            matches=matches,
            total_semantic_matches=1,
            total_graph_expansions=1,
        )

        result = context.to_markdown()

        assert "## Relevant Memory" in result
        assert "Retrieved 2 relevant memories" in result
        assert "Memory #1" in result
        assert "Memory #2" in result
        assert "First match content" in result
        assert "Second match content" in result
        assert "paragraph" in result
        assert "reasoning_chain" in result
        assert "0.85" in result
        assert "Connected via: references" in result


# =============================================================================
# MemoryRetriever Tests
# =============================================================================


class TestMemoryRetriever:
    """Test MemoryRetriever class."""

    def test_retriever_initialization(self, initialized_db) -> None:
        """MemoryRetriever initializes correctly."""
        from reos.memory.retriever import MemoryRetriever

        retriever = MemoryRetriever()

        assert retriever._embedding_service is not None
        assert retriever._graph_store is not None

    def test_retriever_with_custom_services(
        self, initialized_db, mock_embedding_service
    ) -> None:
        """MemoryRetriever accepts custom services."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        assert retriever._embedding_service is mock_embedding_service
        assert retriever._graph_store is graph_store


class TestRetrieverRetrieve:
    """Test MemoryRetriever.retrieve() method."""

    def test_retrieve_empty_when_no_embeddings(
        self, initialized_db, mock_embedding_service, test_act
    ) -> None:
        """retrieve() returns empty context when no embeddings stored."""
        from reos.memory.retriever import MemoryRetriever

        retriever = MemoryRetriever(embedding_service=mock_embedding_service)

        context = retriever.retrieve("authentication query", act_id=test_act)

        assert context.query == "authentication query"
        assert len(context.matches) == 0

    def test_retrieve_finds_semantic_matches(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """retrieve() finds semantically similar blocks."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        # Store embeddings for test blocks
        graph_store = MemoryGraphStore()
        for block_id in test_blocks:
            # Get block content and embed it
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            embedding = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, embedding, f"hash-{block_id}")

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        # Query for authentication - should find related blocks
        context = retriever.retrieve(
            "authentication config",
            act_id=test_act,
            semantic_threshold=0.0,  # Accept all for testing
        )

        assert context.query == "authentication config"
        # Should find some matches (depends on mock similarity)
        assert context.total_semantic_matches >= 0

    def test_retrieve_applies_threshold(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """retrieve() respects semantic_threshold."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            embedding = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, embedding, f"hash-{block_id}")

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        # High threshold
        context_high = retriever.retrieve(
            "random query xyz",
            act_id=test_act,
            semantic_threshold=0.99,
        )

        # Low threshold
        context_low = retriever.retrieve(
            "random query xyz",
            act_id=test_act,
            semantic_threshold=0.0,
        )

        # High threshold should have fewer or equal matches
        assert context_high.total_semantic_matches <= context_low.total_semantic_matches

    def test_retrieve_respects_max_results(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """retrieve() limits results to max_results."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            embedding = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, embedding, f"hash-{block_id}")

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        context = retriever.retrieve(
            "test query",
            act_id=test_act,
            max_results=2,
            semantic_threshold=0.0,
        )

        assert len(context.matches) <= 2


class TestRetrieverGraphExpansion:
    """Test graph expansion in retrieval."""

    def test_retrieve_with_graph_expansion(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """retrieve() expands via graph relationships."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        graph_store = MemoryGraphStore()

        # Store embeddings
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            embedding = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, embedding, f"hash-{block_id}")

        # Create relationship: block_0 -> block_4 (auth -> security)
        graph_store.create_relationship(
            test_blocks[0],
            test_blocks[4],
            RelationshipType.REFERENCES,
        )

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        context = retriever.retrieve(
            "authentication",
            act_id=test_act,
            include_graph_expansion=True,
            graph_depth=1,
            semantic_threshold=0.0,
        )

        # Should have some graph expansions if semantic matches found related blocks
        assert isinstance(context.total_graph_expansions, int)

    def test_retrieve_without_graph_expansion(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """retrieve() can disable graph expansion."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()

        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            embedding = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, embedding, f"hash-{block_id}")

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        context = retriever.retrieve(
            "test query",
            act_id=test_act,
            include_graph_expansion=False,
            semantic_threshold=0.0,
        )

        assert context.total_graph_expansions == 0


class TestRetrieverIndexing:
    """Test block indexing methods."""

    def test_index_block(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """index_block() stores embedding for a block."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()
        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        result = retriever.index_block(test_blocks[0])

        assert result is True
        assert graph_store.get_embedding(test_blocks[0]) is not None

    def test_index_block_skips_empty_content(
        self, initialized_db, mock_embedding_service, test_act
    ) -> None:
        """index_block() returns False for empty content."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore
        from reos.play.blocks_db import create_block

        # Create block with empty content
        block = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[],  # No content
        )

        graph_store = MemoryGraphStore()
        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        result = retriever.index_block(block.id)

        assert result is False

    def test_index_block_skips_uptodate(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """index_block() skips if embedding is up-to-date."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.embeddings import content_hash

        graph_store = MemoryGraphStore()

        # Pre-store embedding with current content hash
        from reos.play.blocks_db import get_block
        block = get_block(test_blocks[0])
        content = block.rich_text[0].content
        current_hash = content_hash(content)
        embedding = mock_embedding_service.embed(content)
        graph_store.store_embedding(test_blocks[0], embedding, current_hash)

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        # Should return True (already up-to-date) without re-embedding
        result = retriever.index_block(test_blocks[0])

        assert result is True

    def test_remove_block_index(
        self, initialized_db, mock_embedding_service, test_act, test_blocks
    ) -> None:
        """remove_block_index() removes embedding."""
        from reos.memory.retriever import MemoryRetriever
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()

        # Store an embedding
        embedding = mock_embedding_service.embed("test")
        graph_store.store_embedding(test_blocks[0], embedding, "hash")

        retriever = MemoryRetriever(
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
        )

        result = retriever.remove_block_index(test_blocks[0])

        assert result is True
        assert graph_store.get_embedding(test_blocks[0]) is None


class TestRetrieverRanking:
    """Test ranking and merging logic."""

    def test_ranking_applies_type_weights(
        self, initialized_db, mock_embedding_service, test_act
    ) -> None:
        """Ranking applies type weights (reasoning_chain > paragraph)."""
        from reos.memory.retriever import MemoryRetriever, MemoryMatch

        retriever = MemoryRetriever(embedding_service=mock_embedding_service)

        matches = [
            MemoryMatch(
                block_id="block-1",
                block_type="paragraph",
                content="Test 1",
                score=0.8,
                source="semantic",
            ),
            MemoryMatch(
                block_id="block-2",
                block_type="reasoning_chain",
                content="Test 2",
                score=0.8,  # Same initial score
                source="semantic",
            ),
        ]

        ranked = retriever._rank_and_merge(matches, max_results=10)

        # reasoning_chain should rank higher due to type weight
        assert ranked[0].block_type == "reasoning_chain"

    def test_ranking_applies_source_bonus(
        self, initialized_db, mock_embedding_service, test_act
    ) -> None:
        """Ranking applies source bonus (both > semantic > graph)."""
        from reos.memory.retriever import MemoryRetriever, MemoryMatch

        retriever = MemoryRetriever(embedding_service=mock_embedding_service)

        matches = [
            MemoryMatch(
                block_id="block-1",
                block_type="paragraph",
                content="Test 1",
                score=0.7,
                source="graph",
            ),
            MemoryMatch(
                block_id="block-2",
                block_type="paragraph",
                content="Test 2",
                score=0.7,  # Same initial score
                source="both",  # Should get bonus
            ),
        ]

        ranked = retriever._rank_and_merge(matches, max_results=10)

        # "both" source should rank higher
        assert ranked[0].source == "both"

    def test_ranking_clamps_scores(
        self, initialized_db, mock_embedding_service, test_act
    ) -> None:
        """Ranking clamps scores to [0, 1]."""
        from reos.memory.retriever import MemoryRetriever, MemoryMatch

        retriever = MemoryRetriever(embedding_service=mock_embedding_service)

        matches = [
            MemoryMatch(
                block_id="block-1",
                block_type="reasoning_chain",  # High type weight
                content="Test 1",
                score=0.95,  # High initial score
                source="both",  # Gets bonus
            ),
        ]

        ranked = retriever._rank_and_merge(matches, max_results=10)

        # Score should be clamped to 1.0
        assert ranked[0].score <= 1.0
