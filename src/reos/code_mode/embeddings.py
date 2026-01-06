"""Embeddings manager for semantic code search.

Uses Ollama's embedding models (nomic-embed-text) to create vector
representations of code symbols for similarity search.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from reos.settings import settings

if TYPE_CHECKING:
    from reos.code_mode.symbol_extractor import Symbol
    from reos.db import Database


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    symbol_id: int
    embedding: list[float]
    model: str


class EmbeddingError(RuntimeError):
    """Error during embedding generation."""

    pass


class EmbeddingManager:
    """Manage code embeddings for semantic search.

    Uses Ollama's embedding API to generate vector representations
    of code symbols, and stores them in SQLite for fast retrieval.
    """

    # Default embedding model
    DEFAULT_MODEL = "nomic-embed-text"

    def __init__(
        self,
        db: Database,
        model: str | None = None,
        ollama_url: str | None = None,
    ):
        """Initialize the embedding manager.

        Args:
            db: Database for storing embeddings
            model: Embedding model name (default: nomic-embed-text)
            ollama_url: Ollama API URL (default from settings)
        """
        self.db = db
        self.model = model or self.DEFAULT_MODEL
        self.ollama_url = (ollama_url or settings.ollama_url).rstrip("/")
        self._dimension: int | None = None

    def embed_text(self, text: str, timeout_seconds: float = 30.0) -> list[float]:
        """Generate embedding for a text string.

        Args:
            text: Text to embed
            timeout_seconds: Request timeout

        Returns:
            Embedding vector as list of floats

        Raises:
            EmbeddingError: If embedding generation fails
        """
        url = f"{self.ollama_url}/api/embed"
        payload = {
            "model": self.model,
            "input": text,
        }

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            raise EmbeddingError(f"Ollama embedding request failed: {e}") from e
        except httpx.RequestError as e:
            raise EmbeddingError(f"Failed to connect to Ollama: {e}") from e
        except json.JSONDecodeError as e:
            raise EmbeddingError(f"Invalid JSON response from Ollama: {e}") from e

        # Handle response format - Ollama returns embeddings in 'embeddings' array
        embeddings = data.get("embeddings")
        if embeddings and isinstance(embeddings, list) and len(embeddings) > 0:
            embedding = embeddings[0]
            if isinstance(embedding, list):
                self._dimension = len(embedding)
                return embedding

        # Fallback: check for 'embedding' key (older API format)
        embedding = data.get("embedding")
        if isinstance(embedding, list):
            self._dimension = len(embedding)
            return embedding

        raise EmbeddingError(f"Unexpected response format: {data}")

    def embed_symbol(
        self,
        symbol: Symbol,
        context: str = "",
        timeout_seconds: float = 30.0,
    ) -> list[float]:
        """Generate embedding for a code symbol.

        Prepares text representation of the symbol with context,
        then generates an embedding vector.

        Args:
            symbol: Symbol to embed
            context: Additional context (e.g., surrounding code)
            timeout_seconds: Request timeout

        Returns:
            Embedding vector
        """
        text = self._prepare_symbol_text(symbol, context)
        return self.embed_text(text, timeout_seconds)

    def _prepare_symbol_text(self, symbol: Symbol, context: str = "") -> str:
        """Prepare text representation of a symbol for embedding.

        Creates a rich text description that captures the symbol's
        semantics for better embedding quality.

        Args:
            symbol: Symbol to describe
            context: Additional context

        Returns:
            Text representation
        """
        parts = []

        # Add symbol type and name
        parts.append(f"{symbol.kind.value}: {symbol.qualified_name}")

        # Add signature if available
        if symbol.signature:
            parts.append(f"Signature: {symbol.signature}")

        # Add docstring if available
        if symbol.docstring:
            # Truncate long docstrings
            doc = symbol.docstring[:500]
            if len(symbol.docstring) > 500:
                doc += "..."
            parts.append(f"Description: {doc}")

        # Add decorators
        if symbol.decorators:
            parts.append(f"Decorators: {', '.join(symbol.decorators)}")

        # Add location info
        parts.append(f"File: {symbol.location.file_path}")

        # Add context if provided
        if context:
            parts.append(f"Context: {context[:200]}")

        return "\n".join(parts)

    def store_embedding(
        self,
        symbol_id: int,
        embedding: list[float],
    ) -> None:
        """Store an embedding in the database.

        Args:
            symbol_id: Database ID of the symbol
            embedding: Embedding vector to store
        """
        # Pack embedding as binary for efficient storage
        embedding_blob = self._pack_embedding(embedding)

        conn = self.db.connect()

        # Upsert: delete existing, then insert
        conn.execute(
            "DELETE FROM repo_embeddings WHERE symbol_id = ?",
            (symbol_id,),
        )
        conn.execute(
            """
            INSERT INTO repo_embeddings (symbol_id, embedding, model)
            VALUES (?, ?, ?)
            """,
            (symbol_id, embedding_blob, self.model),
        )
        conn.commit()

    def get_embedding(self, symbol_id: int) -> list[float] | None:
        """Retrieve an embedding from the database.

        Args:
            symbol_id: Database ID of the symbol

        Returns:
            Embedding vector or None if not found
        """
        conn = self.db.connect()
        row = conn.execute(
            "SELECT embedding FROM repo_embeddings WHERE symbol_id = ?",
            (symbol_id,),
        ).fetchone()

        if row is None:
            return None

        blob = row["embedding"] if hasattr(row, "__getitem__") else row[0]
        return self._unpack_embedding(blob)

    def similarity_search(
        self,
        query_embedding: list[float],
        repo_path: str,
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """Find symbols most similar to a query embedding.

        Uses cosine similarity to rank symbols.

        Args:
            query_embedding: Query vector
            repo_path: Repository path to search within
            top_k: Number of results to return

        Returns:
            List of (symbol_id, similarity_score) tuples
        """
        conn = self.db.connect()

        # Get all embeddings for this repo
        rows = conn.execute(
            """
            SELECT e.symbol_id, e.embedding
            FROM repo_embeddings e
            JOIN repo_symbols s ON e.symbol_id = s.id
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ?
            """,
            (repo_path,),
        ).fetchall()

        if not rows:
            return []

        # Compute similarities
        results: list[tuple[int, float]] = []
        for row in rows:
            symbol_id = row["symbol_id"] if hasattr(row, "__getitem__") else row[0]
            blob = row["embedding"] if hasattr(row, "__getitem__") else row[1]
            embedding = self._unpack_embedding(blob)

            similarity = self._cosine_similarity(query_embedding, embedding)
            results.append((symbol_id, similarity))

        # Sort by similarity (descending) and return top_k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def semantic_search(
        self,
        query: str,
        repo_path: str,
        top_k: int = 10,
        timeout_seconds: float = 30.0,
    ) -> list[tuple[int, float]]:
        """Search for symbols semantically similar to a query.

        Generates an embedding for the query, then finds similar symbols.

        Args:
            query: Natural language query
            repo_path: Repository path to search within
            top_k: Number of results to return
            timeout_seconds: Embedding request timeout

        Returns:
            List of (symbol_id, similarity_score) tuples
        """
        query_embedding = self.embed_text(query, timeout_seconds)
        return self.similarity_search(query_embedding, repo_path, top_k)

    def _pack_embedding(self, embedding: list[float]) -> bytes:
        """Pack embedding as binary blob.

        Uses single-precision floats for space efficiency.

        Args:
            embedding: Embedding vector

        Returns:
            Binary blob
        """
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _unpack_embedding(self, blob: bytes) -> list[float]:
        """Unpack embedding from binary blob.

        Args:
            blob: Binary embedding data

        Returns:
            Embedding vector
        """
        count = len(blob) // 4  # 4 bytes per float
        return list(struct.unpack(f"{count}f", blob))

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Similarity score in [-1, 1]
        """
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def has_embeddings(self, repo_path: str) -> bool:
        """Check if a repository has any embeddings.

        Args:
            repo_path: Repository path

        Returns:
            True if embeddings exist
        """
        conn = self.db.connect()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM repo_embeddings e
            JOIN repo_symbols s ON e.symbol_id = s.id
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ?
            """,
            (repo_path,),
        ).fetchone()

        count = row[0] if row else 0
        return count > 0

    def get_embedding_count(self, repo_path: str) -> int:
        """Get count of embeddings for a repository.

        Args:
            repo_path: Repository path

        Returns:
            Number of embeddings
        """
        conn = self.db.connect()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM repo_embeddings e
            JOIN repo_symbols s ON e.symbol_id = s.id
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ?
            """,
            (repo_path,),
        ).fetchone()

        return row[0] if row else 0
