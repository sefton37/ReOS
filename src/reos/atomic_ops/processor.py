"""Atomic Operations Processor - The main pipeline.

This module orchestrates the full atomic operations pipeline:
1. Classification into 3x2x3 taxonomy (LLM-native)
2. Decomposition of complex requests (LLM-based)
3. Storage of operations for verification

This is the primary interface for agents (CAIRN, ReOS, RIVA) to
convert user requests into atomic operations.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

from .classifier import AtomicClassifier
from .decomposer import AtomicDecomposer, DecompositionResult
from .models import AtomicOperation, OperationStatus
from .schema import AtomicOpsStore


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    def chat_json(
        self, system: str, user: str, temperature: float = 0.1, top_p: float = 0.9
    ) -> str: ...


@dataclass
class ProcessingResult:
    """Result of processing a user request."""

    success: bool
    operations: list[AtomicOperation]
    primary_operation_id: str
    decomposed: bool
    message: str
    # Clarification fields from decomposition (avoids redundant decompose call)
    needs_clarification: bool = False
    clarification_prompt: str | None = None


class AtomicOpsProcessor:
    """Main processor for atomic operations.

    This is the primary entry point for processing user requests.
    It handles the full pipeline from request to stored operations.

    Usage:
        processor = AtomicOpsProcessor(db_connection, llm=llm_provider)
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
        llm: Optional[LLMProvider] = None,
    ):
        """Initialize the processor.

        Args:
            conn: SQLite database connection.
            llm: Optional LLM provider for classification and decomposition.
        """
        self.store = AtomicOpsStore(conn)
        self.llm = llm

        # Initialize LLM-native classifier
        self.classifier = AtomicClassifier(llm=llm)

        # Initialize decomposer with LLM for semantic decomposition
        self.decomposer = AtomicDecomposer(classifier=self.classifier, llm=llm)

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
        1. Classify the request (LLM-native)
        2. Decompose if needed
        3. Store all operations in the database

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

        # Get recent corrections for few-shot context
        corrections = self.store.get_recent_corrections(user_id=user_id, limit=5)

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
            if not op.is_decomposed:
                # Re-classify with corrections context if we have corrections
                if corrections and op.classification:
                    result = self.classifier.classify(op.user_request, corrections=corrections)
                    op.classification = result.classification

                # Store operation
                self.store.create_operation(op)

                # Log classification
                if op.classification:
                    model = ""
                    if hasattr(self.classifier, "llm") and self.classifier.llm:
                        if hasattr(self.classifier.llm, "current_model"):
                            model = self.classifier.llm.current_model or ""
                    self.store.log_classification(op.id, op.classification, model=model)
            else:
                # Parent operation (decomposed)
                self.store.create_operation(op)

            stored_operations.append(op)

        # Determine primary operation ID
        primary_id = ""
        if stored_operations:
            primary_id = stored_operations[0].id

        return ProcessingResult(
            success=True,
            operations=stored_operations,
            primary_operation_id=primary_id,
            decomposed=decomp_result.decomposed,
            message=decomp_result.reasoning,
            needs_clarification=decomp_result.needs_clarification,
            clarification_prompt=decomp_result.clarification_prompt,
        )

    def get_operation(self, operation_id: str) -> Optional[AtomicOperation]:
        """Get an operation by ID."""
        return self.store.get_operation(operation_id)

    def get_pending_operations(self, user_id: str) -> list[AtomicOperation]:
        """Get all pending operations for a user."""
        return self.store.get_operations_by_status(
            user_id, [OperationStatus.AWAITING_VERIFICATION, OperationStatus.AWAITING_APPROVAL]
        )

    def update_status(
        self,
        operation_id: str,
        status: OperationStatus,
    ) -> bool:
        """Update operation status."""
        try:
            self.store.update_operation_status(operation_id, status)
            return True
        except Exception as e:
            logger.warning(
                "Failed to update operation %s status to %s: %s", operation_id, status, e
            )
            return False

    def get_classification_stats(self, user_id: str) -> dict:
        """Get classification statistics for a user."""
        return self.store.get_classification_stats(user_id)


def create_processor(
    db_path: str = ":memory:",
    llm: Any = None,
) -> AtomicOpsProcessor:
    """Create an AtomicOpsProcessor with a new database connection.

    Args:
        db_path: Path to SQLite database or ":memory:" for in-memory.
        llm: Optional LLM provider for classification.

    Returns:
        Configured AtomicOpsProcessor.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return AtomicOpsProcessor(conn=conn, llm=llm)
