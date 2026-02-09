"""Tests for LLM-native atomic operations classifier.

Tests:
- Classification with mock LLM returning valid JSON
- Fallback when LLM unavailable
- LLM returns invalid JSON → confident=False
- Corrections included in prompt
- Schema creates without errors
- classification_confident is boolean in DB
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from reos.atomic_ops.classifier import AtomicClassifier, ClassificationResult
from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)
from reos.atomic_ops.schema import AtomicOpsStore, init_atomic_ops_schema


class MockLLM:
    """Mock LLM provider for testing."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_system: str = ""
        self.last_user: str = ""
        self.call_count = 0
        self.current_model = "test-model-1b"

    def chat_json(
        self,
        system: str = "",
        user: str = "",
        temperature: float = 0.1,
        top_p: float = 0.9,
        **kwargs,
    ) -> str:
        self.last_system = system
        self.last_user = user
        self.call_count += 1
        if self.error:
            raise self.error
        return self.response or "{}"


class TestAtomicClassifierWithLLM:
    """Test LLM-native classification."""

    def test_classify_greeting(self) -> None:
        """'good morning' should classify as stream/human/interpret."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "stream",
                "consumer": "human",
                "semantics": "interpret",
                "confident": True,
                "reasoning": "greeting",
            })
        )
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("good morning")

        assert result.classification.destination == DestinationType.STREAM
        assert result.classification.consumer == ConsumerType.HUMAN
        assert result.classification.semantics == ExecutionSemantics.INTERPRET
        assert result.classification.confident is True
        assert result.classification.reasoning == "greeting"
        assert llm.call_count == 1

    def test_classify_system_command(self) -> None:
        """'run pytest' should classify as process/machine/execute."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "process",
                "consumer": "machine",
                "semantics": "execute",
                "confident": True,
                "reasoning": "system command",
            })
        )
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("run pytest")

        assert result.classification.destination == DestinationType.PROCESS
        assert result.classification.consumer == ConsumerType.MACHINE
        assert result.classification.semantics == ExecutionSemantics.EXECUTE
        assert result.classification.confident is True

    def test_classify_file_operation(self) -> None:
        """'save to notes.txt' should classify as file/human/execute."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "file",
                "consumer": "human",
                "semantics": "execute",
                "confident": True,
                "reasoning": "file write",
            })
        )
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("save to notes.txt")

        assert result.classification.destination == DestinationType.FILE
        assert result.classification.consumer == ConsumerType.HUMAN
        assert result.classification.semantics == ExecutionSemantics.EXECUTE

    def test_classify_not_confident(self) -> None:
        """LLM can signal it's not confident."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "stream",
                "consumer": "human",
                "semantics": "interpret",
                "confident": False,
                "reasoning": "ambiguous",
            })
        )
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("hmm")

        assert result.classification.confident is False

    def test_classify_model_info(self) -> None:
        """Result includes model name."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "stream",
                "consumer": "human",
                "semantics": "read",
                "confident": True,
            })
        )
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("show status")

        assert result.model == "test-model-1b"


class TestAtomicClassifierFallback:
    """Test keyword-based fallback classification."""

    def test_fallback_when_no_llm(self) -> None:
        """Fallback used when no LLM provided."""
        classifier = AtomicClassifier(llm=None)
        result = classifier.classify("good morning")

        assert result.classification.confident is False
        assert result.model == "keyword_fallback"
        assert "keyword fallback" in result.classification.reasoning

    def test_fallback_on_llm_error(self) -> None:
        """Fallback used when LLM raises exception."""
        llm = MockLLM(error=RuntimeError("connection refused"))
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("good morning")

        assert result.classification.confident is False
        assert result.model == "keyword_fallback"

    def test_fallback_on_invalid_json(self) -> None:
        """Fallback used when LLM returns invalid JSON."""
        llm = MockLLM(response="not json at all")
        classifier = AtomicClassifier(llm=llm)
        result = classifier.classify("good morning")

        assert result.classification.confident is False
        assert result.model == "keyword_fallback"

    def test_fallback_keywords_run(self) -> None:
        """Fallback classifies 'run' as process/execute."""
        classifier = AtomicClassifier(llm=None)
        result = classifier.classify("run the test suite")

        assert result.classification.destination == DestinationType.PROCESS
        assert result.classification.semantics == ExecutionSemantics.EXECUTE

    def test_fallback_keywords_show(self) -> None:
        """Fallback classifies 'show' as read."""
        classifier = AtomicClassifier(llm=None)
        result = classifier.classify("show memory usage")

        assert result.classification.semantics == ExecutionSemantics.READ

    def test_fallback_keywords_save(self) -> None:
        """Fallback classifies 'save' as file/execute."""
        classifier = AtomicClassifier(llm=None)
        result = classifier.classify("save to file")

        assert result.classification.destination == DestinationType.FILE
        assert result.classification.semantics == ExecutionSemantics.EXECUTE

    def test_fallback_default_conversation(self) -> None:
        """Fallback defaults to stream/human/interpret for unknown input."""
        classifier = AtomicClassifier(llm=None)
        result = classifier.classify("how about that weather")

        assert result.classification.destination == DestinationType.STREAM
        assert result.classification.consumer == ConsumerType.HUMAN
        assert result.classification.semantics == ExecutionSemantics.INTERPRET


class TestCorrectionsInPrompt:
    """Test that corrections are included in classification prompt."""

    def test_corrections_included_in_prompt(self) -> None:
        """Past corrections are formatted into the system prompt."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "stream",
                "consumer": "human",
                "semantics": "interpret",
                "confident": True,
            })
        )
        classifier = AtomicClassifier(llm=llm)

        corrections = [
            {
                "request": "good morning",
                "system_destination": "file",
                "system_consumer": "machine",
                "system_semantics": "execute",
                "corrected_destination": "stream",
                "corrected_consumer": "human",
                "corrected_semantics": "interpret",
            }
        ]

        classifier.classify("hello", corrections=corrections)

        # Corrections should appear in the system prompt
        assert "PAST CORRECTIONS" in llm.last_system
        assert "good morning" in llm.last_system
        assert "misclassified" in llm.last_system

    def test_no_corrections_no_block(self) -> None:
        """Empty corrections list produces no corrections block."""
        llm = MockLLM(
            response=json.dumps({
                "destination": "stream",
                "consumer": "human",
                "semantics": "read",
                "confident": True,
            })
        )
        classifier = AtomicClassifier(llm=llm)
        classifier.classify("show status", corrections=[])

        assert "PAST CORRECTIONS" not in llm.last_system


