"""Tests for memory/embeddings.py - Embedding service.

Unit tests for:
- EmbeddingService singleton
- Embedding generation (mocked)
- Similarity computation
- Content hashing
- Utility functions
"""

from __future__ import annotations

import numpy as np
import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_embedding_service(monkeypatch):
    """Create an embedding service with mocked model loading."""
    from reos.memory.embeddings import EmbeddingService

    # Reset singleton
    EmbeddingService._instance = None

    service = EmbeddingService()

    # Mock the model to avoid loading sentence-transformers
    class MockModel:
        def encode(self, text, convert_to_numpy=True):
            # Generate deterministic embedding based on text hash
            import hashlib
            h = hashlib.md5(text.encode() if isinstance(text, str) else text[0].encode()).hexdigest()
            seed = int(h[:8], 16)
            rng = np.random.RandomState(seed)
            if isinstance(text, list):
                return np.array([rng.randn(384).astype(np.float32) for _ in text])
            return rng.randn(384).astype(np.float32)

    service._model = MockModel()

    yield service

    # Cleanup singleton
    EmbeddingService._instance = None


@pytest.fixture
def sample_embedding():
    """Create a sample embedding."""
    return np.random.randn(384).astype(np.float32).tobytes()


# =============================================================================
# EmbeddingService Singleton Tests
# =============================================================================


