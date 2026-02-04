"""Embedding service for semantic search.

Provides vector embeddings using sentence-transformers for:
- Semantic similarity search
- Block content representation
- Query embedding for retrieval

Uses all-MiniLM-L6-v2 by default (384 dimensions, fast, good quality).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# Singleton instance
_embedding_service: "EmbeddingService | None" = None
_service_lock = threading.Lock()


class EmbeddingService:
    """Singleton embedding service using sentence-transformers.

    Thread-safe singleton that lazily loads the model on first use.
    Provides embedding generation and similarity computation.

    Embedding Format:
    - Model: all-MiniLM-L6-v2 (default)
    - Dimensions: 384
    - Storage: float32 bytes (1536 bytes per embedding)
    """

    _instance: "EmbeddingService | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "EmbeddingService":
        """Ensure singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize the embedding service (idempotent)."""
        if getattr(self, "_initialized", False):
            return

        self._model = None
        self._model_name = "all-MiniLM-L6-v2"
        self._model_lock = threading.Lock()
        self._initialized = True

    def _ensure_model_loaded(self) -> bool:
        """Lazily load the embedding model.

        Returns:
            True if model is available, False if loading failed.
        """
        if self._model is not None:
            return True

        with self._model_lock:
            if self._model is not None:
                return True

            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading embedding model: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                logger.info("Embedding model loaded successfully")
                return True
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
                return False
            except Exception as e:
                logger.error("Failed to load embedding model: %s", e)
                return False

    @property
    def is_available(self) -> bool:
        """Check if the embedding service is available."""
        return self._ensure_model_loaded()

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model_name

    @property
    def embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return 384  # all-MiniLM-L6-v2 produces 384-dimensional embeddings

    def embed(self, text: str) -> bytes | None:
        """Generate embedding for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding as bytes (float32), or None if service unavailable.
        """
        if not self._ensure_model_loaded():
            return None

        import numpy as np

        try:
            # Truncate very long texts
            if len(text) > 10000:
                text = text[:10000]

            embedding = self._model.encode(text, convert_to_numpy=True)
            return embedding.astype(np.float32).tobytes()
        except Exception as e:
            logger.error(
                "Failed to generate embedding: %s (text_length=%d, text_preview=%s)",
                e,
                len(text),
                text[:50] + "..." if len(text) > 50 else text,
            )
            return None

    def embed_batch(self, texts: list[str]) -> list[bytes | None]:
        """Batch embed multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embeddings as bytes, None for failed embeddings.
        """
        if not texts:
            return []

        if not self._ensure_model_loaded():
            return [None] * len(texts)

        import numpy as np

        try:
            # Truncate very long texts
            truncated = [t[:10000] if len(t) > 10000 else t for t in texts]

            embeddings = self._model.encode(truncated, convert_to_numpy=True)
            return [emb.astype(np.float32).tobytes() for emb in embeddings]
        except Exception as e:
            logger.error(
                "Failed to generate batch embeddings: %s (batch_size=%d)",
                e,
                len(texts),
            )
            return [None] * len(texts)

    def similarity(self, a: bytes, b: bytes) -> float:
        """Compute cosine similarity between two embeddings.

        Args:
            a: First embedding as bytes.
            b: Second embedding as bytes.

        Returns:
            Cosine similarity (-1 to 1), 0 if invalid.
        """
        import numpy as np

        try:
            vec_a = np.frombuffer(a, dtype=np.float32)
            vec_b = np.frombuffer(b, dtype=np.float32)

            if len(vec_a) != len(vec_b):
                return 0.0

            dot = np.dot(vec_a, vec_b)
            norm_a = np.linalg.norm(vec_a)
            norm_b = np.linalg.norm(vec_b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot / (norm_a * norm_b))
        except Exception as e:
            logger.warning(
                "Failed to compute similarity: %s (embedding sizes: %d, %d)",
                e,
                len(a),
                len(b),
            )
            return 0.0

    def find_similar(
        self,
        query_embedding: bytes,
        candidate_embeddings: list[tuple[str, bytes]],
        threshold: float = 0.5,
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Find similar embeddings from candidates.

        Args:
            query_embedding: The query embedding.
            candidate_embeddings: List of (id, embedding) tuples.
            threshold: Minimum similarity threshold.
            top_k: Maximum number of results.

        Returns:
            List of (id, similarity) tuples, sorted by similarity descending.
        """
        import numpy as np

        try:
            query_vec = np.frombuffer(query_embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)

            if query_norm == 0:
                return []

            results = []
            for block_id, emb_bytes in candidate_embeddings:
                cand_vec = np.frombuffer(emb_bytes, dtype=np.float32)
                cand_norm = np.linalg.norm(cand_vec)

                if cand_norm == 0:
                    continue

                sim = float(np.dot(query_vec, cand_vec) / (query_norm * cand_norm))
                if sim >= threshold:
                    results.append((block_id, sim))

            # Sort by similarity descending
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.warning(
                "Failed to find similar embeddings: %s (candidates=%d, top_k=%d)",
                e,
                len(candidate_embeddings),
                top_k,
            )
            return []


def get_embedding_service() -> EmbeddingService:
    """Get the singleton embedding service instance.

    Returns:
        The global EmbeddingService instance.
    """
    global _embedding_service
    if _embedding_service is None:
        with _service_lock:
            if _embedding_service is None:
                _embedding_service = EmbeddingService()
    return _embedding_service


def content_hash(text: str) -> str:
    """Generate a hash of text content for staleness detection.

    Args:
        text: Text content to hash.

    Returns:
        SHA-256 hash prefix (16 characters).
    """
    normalized = text.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def embedding_to_array(embedding_bytes: bytes) -> list[float]:
    """Convert embedding bytes to float array.

    Args:
        embedding_bytes: Embedding as bytes.

    Returns:
        List of float values.
    """
    import numpy as np

    return np.frombuffer(embedding_bytes, dtype=np.float32).tolist()


def array_to_embedding(embedding_array: list[float]) -> bytes:
    """Convert float array to embedding bytes.

    Args:
        embedding_array: List of float values.

    Returns:
        Embedding as bytes.
    """
    import numpy as np

    return np.array(embedding_array, dtype=np.float32).tobytes()
