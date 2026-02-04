from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from reos.db import Database
from reos.errors import record_error


@pytest.fixture
def temp_db() -> Iterator[Database]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


def test_record_error_inserts_event(temp_db: Database) -> None:
    event_id = record_error(
        source="reos",
        operation="unit_test",
        exc=RuntimeError("boom"),
        context={"k": "v"},
        db=temp_db,
        dedupe_window_seconds=0,
    )

    assert isinstance(event_id, str)

    rows = temp_db.iter_events_recent(limit=5)
    assert len(rows) == 1
    assert rows[0]["kind"] == "error"
    assert rows[0]["source"] == "reos"

    payload_raw = rows[0]["payload_metadata"]
    assert isinstance(payload_raw, str)
    payload = json.loads(payload_raw)
    assert payload["kind"] == "error"
    assert payload["operation"] == "unit_test"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert payload["context"] == {"k": "v"}
    assert isinstance(payload["signature"], str)


def test_record_error_dedupes_within_window(temp_db: Database) -> None:
    first = record_error(
        source="reos",
        operation="unit_test_dedupe",
        exc=ValueError("same"),
        db=temp_db,
        dedupe_window_seconds=3600,
    )
    second = record_error(
        source="reos",
        operation="unit_test_dedupe",
        exc=ValueError("same"),
        db=temp_db,
        dedupe_window_seconds=3600,
    )

    assert first is not None
    assert second is None

    rows = temp_db.iter_events_recent(limit=10)
    assert len(rows) == 1


# =============================================================================
# Error Hierarchy Tests
# =============================================================================


from reos.errors import (
    TalkingRockError,
    ValidationError,
    PathValidationError,
    CommandValidationError,
    SafetyError,
    RateLimitError,
    CircuitBreakerError,
    LLMError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelError,
    DatabaseError,
    IntegrityError,
    MigrationError,
    ConfigurationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ExecutionError,
    SandboxError,
    error_response,
    get_error_code,
    ErrorResponse,
    # New additions
    Result,
    handle_errors,
    MemoryError,
    StorageError,
    AtomicOpError,
    CAIRNError,
)


class TestTalkingRockError:
    """Tests for the base error class."""

    def test_basic_creation(self):
        """Error can be created with just a message."""
        err = TalkingRockError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.message == "Something went wrong"
        assert err.recoverable is False
        assert err.context == {}

    def test_with_context(self):
        """Error can include context data."""
        err = TalkingRockError(
            "Failed",
            context={"key": "value", "count": 42},
        )
        assert err.context == {"key": "value", "count": 42}

    def test_recoverable_flag(self):
        """Recoverable flag can be set."""
        err = TalkingRockError("Transient failure", recoverable=True)
        assert err.recoverable is True

    def test_to_dict(self):
        """Error can be converted to dictionary."""
        err = TalkingRockError(
            "Error message",
            recoverable=True,
            context={"field": "username"},
        )
        result = err.to_dict()
        assert result["type"] == "talkingrock"
        assert result["message"] == "Error message"
        assert result["recoverable"] is True
        assert result["field"] == "username"


class TestValidationError:
    """Tests for validation errors."""

    def test_with_field(self):
        """Validation error includes field name."""
        err = ValidationError("Invalid input", field="username")
        assert err.field == "username"
        assert err.context["field"] == "username"

    def test_with_constraint(self):
        """Validation error includes constraint info."""
        err = ValidationError("Too short", field="pwd", constraint="min_length")
        assert err.constraint == "min_length"
        assert err.context["constraint"] == "min_length"

    def test_sensitive_value_not_included(self):
        """Sensitive values are not included in context."""
        err = ValidationError("Invalid", field="password", value="secret123")
        assert "secret123" not in str(err.context.get("value", ""))

    def test_non_sensitive_value_included(self):
        """Non-sensitive values are included."""
        err = ValidationError("Invalid", field="count", value="abc")
        assert err.context.get("value") == "abc"


class TestSafetyError:
    """Tests for safety errors."""

    def test_limit_info(self):
        """Safety error includes limit information."""
        err = SafetyError(
            "Limit exceeded",
            limit_type="sudo",
            current_value=5,
            limit_value=3,
        )
        assert err.limit_type == "sudo"
        assert err.context["current"] == 5
        assert err.context["limit"] == 3


class TestRateLimitError:
    """Tests for rate limit errors."""

    def test_is_recoverable(self):
        """Rate limit errors are recoverable."""
        err = RateLimitError()
        assert err.recoverable is True

    def test_retry_after(self):
        """Retry after is included."""
        err = RateLimitError(category="auth", retry_after=60)
        assert err.context["category"] == "auth"
        assert err.context["retry_after_seconds"] == 60