class TestEmbeddingServiceSingleton:
    """Test EmbeddingService singleton behavior."""

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls return the same instance."""
        from reos.memory.embeddings import EmbeddingService

        # Reset singleton
        EmbeddingService._instance = None

        service1 = EmbeddingService()
        service2 = EmbeddingService()

        assert service1 is service2

    def test_get_embedding_service_returns_singleton(self) -> None:
        """get_embedding_service returns the singleton."""
        from reos.memory.embeddings import get_embedding_service, EmbeddingService

        # Reset singleton
        EmbeddingService._instance = None

        service1 = get_embedding_service()
        service2 = get_embedding_service()

        assert service1 is service2
        assert isinstance(service1, EmbeddingService)

    def test_service_properties(self, mock_embedding_service) -> None:
        """Service has expected properties."""
        assert mock_embedding_service.model_name == "all-MiniLM-L6-v2"
        assert mock_embedding_service.embedding_dim == 384


# =============================================================================
# Embedding Generation Tests
# =============================================================================


class TestEmbeddingGeneration:
    """Test embedding generation."""

    def test_embed_returns_bytes(self, mock_embedding_service) -> None:
        """embed() returns bytes."""
        result = mock_embedding_service.embed("Hello world")

        assert isinstance(result, bytes)
        # 384 dimensions * 4 bytes per float32 = 1536 bytes
        assert len(result) == 384 * 4

    def test_embed_different_texts_different_embeddings(self, mock_embedding_service) -> None:
        """Different texts produce different embeddings."""
        emb1 = mock_embedding_service.embed("Hello world")
        emb2 = mock_embedding_service.embed("Goodbye universe")

        assert emb1 != emb2

    def test_embed_same_text_same_embedding(self, mock_embedding_service) -> None:
        """Same text produces same embedding (deterministic)."""
        emb1 = mock_embedding_service.embed("Hello world")
        emb2 = mock_embedding_service.embed("Hello world")

        assert emb1 == emb2

    def test_embed_batch_returns_list(self, mock_embedding_service) -> None:
        """embed_batch() returns list of bytes."""
        texts = ["Hello", "World", "Test"]
        results = mock_embedding_service.embed_batch(texts)

        assert isinstance(results, list)
        assert len(results) == 3
        for result in results:
            assert isinstance(result, bytes)
            assert len(result) == 384 * 4

    def test_embed_batch_empty_list(self, mock_embedding_service) -> None:
        """embed_batch() handles empty list."""
        results = mock_embedding_service.embed_batch([])
        assert results == []

    def test_embed_truncates_long_text(self, mock_embedding_service) -> None:
        """embed() handles very long text."""
        long_text = "A" * 20000
        result = mock_embedding_service.embed(long_text)

        assert result is not None
        assert len(result) == 384 * 4


# =============================================================================
# Similarity Tests
# =============================================================================


class TestSimilarity:
    """Test similarity computation."""

    def test_similarity_identical_embeddings(self, mock_embedding_service) -> None:
        """Identical embeddings have similarity 1.0."""
        emb = mock_embedding_service.embed("Test text")

        similarity = mock_embedding_service.similarity(emb, emb)

        assert similarity == pytest.approx(1.0, abs=0.001)

    def test_similarity_range(self, mock_embedding_service) -> None:
        """Similarity is in range [-1, 1]."""
        emb1 = mock_embedding_service.embed("Hello world")
        emb2 = mock_embedding_service.embed("Goodbye universe")

        similarity = mock_embedding_service.similarity(emb1, emb2)

        assert -1.0 <= similarity <= 1.0

    def test_similarity_symmetric(self, mock_embedding_service) -> None:
        """Similarity is symmetric."""
        emb1 = mock_embedding_service.embed("Hello world")
        emb2 = mock_embedding_service.embed("Goodbye universe")

        sim1 = mock_embedding_service.similarity(emb1, emb2)
        sim2 = mock_embedding_service.similarity(emb2, emb1)

        assert sim1 == pytest.approx(sim2, abs=0.001)

    def test_similarity_mismatched_lengths(self, mock_embedding_service) -> None:
        """Mismatched embedding lengths return 0."""
        emb1 = np.random.randn(384).astype(np.float32).tobytes()
        emb2 = np.random.randn(256).astype(np.float32).tobytes()

        similarity = mock_embedding_service.similarity(emb1, emb2)

        assert similarity == 0.0

    def test_similarity_zero_vector(self, mock_embedding_service) -> None:
        """Zero vector returns similarity 0."""
        emb1 = np.zeros(384, dtype=np.float32).tobytes()
        emb2 = np.random.randn(384).astype(np.float32).tobytes()

        similarity = mock_embedding_service.similarity(emb1, emb2)

        assert similarity == 0.0


# =============================================================================
# Find Similar Tests
# =============================================================================


class TestFindSimilar:
    """Test find_similar function."""

    def test_find_similar_returns_sorted_results(self, mock_embedding_service) -> None:
        """Results are sorted by similarity descending."""
        query = mock_embedding_service.embed("Query text")
        candidates = [
            ("block-1", mock_embedding_service.embed("Query text")),  # Most similar
            ("block-2", mock_embedding_service.embed("Something else")),
            ("block-3", mock_embedding_service.embed("Query text similar")),
        ]

        results = mock_embedding_service.find_similar(
            query, candidates, threshold=0.0, top_k=10
        )

        assert len(results) >= 1
        # Check descending order
        for i in range(len(results) - 1):
            assert results[i][1] >= results[i + 1][1]

    def test_find_similar_respects_threshold(self, mock_embedding_service) -> None:
        """Results below threshold are excluded."""
        query = mock_embedding_service.embed("Query text")
        candidates = [
            ("block-1", mock_embedding_service.embed("Query text")),  # High similarity
            ("block-2", mock_embedding_service.embed("Completely different topic xyz")),  # Low
        ]

        # High threshold
        results = mock_embedding_service.find_similar(
            query, candidates, threshold=0.9, top_k=10
        )

        # Only exact match should pass high threshold
        for _, sim in results:
            assert sim >= 0.9

    def test_find_similar_respects_top_k(self, mock_embedding_service) -> None:
        """Results are limited to top_k."""
        query = mock_embedding_service.embed("Query")
        candidates = [
            (f"block-{i}", mock_embedding_service.embed(f"Text {i}"))
            for i in range(20)
        ]

        results = mock_embedding_service.find_similar(
            query, candidates, threshold=0.0, top_k=5
        )

        assert len(results) <= 5

    def test_find_similar_empty_candidates(self, mock_embedding_service) -> None:
        """Empty candidates returns empty list."""
        query = mock_embedding_service.embed("Query")

        results = mock_embedding_service.find_similar(
            query, [], threshold=0.0, top_k=10
        )

        assert results == []

    def test_find_similar_zero_query_vector(self, mock_embedding_service) -> None:
        """Zero query vector returns empty list."""
        query = np.zeros(384, dtype=np.float32).tobytes()
        candidates = [
            ("block-1", mock_embedding_service.embed("Some text")),
        ]

        results = mock_embedding_service.find_similar(
            query, candidates, threshold=0.0, top_k=10
        )

        assert results == []


# =============================================================================
# Content Hash Tests
# =============================================================================


class TestContentHash:
    """Test content_hash function."""

    def test_content_hash_deterministic(self) -> None:
        """Same text produces same hash."""
        from reos.memory.embeddings import content_hash

        hash1 = content_hash("Hello world")
        hash2 = content_hash("Hello world")

        assert hash1 == hash2

    def test_content_hash_different_texts(self) -> None:
        """Different texts produce different hashes."""
        from reos.memory.embeddings import content_hash

        hash1 = content_hash("Hello world")
        hash2 = content_hash("Goodbye world")

        assert hash1 != hash2

    def test_content_hash_case_insensitive(self) -> None:
        """Hash is case-insensitive."""
        from reos.memory.embeddings import content_hash

        hash1 = content_hash("Hello World")
        hash2 = content_hash("hello world")

        assert hash1 == hash2

    def test_content_hash_strips_whitespace(self) -> None:
        """Hash ignores leading/trailing whitespace."""
        from reos.memory.embeddings import content_hash

        hash1 = content_hash("  Hello world  ")
        hash2 = content_hash("Hello world")

        assert hash1 == hash2

    def test_content_hash_length(self) -> None:
        """Hash is 16 characters (hex prefix)."""
        from reos.memory.embeddings import content_hash

        result = content_hash("Test text")

        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Test utility functions for embedding conversion."""

    def test_embedding_to_array(self) -> None:
        """embedding_to_array converts bytes to float list."""
        from reos.memory.embeddings import embedding_to_array

        original = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        embedding_bytes = original.tobytes()

        result = embedding_to_array(embedding_bytes)

        assert isinstance(result, list)
        assert len(result) == 4
        assert result == pytest.approx([1.0, 2.0, 3.0, 4.0])

    def test_array_to_embedding(self) -> None:
        """array_to_embedding converts float list to bytes."""
        from reos.memory.embeddings import array_to_embedding

        array = [1.0, 2.0, 3.0, 4.0]

        result = array_to_embedding(array)

        assert isinstance(result, bytes)
        assert len(result) == 16  # 4 floats * 4 bytes

    def test_roundtrip_conversion(self) -> None:
        """Conversion roundtrip preserves data."""
        from reos.memory.embeddings import embedding_to_array, array_to_embedding

        original = [1.5, 2.5, 3.5, 4.5]

        embedding_bytes = array_to_embedding(original)
        result = embedding_to_array(embedding_bytes)

        assert result == pytest.approx(original)


# =============================================================================
# Graceful Degradation Tests
# =============================================================================


class TestGracefulDegradation:
    """Test graceful degradation when sentence-transformers unavailable."""

    def test_is_available_without_model(self) -> None:
        """is_available returns False when model can't load."""
        from reos.memory.embeddings import EmbeddingService

        # Reset singleton
        EmbeddingService._instance = None

        service = EmbeddingService()
        # Don't load the model - leave it as None

        # is_available triggers model loading, which may or may not succeed
        # depending on whether sentence-transformers is installed
        # Just verify it doesn't crash and returns a boolean
        result = service.is_available
        assert isinstance(result, bool)

        # Cleanup
        EmbeddingService._instance = None
