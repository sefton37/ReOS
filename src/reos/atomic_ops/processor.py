"""Atomic Operations Processor - The main pipeline.

This module orchestrates the full atomic operations pipeline:
1. Feature extraction from user requests
2. Classification into 3x2x3 taxonomy
3. Decomposition of complex requests (LLM-based)
4. Storage of operations for verification

This is the primary interface for agents (CAIRN, ReOS, RIVA) to
convert user requests into atomic operations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .classifier import AtomicClassifier, ClassificationConfig
from .decomposer import AtomicDecomposer, DecompositionResult
from .features import FeatureExtractor
from .models import AtomicOperation, OperationStatus
from .schema import AtomicOpsStore


class LLMProvider(Protocol):
    """Protocol for LLM providers."""
    def chat_json(self, system: str, user: str, temperature: float = 0.1, top_p: float = 0.9) -> str:
        ...


@dataclass
class ProcessingResult:
    """Result of processing a user request."""
    success: bool
    operations: list[AtomicOperation]
    primary_operation_id: str
    decomposed: bool
    message: str


class AtomicOpsProcessor:
    """Main processor for atomic operations.

    This is the primary entry point for processing user requests.
    It handles the full pipeline from request to stored operations.

    Usage:
        processor = AtomicOpsProcessor(db_connection)
        result = processor.process_request(
            request="show memory usage and save to log.txt",
            user_id="user-123",
            source_agent="cairn"
        )

        # Operations are now stored and ready for verification
        for op in result.operations:
            print(f"{op.id}: {op.classification}")
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        classifier_config: Optional[ClassificationConfig] = None,
        auto_init_embeddings: bool = True,
        llm: Optional[LLMProvider] = None,
    ):
        """Initialize the processor.

        Args:
            conn: SQLite database connection.
            classifier_config: Optional classifier configuration.
            auto_init_embeddings: Whether to auto-initialize sentence-transformers.
            llm: Optional LLM provider for semantic decomposition.
        """
        self.store = AtomicOpsStore(conn)
        self.llm = llm

        # Initialize feature extractor
        self.feature_extractor = FeatureExtractor()

        # Initialize classifier
        self.classifier = AtomicClassifier(
            config=classifier_config,
            feature_extractor=self.feature_extractor,
        )

        # Initialize decomposer with LLM for semantic decomposition
        self.decomposer = AtomicDecomposer(classifier=self.classifier, llm=llm)

        # Track embedding initialization status
        self._embeddings_initialized = False

        if auto_init_embeddings:
            self._init_embeddings()

    def _init_embeddings(self) -> bool:
        """Initialize sentence-transformers embeddings.

        Returns True if successful, False if sentence-transformers
        is not available or initialization failed.
        """
        try:
            if self.feature_extractor.load_embedding_model():
                self._embeddings_initialized = self.classifier.initialize_embeddings()
                return self._embeddings_initialized
        except Exception:
            pass
        return False

    @property
    def embeddings_available(self) -> bool:
        """Check if semantic embeddings are available."""
        return self._embeddings_initialized

    def process_request(
        self,
        request: str,
        user_id: str,
        source_agent: str,
        context: Optional[dict] = None,
        force_decomposition: bool = False,
    ) -> ProcessingResult:
        """Process a user request into atomic operations.

        This is the main entry point for the pipeline. It will:
        1. Extract features from the request
        2. Classify the request
        3. Decompose if needed
        4. Store all operations in the database

        Args:
            request: User's natural language request.
            user_id: User identifier.
            source_agent: Source agent (cairn, reos, riva).
            context: Optional context for classification.
            force_decomposition: Force decomposition even if not needed.

        Returns:
            ProcessingResult with all created operations.
        """
        if not request.strip():
            return ProcessingResult(
                success=False,
                operations=[],
                primary_operation_id="",
                decomposed=False,
                message="Empty request",
            )

        # Decompose (this handles both single and multi-operation cases)
        decomp_result = self.decomposer.decompose(
            request=request,
            user_id=user_id,
            source_agent=source_agent,
            force_decomposition=force_decomposition,
        )

        # Store all operations
        stored_operations = []
        for op in decomp_result.operations:
            # Extract features if not already done
            if op.features is None and not op.is_decomposed:
                features, embeddings = self.feature_extractor.extract(
                    op.user_request, context
                )
                op.features = features

                # Store operation
                self.store.create_operation(op)

                # Store features with embeddings
                self.store.store_features(
                    op.id,
                    features,
                    embeddings,
                )

                # Log classification
                if op.classification:
                    self.store.log_classification(op.id, op.classification)
            else:
                # Parent operation (decomposed)
                self.store.create_operation(op)

            stored_operations.append(op)

        # Determine primary operation ID
        primary_id = ""
        if stored_operations:
            if decomp_result.decomposed:
                # First operation is the parent
                primary_id = stored_operations[0].id
            else:
                primary_id = stored_operations[0].id

        return ProcessingResult(
            success=True,
            operations=stored_operations,
            primary_operation_id=primary_id,
            decomposed=decomp_result.decomposed,
            message=decomp_result.reasoning,
        )

    def get_operation(self, operation_id: str) -> Optional[AtomicOperation]:
        """Get an operation by ID.

        Args:
            operation_id: Operation identifier.

        Returns:
            AtomicOperation or None if not found.
        """
        return self.store.get_operation(operation_id)

    def get_pending_operations(self, user_id: str) -> list[AtomicOperation]:
        """Get all pending operations for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of operations awaiting verification or approval.
        """
        return self.store.get_operations_by_status(
            user_id,
            [OperationStatus.AWAITING_VERIFICATION, OperationStatus.AWAITING_APPROVAL]
        )

    def update_status(
        self,
        operation_id: str,
        status: OperationStatus,
    ) -> bool:
        """Update operation status.

        Args:
            operation_id: Operation identifier.
            status: New status.

        Returns:
            True if update successful.
        """
        try:
            self.store.update_operation_status(operation_id, status)
            return True
        except Exception:
            return False

    def get_similar_operations(
        self,
        request: str,
        user_id: str,
        limit: int = 5,
    ) -> list[tuple[AtomicOperation, float]]:
        """Find similar past operations using embeddings.

        This enables learning from past operations and user feedback.

        Args:
            request: Request to find similar operations for.
            user_id: User identifier (for user-specific similarity).
            limit: Maximum number of results.

        Returns:
            List of (operation, similarity_score) tuples.
        """
        if not self._embeddings_initialized:
            return []

        # Get embedding for request
        _, embedding = self.feature_extractor.extract(request)
        if embedding is None:
            return []

        # Query store for similar operations
        return self.store.find_similar_operations(
            embedding,
            user_id,
            limit,
        )

    def get_classification_stats(self, user_id: str) -> dict:
        """Get classification statistics for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dict with accuracy and distribution stats.
        """
        return self.store.get_classification_stats(user_id)


def create_processor(
    db_path: str = ":memory:",
    auto_init_embeddings: bool = True,
) -> AtomicOpsProcessor:
    """Create an AtomicOpsProcessor with a new database connection.

    Convenience function for creating a processor with defaults.

    Args:
        db_path: Path to SQLite database or ":memory:" for in-memory.
        auto_init_embeddings: Whether to auto-initialize embeddings.

    Returns:
        Configured AtomicOpsProcessor.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return AtomicOpsProcessor(
        conn=conn,
        auto_init_embeddings=auto_init_embeddings,
    )