class TestLLMError:
    """Tests for LLM errors."""

    def test_provider_and_model(self):
        """LLM error includes provider and model."""
        err = LLMError("Failed", provider="ollama", model="llama3")
        assert err.provider == "ollama"
        assert err.model == "llama3"

    def test_connection_error_recoverable(self):
        """Connection errors are recoverable."""
        err = LLMConnectionError("Cannot connect", provider="ollama")
        assert err.recoverable is True

    def test_timeout_error_recoverable(self):
        """Timeout errors are recoverable."""
        err = LLMTimeoutError("Timed out", timeout_seconds=30.0)
        assert err.recoverable is True


class TestDatabaseError:
    """Tests for database errors."""

    def test_operation_and_table(self):
        """Database error includes operation and table."""
        err = DatabaseError("Query failed", operation="insert", table="users")
        assert err.context["operation"] == "insert"
        assert err.context["table"] == "users"

    def test_integrity_error(self):
        """Integrity error includes constraint."""
        err = IntegrityError("FK violation", constraint="fk_user_id", table="orders")
        assert err.context["constraint"] == "fk_user_id"


class TestErrorResponse:
    """Tests for error response helpers."""

    def test_from_domain_error(self):
        """error_response converts domain errors correctly."""
        err = ValidationError("Invalid input", field="email")
        response = error_response(err)

        assert response.error_type == "validation"
        assert response.message == "Invalid input"
        assert response.recoverable is False

    def test_from_unknown_exception(self):
        """error_response handles unknown exceptions."""
        err = ValueError("something went wrong")
        response = error_response(err)

        assert response.error_type == "internal"
        assert "something went wrong" in response.message

    def test_to_dict(self):
        """ErrorResponse converts to dict correctly."""
        response = ErrorResponse(
            error_type="validation",
            message="Invalid",
            recoverable=False,
            details={"field": "name"},
        )
        result = response.to_dict()

        assert result["error"]["type"] == "validation"
        assert result["error"]["message"] == "Invalid"


class TestErrorCodeMapping:
    """Tests for error code mapping."""

    def test_validation_error_code(self):
        """Validation errors get -32000."""
        err = ValidationError("Invalid")
        assert get_error_code(err) == -32000

    def test_rate_limit_error_code(self):
        """Rate limit errors get -32001."""
        err = RateLimitError()
        assert get_error_code(err) == -32001

    def test_safety_error_code(self):
        """Safety errors get -32004."""
        err = SafetyError("Blocked")
        assert get_error_code(err) == -32004

    def test_llm_error_code(self):
        """LLM errors get -32010."""
        err = LLMError("Failed")
        assert get_error_code(err) == -32010

    def test_database_error_code(self):
        """Database errors get -32020."""
        err = DatabaseError("Failed")
        assert get_error_code(err) == -32020


class TestErrorHierarchy:
    """Tests for error hierarchy relationships."""

    def test_all_inherit_from_base(self):
        """All error types inherit from TalkingRockError."""
        error_types = [
            ValidationError,
            PathValidationError,
            SafetyError,
            RateLimitError,
            LLMError,
            LLMConnectionError,
            DatabaseError,
            IntegrityError,
            ConfigurationError,
            AuthenticationError,
            NotFoundError,
            ExecutionError,
            SandboxError,
        ]

        for error_type in error_types:
            err = error_type("test")
            assert isinstance(err, TalkingRockError)

    def test_path_validation_is_validation(self):
        """PathValidationError is a ValidationError."""
        err = PathValidationError("Invalid")
        assert isinstance(err, ValidationError)

    def test_rate_limit_is_safety(self):
        """RateLimitError is a SafetyError."""
        err = RateLimitError()
        assert isinstance(err, SafetyError)

    def test_llm_connection_is_llm(self):
        """LLMConnectionError is an LLMError."""
        err = LLMConnectionError("Cannot connect")
        assert isinstance(err, LLMError)

    def test_integrity_is_database(self):
        """IntegrityError is a DatabaseError."""
        err = IntegrityError("Constraint violated")
        assert isinstance(err, DatabaseError)

    def test_sandbox_is_execution(self):
        """SandboxError is an ExecutionError."""
        err = SandboxError("Failed")
        assert isinstance(err, ExecutionError)


# =============================================================================
# Result Type Tests
# =============================================================================


class TestResult:
    """Tests for the Result type."""

    def test_ok_creates_successful_result(self):
        """Result.ok() creates a successful result with value."""
        result = Result.ok(42)
        assert result.success is True
        assert result.value == 42
        assert result.error is None

    def test_fail_creates_failed_result(self):
        """Result.fail() creates a failed result with error."""
        error = ValidationError("Invalid input")
        result = Result.fail(error)
        assert result.success is False
        assert result.value is None
        assert result.error is error

    def test_unwrap_returns_value_on_success(self):
        """unwrap() returns the value for successful results."""
        result = Result.ok("hello")
        assert result.unwrap() == "hello"

    def test_unwrap_raises_on_failure(self):
        """unwrap() raises the error for failed results."""
        error = ValidationError("Bad input")
        result = Result.fail(error)
        with pytest.raises(ValidationError) as exc_info:
            result.unwrap()
        assert exc_info.value is error

    def test_unwrap_or_returns_value_on_success(self):
        """unwrap_or() returns the value for successful results."""
        result = Result.ok(42)
        assert result.unwrap_or(0) == 42

    def test_unwrap_or_returns_default_on_failure(self):
        """unwrap_or() returns the default for failed results."""
        result = Result.fail(ValidationError("Error"))
        assert result.unwrap_or("default") == "default"

    def test_result_with_none_value(self):
        """Result can wrap None as a successful value."""
        result = Result.ok(None)
        assert result.success is True
        assert result.value is None

    def test_result_with_complex_type(self):
        """Result can wrap complex types."""
        data = {"users": [{"id": 1, "name": "Alice"}]}
        result = Result.ok(data)
        assert result.success is True
        assert result.value == data


