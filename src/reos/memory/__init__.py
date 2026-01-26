"""Hybrid Vector-Graph Memory System for Talking Rock.

This module provides relational memory capabilities through:
- Typed relationships between blocks (graph edges)
- Vector embeddings for semantic search
- Three-stage retrieval (semantic → graph → rank)
- Automatic relationship extraction from reasoning chains

Philosophy: "Memory is not just storage—it's relationships. Understanding
how ideas connect is how Talking Rock becomes truly personal."
"""

from __future__ import annotations

from .relationships import RelationshipType, RelationshipSource
from .embeddings import EmbeddingService, get_embedding_service
from .graph_store import MemoryGraphStore, GraphEdge, TraversalResult
from .retriever import MemoryRetriever, MemoryContext

__all__ = [
    # Relationship types
    "RelationshipType",
    "RelationshipSource",
    # Embedding service
    "EmbeddingService",
    "get_embedding_service",
    # Graph store
    "MemoryGraphStore",
    "GraphEdge",
    "TraversalResult",
    # Retriever
    "MemoryRetriever",
    "MemoryContext",
]