class TestSchemaAndStorage:
    """Test schema creation and data storage with new classification fields."""

    @pytest.fixture
    def db_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn

    def test_schema_creates_successfully(self, db_conn: sqlite3.Connection) -> None:
        """Schema v2 initializes without errors."""
        store = AtomicOpsStore(db_conn)

        # Verify tables exist
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "atomic_operations" in tables
        assert "classification_log" in tables
        assert "user_feedback" in tables
        assert "classification_clarifications" in tables
        # ml_features should NOT exist
        assert "ml_features" not in tables

    def test_classification_confident_stored_as_boolean(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """classification_confident is stored as INTEGER (0/1)."""
        from reos.atomic_ops.models import AtomicOperation

        store = AtomicOpsStore(db_conn)

        op = AtomicOperation(
            user_request="good morning",
            user_id="test-user",
            classification=Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.INTERPRET,
                confident=True,
                reasoning="greeting",
            ),
        )
        store.create_operation(op)

        # Read back raw
        cursor = db_conn.execute(
            "SELECT classification_confident FROM atomic_operations WHERE id = ?",
            (op.id,)
        )
        row = cursor.fetchone()
        assert row[0] == 1  # True stored as 1

        # Read back via store
        loaded = store.get_operation(op.id)
        assert loaded is not None
        assert loaded.classification is not None
        assert loaded.classification.confident is True

    def test_not_confident_stored(self, db_conn: sqlite3.Connection) -> None:
        """confident=False is stored as 0."""
        from reos.atomic_ops.models import AtomicOperation

        store = AtomicOpsStore(db_conn)

        op = AtomicOperation(
            user_request="hmm",
            user_id="test-user",
            classification=Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.INTERPRET,
                confident=False,
                reasoning="uncertain",
            ),
        )
        store.create_operation(op)

        cursor = db_conn.execute(
            "SELECT classification_confident FROM atomic_operations WHERE id = ?",
            (op.id,)
        )
        row = cursor.fetchone()
        assert row[0] == 0

    def test_log_classification(self, db_conn: sqlite3.Connection) -> None:
        """Classification log stores confident and reasoning."""
        store = AtomicOpsStore(db_conn)

        classification = Classification(
            destination=DestinationType.STREAM,
            consumer=ConsumerType.HUMAN,
            semantics=ExecutionSemantics.READ,
            confident=True,
            reasoning="keyword match",
        )

        log_id = store.log_classification("test-op-id", classification, model="llama3.2:1b")

        cursor = db_conn.execute(
            "SELECT * FROM classification_log WHERE id = ?", (log_id,)
        )
        row = cursor.fetchone()
        assert row["confident"] == 1
        assert row["reasoning"] == "keyword match"
        assert row["model"] == "llama3.2:1b"

    def test_schema_version_is_2(self, db_conn: sqlite3.Connection) -> None:
        """Schema version is updated to 2."""
        store = AtomicOpsStore(db_conn)

        cursor = db_conn.execute("SELECT version FROM atomic_ops_schema_version LIMIT 1")
        row = cursor.fetchone()
        assert row[0] == 2


class TestBackwardCompatConfidence:
    """Test backward-compatible confidence property on AtomicOperation."""

    def test_confident_returns_0_9(self) -> None:
        """confident=True → operation.confidence == 0.9."""
        from reos.atomic_ops.models import AtomicOperation

        op = AtomicOperation(
            user_request="test",
            user_id="u",
            classification=Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.READ,
                confident=True,
            ),
        )
        assert op.confidence == 0.9

    def test_not_confident_returns_0_3(self) -> None:
        """confident=False → operation.confidence == 0.3."""
        from reos.atomic_ops.models import AtomicOperation

        op = AtomicOperation(
            user_request="test",
            user_id="u",
            classification=Classification(
                destination=DestinationType.STREAM,
                consumer=ConsumerType.HUMAN,
                semantics=ExecutionSemantics.READ,
                confident=False,
            ),
        )
        assert op.confidence == 0.3

    def test_no_classification_returns_0(self) -> None:
        """No classification → operation.confidence == 0.0."""
        from reos.atomic_ops.models import AtomicOperation

        op = AtomicOperation(user_request="test", user_id="u")
        assert op.confidence == 0.0
