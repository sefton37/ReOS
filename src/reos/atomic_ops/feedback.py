"""Feedback collection for classification learning.

Collects two types of feedback:
- Approval: user accepted the classification and result
- Correction: user corrected the classification

Corrections are fed back to the LLM classifier as few-shot examples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

from .models import (
    AtomicOperation,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
    FeedbackType,
    UserFeedback,
)
from .schema import AtomicOpsStore


@dataclass
class FeedbackSession:
    """Tracks a feedback collection session for an operation."""
    operation_id: str
    user_id: str
    started_at: datetime = field(default_factory=datetime.now)
    approval_presented_at: Optional[datetime] = None
    approval_decided_at: Optional[datetime] = None


class FeedbackCollector:
    """Collects approval and correction feedback.

    Feedback is stored in the database and used by the classifier
    for few-shot learning from past corrections.
    """

    def __init__(self, store: Optional[AtomicOpsStore] = None):
        self.store = store
        self._sessions: dict[str, FeedbackSession] = {}

    def start_session(self, operation: AtomicOperation) -> FeedbackSession:
        """Start a feedback session for an operation."""
        session = FeedbackSession(
            operation_id=operation.id,
            user_id=operation.user_id,
        )
        self._sessions[operation.id] = session
        return session

    def get_session(self, operation_id: str) -> Optional[FeedbackSession]:
        """Get active session for an operation."""
        return self._sessions.get(operation_id)

    def end_session(self, operation_id: str) -> Optional[FeedbackSession]:
        """End and return a feedback session."""
        return self._sessions.pop(operation_id, None)

    def present_for_approval(self, operation_id: str):
        """Mark when operation is presented for approval."""
        session = self._sessions.get(operation_id)
        if session:
            session.approval_presented_at = datetime.now()

    def collect_approval(
        self,
        operation: AtomicOperation,
        approved: bool,
        modified: bool = False,
    ) -> UserFeedback:
        """Collect approval feedback when user accepts/rejects operation."""
        session = self._sessions.get(operation.id)
        time_to_decision = None

        if session and session.approval_presented_at:
            session.approval_decided_at = datetime.now()
            delta = session.approval_decided_at - session.approval_presented_at
            time_to_decision = int(delta.total_seconds() * 1000)

        feedback_type = FeedbackType.APPROVAL if approved else FeedbackType.REJECTION

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=feedback_type,
            approved=approved,
            time_to_decision_ms=time_to_decision,
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback

    def collect_correction(
        self,
        operation: AtomicOperation,
        corrected_destination: Optional[DestinationType] = None,
        corrected_consumer: Optional[ConsumerType] = None,
        corrected_semantics: Optional[ExecutionSemantics] = None,
        reasoning: Optional[str] = None,
    ) -> UserFeedback:
        """Collect correction feedback when user fixes classification."""
        system_class = None
        if operation.classification:
            system_class = {
                "destination": operation.classification.destination.value,
                "consumer": operation.classification.consumer.value,
                "semantics": operation.classification.semantics.value,
                "confident": operation.classification.confident,
            }

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.CORRECTION,
            system_classification=system_class,
            user_corrected_destination=corrected_destination.value if corrected_destination else None,
            user_corrected_consumer=corrected_consumer.value if corrected_consumer else None,
            user_corrected_semantics=corrected_semantics.value if corrected_semantics else None,
            correction_reasoning=reasoning,
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback


class LearningAggregator:
    """Aggregates feedback for classification improvement.

    Provides corrections as few-shot examples for the LLM classifier
    and computes simple accuracy metrics.
    """

    def __init__(self, store: AtomicOpsStore):
        self.store = store

    def get_recent_corrections(
        self,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get recent corrections for few-shot classifier context."""
        return self.store.get_recent_corrections(user_id=user_id, limit=limit)

    def compute_metrics(self, user_id: str) -> dict:
        """Compute simple classification metrics for a user."""
        return self.store.get_classification_stats(user_id)


def create_feedback_collector(
    store: Optional[AtomicOpsStore] = None,
) -> FeedbackCollector:
    """Create a feedback collector."""
    return FeedbackCollector(store=store)


def create_learning_aggregator(store: AtomicOpsStore) -> LearningAggregator:
    """Create a learning aggregator."""
    return LearningAggregator(store=store)