# =============================================================================
# handle_errors Decorator Tests
# =============================================================================


class TestHandleErrorsDecorator:
    """Tests for the handle_errors decorator."""

    def test_returns_value_on_success(self):
        """Decorator returns function result on success."""

        @handle_errors("test operation")
        def successful_func() -> str:
            return "success"

        assert successful_func() == "success"

    def test_returns_default_on_exception(self):
        """Decorator returns default value when exception occurs."""

        @handle_errors("test operation", default="fallback")
        def failing_func() -> str:
            raise ValueError("boom")

        assert failing_func() == "fallback"

    def test_returns_none_by_default(self):
        """Decorator returns None by default when exception occurs."""

        @handle_errors("test operation")
        def failing_func() -> str | None:
            raise ValueError("boom")

        assert failing_func() is None

    def test_propagates_talking_rock_error(self):
        """Decorator propagates TalkingRockError unchanged."""

        @handle_errors("test operation", default="fallback")
        def func_raising_domain_error() -> str:
            raise ValidationError("Invalid input")

        with pytest.raises(ValidationError):
            func_raising_domain_error()

    def test_reraise_converts_to_talking_rock_error(self):
        """Decorator can re-raise as TalkingRockError."""

        @handle_errors("test operation", reraise=True)
        def failing_func() -> str:
            raise ValueError("original error")

        with pytest.raises(TalkingRockError) as exc_info:
            failing_func()

        assert "Failed to test operation" in str(exc_info.value)
        assert exc_info.value.context["original_error"] == "original error"

    def test_preserves_function_name(self):
        """Decorator preserves the wrapped function's name."""

        @handle_errors("my operation")
        def my_function() -> None:
            pass

        assert my_function.__name__ == "my_function"

    def test_handles_function_with_args(self):
        """Decorator works with functions that have arguments."""

        @handle_errors("division", default=0)
        def divide(a: int, b: int) -> int:
            return a // b

        assert divide(10, 2) == 5
        assert divide(10, 0) == 0  # ZeroDivisionError caught

    def test_handles_function_with_kwargs(self):
        """Decorator works with functions that have keyword arguments."""

        @handle_errors("processing", default={})
        def process(*, items: list[str], prefix: str = "") -> dict:
            return {prefix + item: len(item) for item in items}

        result = process(items=["a", "bb"], prefix="len_")
        assert result == {"len_a": 1, "len_bb": 2}


# =============================================================================
# Domain-Specific Error Tests
# =============================================================================


class TestDomainSpecificErrors:
    """Tests for domain-specific error types."""

    def test_memory_error(self):
        """MemoryError includes operation and block_id."""
        err = MemoryError(
            "Embedding failed",
            operation="embed",
            block_id="block-123",
        )
        assert err.context["operation"] == "embed"
        assert err.context["block_id"] == "block-123"
        assert err.recoverable is True

    def test_storage_error(self):
        """StorageError includes operation and path."""
        err = StorageError(
            "Write failed",
            operation="append_event",
            path="/data/events.jsonl",
        )
        assert err.context["operation"] == "append_event"
        assert "/data/events.jsonl" in err.context["path"]
        assert err.recoverable is False

    def test_atomic_op_error(self):
        """AtomicOpError includes operation and phase."""
        err = AtomicOpError(
            "Backup failed",
            operation="file_backup",
            phase="pre_execution",
        )
        assert err.context["operation"] == "file_backup"
        assert err.context["phase"] == "pre_execution"

    def test_cairn_error(self):
        """CAIRNError includes stage and query."""
        err = CAIRNError(
            "Reasoning failed",
            stage="context_building",
            query="What are the pending tasks?",
        )
        assert err.context["stage"] == "context_building"
        assert "pending tasks" in err.context["query"]
        assert err.recoverable is True

    def test_domain_errors_have_error_codes(self):
        """Domain-specific errors have mapped error codes."""
        assert get_error_code(MemoryError("test")) == -32050
        assert get_error_code(StorageError("test")) == -32051
        assert get_error_code(AtomicOpError("test")) == -32052
        assert get_error_code(CAIRNError("test")) == -32053