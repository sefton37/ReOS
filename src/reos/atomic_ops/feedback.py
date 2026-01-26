"""RLHF feedback collection system.

This module implements multi-signal feedback collection for learning:
- Explicit ratings (1-5 stars)
- Corrections (user fixes classification)
- Approval signals (accepted/modified/rejected)
- Behavioral signals (retry, undo, abandon)
- Long-term outcomes (persisted, reused, referenced)

Feedback is used to improve classification accuracy over time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from .models import (
    AtomicOperation,
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
    FeedbackType,
    LearningMetrics,
    UserFeedback,
)
from .schema import AtomicOpsStore


@dataclass
class FeedbackSession:
    """Tracks a feedback collection session for an operation."""
    operation_id: str
    user_id: str
    started_at: datetime = field(default_factory=datetime.now)

    # Timing for behavioral signals
    approval_presented_at: Optional[datetime] = None
    approval_decided_at: Optional[datetime] = None
    execution_completed_at: Optional[datetime] = None

    # Behavioral tracking
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    undone: bool = False
    undo_at: Optional[datetime] = None
    abandoned: bool = False


class FeedbackCollector:
    """Collects multi-signal feedback for RLHF.

    The collector tracks various signals throughout an operation's
    lifecycle and aggregates them into feedback records for learning.
    """

    def __init__(self, store: Optional[AtomicOpsStore] = None):
        """Initialize feedback collector.

        Args:
            store: Optional store for persisting feedback.
        """
        self.store = store
        self._sessions: dict[str, FeedbackSession] = {}

    def start_session(self, operation: AtomicOperation) -> FeedbackSession:
        """Start a feedback session for an operation.

        Call this when an operation is presented to the user.
        """
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

    # =========================================================================
    # EXPLICIT RATING FEEDBACK
    # =========================================================================

    def collect_rating(
        self,
        operation: AtomicOperation,
        rating: int,
        comment: Optional[str] = None,
        dimensions: Optional[dict[str, int]] = None,
    ) -> UserFeedback:
        """Collect explicit rating feedback (1-5 stars).

        Args:
            operation: The operation being rated.
            rating: Overall rating 1-5.
            comment: Optional user comment.
            dimensions: Optional ratings for specific dimensions
                       (accuracy, helpfulness, safety, etc.)

        Returns:
            UserFeedback record.
        """
        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.EXPLICIT_RATING,
            rating=max(1, min(5, rating)),
            rating_dimensions=dimensions or {},
            comment=comment,
            feedback_confidence=0.9,  # Explicit ratings are high confidence
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback

    # =========================================================================
    # CORRECTION FEEDBACK
    # =========================================================================

    def collect_correction(
        self,
        operation: AtomicOperation,
        corrected_destination: Optional[DestinationType] = None,
        corrected_consumer: Optional[ConsumerType] = None,
        corrected_semantics: Optional[ExecutionSemantics] = None,
        reasoning: Optional[str] = None,
    ) -> UserFeedback:
        """Collect correction feedback when user fixes classification.

        Args:
            operation: The operation with incorrect classification.
            corrected_destination: User's corrected destination type.
            corrected_consumer: User's corrected consumer type.
            corrected_semantics: User's corrected semantics.
            reasoning: User's explanation for correction.

        Returns:
            UserFeedback record.
        """
        # Build system classification dict
        system_class = None
        if operation.classification:
            system_class = {
                "destination": operation.classification.destination.value,
                "consumer": operation.classification.consumer.value,
                "semantics": operation.classification.semantics.value,
                "confidence": operation.classification.confidence,
            }

        # Build corrected classification dict
        corrected = {}
        if corrected_destination:
            corrected["destination"] = corrected_destination.value
        elif operation.classification:
            corrected["destination"] = operation.classification.destination.value

        if corrected_consumer:
            corrected["consumer"] = corrected_consumer.value
        elif operation.classification:
            corrected["consumer"] = operation.classification.consumer.value

        if corrected_semantics:
            corrected["semantics"] = corrected_semantics.value
        elif operation.classification:
            corrected["semantics"] = operation.classification.semantics.value

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.CORRECTION,
            system_classification=system_class,
            user_corrected_classification=corrected,
            correction_reasoning=reasoning,
            feedback_confidence=0.95,  # Corrections are highest confidence
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback

    # =========================================================================
    # APPROVAL FEEDBACK
    # =========================================================================

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
        modification_extent: float = 0.0,
        modification_details: Optional[dict] = None,
    ) -> UserFeedback:
        """Collect approval feedback when user accepts/rejects operation.

        Args:
            operation: The operation being approved.
            approved: Whether user approved the operation.
            modified: Whether user modified before approving.
            modification_extent: How much was modified (0.0-1.0).
            modification_details: Details of modifications.

        Returns:
            UserFeedback record.
        """
        session = self._sessions.get(operation.id)
        time_to_decision = None

        if session and session.approval_presented_at:
            session.approval_decided_at = datetime.now()
            delta = session.approval_decided_at - session.approval_presented_at
            time_to_decision = int(delta.total_seconds() * 1000)

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.APPROVAL,
            approved=approved,
            modified=modified,
            modification_extent=modification_extent,
            modification_details=modification_details,
            time_to_decision_ms=time_to_decision,
            feedback_confidence=0.85 if not modified else 0.7,
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback

    # =========================================================================
    # BEHAVIORAL FEEDBACK
    # =========================================================================

    def record_retry(self, operation_id: str):
        """Record when user retries an operation."""
        session = self._sessions.get(operation_id)
        if session:
            session.retry_count += 1
            session.last_retry_at = datetime.now()

    def record_undo(self, operation_id: str):
        """Record when user undoes an operation."""
        session = self._sessions.get(operation_id)
        if session:
            session.undone = True
            session.undo_at = datetime.now()

    def record_abandon(self, operation_id: str):
        """Record when user abandons an operation."""
        session = self._sessions.get(operation_id)
        if session:
            session.abandoned = True

    def collect_behavioral_feedback(
        self,
        operation: AtomicOperation,
    ) -> Optional[UserFeedback]:
        """Collect accumulated behavioral feedback for an operation.

        Call this at the end of an operation's lifecycle to
        capture all behavioral signals.

        Returns:
            UserFeedback record or None if no session exists.
        """
        session = self._sessions.get(operation.id)
        if not session:
            return None

        # Calculate time to undo if applicable
        time_to_undo = None
        if session.undone and session.undo_at and session.execution_completed_at:
            delta = session.undo_at - session.execution_completed_at
            time_to_undo = int(delta.total_seconds() * 1000)

        # Calculate time to retry if applicable
        time_to_retry = None
        if session.retry_count > 0 and session.last_retry_at:
            delta = session.last_retry_at - session.started_at
            time_to_retry = int(delta.total_seconds() * 1000)

        # Skip if no behavioral signals
        if not (session.retry_count > 0 or session.undone or session.abandoned):
            return None

        # Calculate confidence based on signal strength
        confidence = 0.6
        if session.undone:
            confidence = 0.8  # Undo is strong negative signal
        if session.abandoned:
            confidence = 0.7  # Abandon is moderate negative signal
        if session.retry_count > 2:
            confidence = 0.75  # Multiple retries is negative signal

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.BEHAVIORAL,
            retried=session.retry_count > 0,
            time_to_retry_ms=time_to_retry,
            undid=session.undone,
            time_to_undo_ms=time_to_undo,
            abandoned=session.abandoned,
            feedback_confidence=confidence,
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback

    # =========================================================================
    # LONG-TERM FEEDBACK
    # =========================================================================

    def collect_long_term_feedback(
        self,
        operation: AtomicOperation,
        persisted: bool,
        days_persisted: Optional[int] = None,
        reused: bool = False,
        referenced: bool = False,
    ) -> UserFeedback:
        """Collect long-term outcome feedback.

        This is collected asynchronously, days/weeks after the operation.

        Args:
            operation: The operation to evaluate.
            persisted: Whether the operation's result persisted.
            days_persisted: How many days the result has persisted.
            reused: Whether the pattern was reused in new operations.
            referenced: Whether the result was referenced later.

        Returns:
            UserFeedback record.
        """
        # Long-term signals are lower confidence individually
        # but valuable for aggregate learning
        confidence = 0.5
        if persisted and days_persisted and days_persisted > 7:
            confidence = 0.7
        if reused:
            confidence = 0.8
        if referenced:
            confidence = 0.75

        feedback = UserFeedback(
            id=str(uuid4()),
            operation_id=operation.id,
            user_id=operation.user_id,
            feedback_type=FeedbackType.LONG_TERM,
            operation_persisted=persisted,
            days_persisted=days_persisted,
            reused_pattern=reused,
            referenced_later=referenced,
            feedback_confidence=confidence,
        )

        if self.store:
            self.store.store_feedback(feedback)

        return feedback


class LearningAggregator:
    """Aggregates feedback into learning metrics.

    Computes accuracy metrics, improvement tracking, and
    generates training data for classification improvement.
    """

    def __init__(self, store: AtomicOpsStore):
        """Initialize learning aggregator.

        Args:
            store: Store for reading feedback and writing metrics.
        """
        self.store = store

    def compute_metrics(
        self,
        user_id: str,
        window_days: int = 7,
    ) -> LearningMetrics:
        """Compute learning metrics for a user over a time window.

        Args:
            user_id: User identifier.
            window_days: Number of days to include.

        Returns:
            LearningMetrics with accuracy and improvement data.
        """
        window_end = datetime.now()
        window_start = window_end - timedelta(days=window_days)

        # Query feedback data
        stats = self.store.get_classification_stats(user_id)

        # Build metrics
        metrics = LearningMetrics(
            user_id=user_id,
            window_start=window_start,
            window_end=window_end,
            window_days=window_days,
            classification_accuracy=stats.get("accuracy", 0.0),
            sample_size=stats.get("feedback_count", 0),
            accuracy_by_destination=stats.get("distribution", {}).get("destination", {}),
            accuracy_by_consumer=stats.get("distribution", {}).get("consumer", {}),
            accuracy_by_semantics=stats.get("distribution", {}).get("semantics", {}),
            avg_rating=stats.get("avg_rating"),
            correction_rate=stats.get("correction_rate", 0.0),
        )

        # Store metrics
        self.store.store_learning_metrics(metrics)

        return metrics

    def get_training_pairs(
        self,
        user_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Get training pairs from feedback data.

        Returns list of dicts with:
        - request: The original request text
        - features: Extracted features
        - true_label: The confirmed correct classification
        - feedback_confidence: How confident we are in the label

        Args:
            user_id: Optional user filter.
            limit: Maximum pairs to return.

        Returns:
            List of training pair dicts.
        """
        # Query training_data view
        query = """
            SELECT * FROM training_data
            WHERE true_destination IS NOT NULL
        """
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        cursor = self.store.conn.execute(query, params)
        pairs = []

        for row in cursor.fetchall():
            pairs.append({
                "request": row["user_request"],
                "features": row["features_json"],
                "true_label": {
                    "destination": row["true_destination"],
                    "consumer": row["true_consumer"],
                    "semantics": row["true_semantics"],
                },
                "system_label": {
                    "destination": row["system_destination"],
                    "consumer": row["system_consumer"],
                    "semantics": row["system_semantics"],
                },
                "feedback_confidence": row["feedback_confidence"] or 0.5,
            })

        return pairs

    def identify_weak_areas(
        self,
        user_id: str,
        threshold: float = 0.7,
    ) -> list[dict]:
        """Identify classification areas needing improvement.

        Returns areas where accuracy is below threshold.

        Args:
            user_id: User identifier.
            threshold: Minimum acceptable accuracy.

        Returns:
            List of weak area dicts with category and accuracy.
        """
        stats = self.store.get_classification_stats(user_id)
        weak_areas = []

        for dim_name, dim_dist in stats.get("distribution", {}).items():
            for category, count in dim_dist.items():
                # Calculate accuracy for this category
                # (simplified - would need more detailed tracking)
                if count > 5:  # Minimum sample size
                    # Placeholder accuracy calculation
                    accuracy = stats.get("accuracy", 0.5)
                    if accuracy < threshold:
                        weak_areas.append({
                            "dimension": dim_name,
                            "category": category,
                            "accuracy": accuracy,
                            "sample_size": count,
                        })

        return weak_areas


def create_feedback_collector(
    store: Optional[AtomicOpsStore] = None,
) -> FeedbackCollector:
    """Create a feedback collector."""
    return FeedbackCollector(store=store)


def create_learning_aggregator(store: AtomicOpsStore) -> LearningAggregator:
    """Create a learning aggregator."""
    return LearningAggregator(store=store)
