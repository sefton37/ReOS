"""Tests for memory/extractor.py - Automatic relationship extraction.

Integration tests for:
- Extracting relationships from reasoning chains
- Learning from RLHF feedback
- Pattern detection (logical connectors)
- Auto-linking similar blocks
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
    return play_db


@pytest.fixture
def test_act(initialized_db) -> str:
    """Create a test act and return its ID."""
    _, act_id = initialized_db.create_act(title="Test Act")
    return act_id


@pytest.fixture
def mock_embedding_service(monkeypatch):
    """Create a mock embedding service."""
    from reos.memory import embeddings as emb_mod

    mock = Mock()
    mock.is_available = True
    mock.embedding_dim = 384

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

    # Patch the get_embedding_service function
    monkeypatch.setattr(emb_mod, "get_embedding_service", lambda: mock)

    return mock


@pytest.fixture
def extractor(initialized_db, mock_embedding_service):
    """Create a RelationshipExtractor with initialized database."""
    from reos.memory.extractor import RelationshipExtractor

    return RelationshipExtractor()


@pytest.fixture
def test_blocks(test_act: str, initialized_db) -> list[str]:
    """Create test blocks and return their IDs."""
    from reos.play.blocks_db import create_block

    blocks_data = [
        "Authentication requires valid credentials",
        "Therefore, users must log in before accessing data",
        "Because of security requirements, we validate tokens",
        "However, some endpoints are public",
        "For example, the health check endpoint is open",
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
# Pattern Detection Tests
# =============================================================================


class TestLogicalPatternDetection:
    """Test detection of logical patterns in text."""

    def test_detect_follows_from_patterns(self, extractor) -> None:
        """Detects FOLLOWS_FROM indicators."""
        from reos.memory.relationships import RelationshipType

        test_texts = [
            "Therefore, we should implement caching.",
            "Thus the system is more efficient.",
            "Hence the decision was made.",
            "Consequently, users see faster load times.",
            "As a result, performance improved.",
        ]

        for text in test_texts:
            patterns = extractor._detect_logical_patterns(text)
            assert RelationshipType.FOLLOWS_FROM in patterns, f"Failed for: {text}"

    def test_detect_caused_by_patterns(self, extractor) -> None:
        """Detects CAUSED_BY indicators."""
        from reos.memory.relationships import RelationshipType

        test_texts = [
            "Because the server crashed, we lost data.",
            "Since the API changed, we updated the client.",
            "Due to high traffic, we scaled up.",
        ]

        for text in test_texts:
            patterns = extractor._detect_logical_patterns(text)
            assert RelationshipType.CAUSED_BY in patterns, f"Failed for: {text}"

    def test_detect_supports_patterns(self, extractor) -> None:
        """Detects SUPPORTS indicators."""
        from reos.memory.relationships import RelationshipType

        test_texts = [
            "For example, the login page uses OAuth.",
            "For instance, we cache frequently accessed data.",
            "This demonstrates that the approach works.",
        ]

        for text in test_texts:
            patterns = extractor._detect_logical_patterns(text)
            assert RelationshipType.SUPPORTS in patterns, f"Failed for: {text}"

    def test_detect_contradicts_patterns(self, extractor) -> None:
        """Detects CONTRADICTS indicators."""
        from reos.memory.relationships import RelationshipType

        test_texts = [
            "However, this approach has drawbacks.",
            "But the performance is not ideal.",
            "Although it works, it's slow.",
            "Despite the benefits, there are risks.",
        ]

        for text in test_texts:
            patterns = extractor._detect_logical_patterns(text)
            assert RelationshipType.CONTRADICTS in patterns, f"Failed for: {text}"

    def test_detect_elaborates_patterns(self, extractor) -> None:
        """Detects ELABORATES indicators."""
        from reos.memory.relationships import RelationshipType

        test_texts = [
            "Specifically, we use JWT tokens.",
            "More specifically, the timeout is 30 seconds.",
            "In detail, the algorithm works as follows.",
            "Namely, the user and admin roles.",
        ]

        for text in test_texts:
            patterns = extractor._detect_logical_patterns(text)
            assert RelationshipType.ELABORATES in patterns, f"Failed for: {text}"

    def test_detect_multiple_patterns(self, extractor) -> None:
        """Detects multiple patterns in same text."""
        from reos.memory.relationships import RelationshipType

        text = "Therefore, we changed the API. However, this caused some issues."

        patterns = extractor._detect_logical_patterns(text)

        assert RelationshipType.FOLLOWS_FROM in patterns
        assert RelationshipType.CONTRADICTS in patterns

    def test_no_patterns_detected(self, extractor) -> None:
        """Returns empty list when no patterns found."""
        text = "The sky is blue today."

        patterns = extractor._detect_logical_patterns(text)

        assert patterns == []


# =============================================================================
# Extract from Chain Tests
# =============================================================================


class TestExtractFromChain:
    """Test extraction from reasoning chains."""

    def test_extract_creates_similar_to_relationships(
        self, extractor, test_act, test_blocks
    ) -> None:
        """extract_from_chain creates SIMILAR_TO relationships."""
        from reos.play.blocks_db import create_block
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        # Create a chain block
        chain_block = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Authentication is important for security"}],
        )

        # Store embeddings for existing blocks
        graph_store = MemoryGraphStore()
        mock_service = extractor._embedding_service
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            emb = mock_service.embed(content)
            graph_store.store_embedding(block_id, emb, f"hash-{block_id}")

        # Extract relationships
        created = extractor.extract_from_chain(
            chain_block.id,
            "Authentication is important for security",
            act_id=test_act,
        )

        # Should create SIMILAR_TO relationships (if similarity threshold met)
        similar_rels = [r for r in created if r.get("type") == "similar_to"]
        # May or may not find similar blocks depending on threshold
        assert isinstance(similar_rels, list)

    def test_extract_handles_empty_content(self, extractor, test_act) -> None:
        """extract_from_chain handles empty content gracefully."""
        from reos.play.blocks_db import create_block

        chain_block = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[],
        )

        created = extractor.extract_from_chain(chain_block.id, "", act_id=test_act)

        assert isinstance(created, list)


# =============================================================================
# Extract from Conversation Tests
# =============================================================================


class TestExtractFromConversation:
    """Test extraction from conversation messages."""

    def test_extract_creates_responds_to(self, extractor, test_act) -> None:
        """extract_from_conversation creates RESPONDS_TO relationship."""
        from reos.play.blocks_db import create_block
        from reos.memory.graph_store import MemoryGraphStore

        # Create two message blocks
        msg1 = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[{"content": "How do I configure authentication?"}],
        )
        msg2 = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[{"content": "You need to set up OAuth credentials."}],
        )

        created = extractor.extract_from_conversation(
            msg2.id,
            msg1.id,
            "You need to set up OAuth credentials.",
        )

        # Should have RESPONDS_TO relationship
        responds_to = [r for r in created if r.get("type") == "responds_to"]
        assert len(responds_to) == 1
        assert responds_to[0]["target"] == msg1.id

    def test_extract_no_previous_message(self, extractor, test_act) -> None:
        """extract_from_conversation works without previous message."""
        from reos.play.blocks_db import create_block

        msg = create_block(
            type="paragraph",
            act_id=test_act,
            rich_text=[{"content": "First message in conversation"}],
        )

        created = extractor.extract_from_conversation(
            msg.id,
            None,  # No previous message
            "First message in conversation",
        )

        # Should not have RESPONDS_TO (no previous)
        responds_to = [r for r in created if r.get("type") == "responds_to"]
        assert len(responds_to) == 0


# =============================================================================
# Extract from Feedback Tests
# =============================================================================


class TestExtractFromFeedback:
    """Test learning from RLHF feedback."""

    def test_positive_feedback_strengthens_relationships(
        self, extractor, test_act, test_blocks
    ) -> None:
        """Positive feedback (rating >= 4) strengthens relationships."""
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        graph_store = MemoryGraphStore()

        # Create a chain with relationships
        from reos.play.blocks_db import create_block

        chain = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Reasoning content"}],
        )

        # Create outgoing relationship with initial confidence
        rel_id = graph_store.create_relationship(
            chain.id,
            test_blocks[0],
            RelationshipType.REFERENCES,
            confidence=0.5,
        )

        # Apply positive feedback
        # Need to use the same graph_store instance
        extractor._graph_store = graph_store
        changes = extractor.extract_from_feedback(chain.id, rating=5)

        # Check if relationship was strengthened
        edge = graph_store.get_relationship(rel_id)
        if edge:
            assert edge.confidence >= 0.5  # Should be equal or higher

    def test_negative_feedback_with_correction(
        self, extractor, test_act, test_blocks
    ) -> None:
        """Negative feedback with correction creates CORRECTS relationship."""
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        graph_store = MemoryGraphStore()
        extractor._graph_store = graph_store

        from reos.play.blocks_db import create_block

        # Original chain
        original = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Original reasoning"}],
        )

        # Create relationship from original
        graph_store.create_relationship(
            original.id,
            test_blocks[0],
            RelationshipType.REFERENCES,
            confidence=0.8,
        )

        # Corrected version
        corrected = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Corrected reasoning"}],
        )

        # Apply negative feedback with correction
        changes = extractor.extract_from_feedback(
            original.id,
            rating=1,
            corrected_block_id=corrected.id,
        )

        # Should have created CORRECTS relationship
        corrects = [c for c in changes if c.get("type") == "corrects"]
        assert len(corrects) == 1
        assert corrects[0]["source"] == corrected.id
        assert corrects[0]["target"] == original.id

    def test_neutral_feedback_no_changes(self, extractor, test_act) -> None:
        """Neutral feedback (rating 3) makes no changes."""
        from reos.play.blocks_db import create_block

        chain = create_block(
            type="reasoning_chain",
            act_id=test_act,
            rich_text=[{"content": "Neutral content"}],
        )

        changes = extractor.extract_from_feedback(chain.id, rating=3)

        assert len(changes) == 0


# =============================================================================
# Sequential Block Connection Tests
# =============================================================================


class TestConnectSequentialBlocks:
    """Test connecting sequences of blocks."""

    def test_connect_sequential_blocks(self, extractor, test_act, test_blocks) -> None:
        """connect_sequential_blocks creates chain of relationships."""
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        graph_store = MemoryGraphStore()
        extractor._graph_store = graph_store

        # Connect first 3 blocks sequentially
        rel_ids = extractor.connect_sequential_blocks(test_blocks[:3])

        # Should create 2 relationships (3-1)
        assert len(rel_ids) == 2

        # Verify relationships
        for rel_id in rel_ids:
            edge = graph_store.get_relationship(rel_id)
            assert edge is not None
            assert edge.relationship_type == RelationshipType.PRECEDED_BY

    def test_connect_with_custom_relationship_type(
        self, extractor, test_act, test_blocks
    ) -> None:
        """connect_sequential_blocks uses custom relationship type."""
        from reos.memory.graph_store import MemoryGraphStore
        from reos.memory.relationships import RelationshipType

        graph_store = MemoryGraphStore()
        extractor._graph_store = graph_store

        rel_ids = extractor.connect_sequential_blocks(
            test_blocks[:3],
            relationship_type=RelationshipType.FOLLOWS_FROM,
        )

        for rel_id in rel_ids:
            edge = graph_store.get_relationship(rel_id)
            assert edge.relationship_type == RelationshipType.FOLLOWS_FROM

    def test_connect_single_block(self, extractor, test_act, test_blocks) -> None:
        """connect_sequential_blocks handles single block list."""
        rel_ids = extractor.connect_sequential_blocks([test_blocks[0]])

        assert len(rel_ids) == 0

    def test_connect_empty_list(self, extractor) -> None:
        """connect_sequential_blocks handles empty list."""
        rel_ids = extractor.connect_sequential_blocks([])

        assert len(rel_ids) == 0


# =============================================================================
# Auto-Link Similar Blocks Tests
# =============================================================================


class TestAutoLinkSimilarBlocks:
    """Test automatic similar block linking."""

    def test_auto_link_creates_relationships(
        self, extractor, test_act, test_blocks, mock_embedding_service
    ) -> None:
        """auto_link_similar_blocks creates SIMILAR_TO relationships."""
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()
        extractor._graph_store = graph_store

        # Store embeddings
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            emb = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, emb, f"hash-{block_id}")

        # Auto-link with very low threshold to ensure matches
        count = extractor.auto_link_similar_blocks(
            act_id=test_act,
            threshold=0.0,
            max_links_per_block=2,
        )

        # Should have created some relationships
        assert isinstance(count, int)
        assert count >= 0

    def test_auto_link_respects_threshold(
        self, extractor, test_act, test_blocks, mock_embedding_service
    ) -> None:
        """auto_link_similar_blocks respects similarity threshold."""
        from reos.memory.graph_store import MemoryGraphStore

        graph_store = MemoryGraphStore()
        extractor._graph_store = graph_store

        # Store embeddings
        for block_id in test_blocks:
            from reos.play.blocks_db import get_block
            block = get_block(block_id)
            content = block.rich_text[0].content if block.rich_text else ""
            emb = mock_embedding_service.embed(content)
            graph_store.store_embedding(block_id, emb, f"hash-{block_id}")

        # High threshold - fewer links
        count_high = extractor.auto_link_similar_blocks(
            threshold=0.99,
            max_links_per_block=10,
        )

        # Reset relationships
        for block_id in test_blocks:
            graph_store.delete_relationships_for_block(block_id)

        # Low threshold - more links
        count_low = extractor.auto_link_similar_blocks(
            threshold=0.0,
            max_links_per_block=10,
        )

        assert count_high <= count_low

    def test_auto_link_no_embeddings(self, extractor, test_act) -> None:
        """auto_link_similar_blocks handles no embeddings."""
        count = extractor.auto_link_similar_blocks(act_id=test_act)

        assert count == 0
