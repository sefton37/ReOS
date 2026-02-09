"""Tests for classification context (few-shot learning from corrections)."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from reos.atomic_ops.classification_context import ClassificationContext
from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
    FeedbackType,
    UserFeedback,
)
from reos.atomic_ops.schema import AtomicOpsStore


@pytest.fixture
def store() -> AtomicOpsStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return AtomicOpsStore(conn)


@pytest.fixture
def context(store: AtomicOpsStore) -> ClassificationContext:
    return ClassificationContext(store)


def _create_operation_with_correction(
    store: AtomicOpsStore,
    request: str,
    sys_dest: str,
    sys_cons: str,
    sys_sem: str,
    corr_dest: str,
    corr_cons: str,
    corr_sem: str,
) -> None:
    """Helper to create an operation and a correction for it."""
    from reos.atomic_ops.models import AtomicOperation, OperationStatus

    op = AtomicOperation(
        user_request=request,
        user_id="test-user",
        classification=Classification(
            destination=DestinationType(sys_dest),
            consumer=ConsumerType(sys_cons),
            semantics=ExecutionSemantics(sys_sem),
            confident=True,
        ),
    )
    store.create_operation(op)

    feedback = UserFeedback(
        id=str(uuid4()),
        operation_id=op.id,
        user_id="test-user",
        feedback_type=FeedbackType.CORRECTION,
        user_corrected_destination=corr_dest,
        user_corrected_consumer=corr_cons,
        user_corrected_semantics=corr_sem,
        correction_reasoning="wrong classification",
    )
    store.store_feedback(feedback)


class TestClassificationContext:
    def test_no_corrections(self, context: ClassificationContext) -> None:
        """Returns empty list when no corrections exist."""
        corrections = context.get_corrections()
        assert corrections == []

    def test_has_corrections_false(self, context: ClassificationContext) -> None:
        """has_corrections returns False when empty."""
        assert context.has_corrections() is False

    def test_get_corrections(
        self, store: AtomicOpsStore, context: ClassificationContext
    ) -> None:
        """Returns corrections formatted for classifier prompt."""
        _create_operation_with_correction(
            store,
            request="good morning",
            sys_dest="file",
            sys_cons="machine",
            sys_sem="execute",
            corr_dest="stream",
            corr_cons="human",
            corr_sem="interpret",
        )

        corrections = context.get_corrections()
        assert len(corrections) == 1
        assert corrections[0]["request"] == "good morning"
        assert corrections[0]["system_destination"] == "file"
        assert corrections[0]["corrected_destination"] == "stream"
        assert corrections[0]["corrected_consumer"] == "human"
        assert corrections[0]["corrected_semantics"] == "interpret"

    def test_has_corrections_true(
        self, store: AtomicOpsStore, context: ClassificationContext
    ) -> None:
        """has_corrections returns True when corrections exist."""
        _create_operation_with_correction(
            store,
            request="test",
            sys_dest="stream",
            sys_cons="human",
            sys_sem="read",
            corr_dest="stream",
            corr_cons="human",
            corr_sem="interpret",
        )
        assert context.has_corrections() is True

    def test_limit_respected(
        self, store: AtomicOpsStore, context: ClassificationContext
    ) -> None:
        """Limit parameter is respected."""
        for i in range(5):
            _create_operation_with_correction(
                store,
                request=f"test request {i}",
                sys_dest="stream",
                sys_cons="human",
                sys_sem="read",
                corr_dest="file",
                corr_cons="human",
                corr_sem="execute",
            )

        corrections = context.get_corrections(limit=3)
        assert len(corrections) == 3
