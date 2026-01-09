"""Talking Rock Error Hierarchy.

Provides a structured error hierarchy for all domain operations:
- TalkingRockError: Base exception for all application errors
- ValidationError: Input validation failures
- SafetyError: Safety constraint violations
- LLMError: LLM operation failures
- DatabaseError: Database operation failures
- ConfigurationError: Configuration/setup issues

Each error type includes:
- Descriptive message
- Optional field for context
- Recoverable flag for retry logic
- Structured representation for RPC responses

Usage:
    from reos.errors import ValidationError, SafetyError

    if not is_valid_path(path):
        raise ValidationError("Invalid path format", field="path")

    if is_dangerous_command(cmd):
        raise SafetyError("Command blocked by safety layer", command=cmd)
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Error Base Classes
# =============================================================================


class TalkingRockError(Exception):
    """Base exception for all Talking Rock application errors.

    Attributes:
        message: Human-readable error description
        recoverable: Whether the operation can be retried
        context: Additional context for debugging
    """

    def __init__(
        self,
        message: str,
        *,
        recoverable: bool = False,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to structured dictionary for RPC responses."""
        return {
            "type": type(self).__name__.lower().replace("error", ""),
            "message": self.message,
            "recoverable": self.recoverable,
            **{k: v for k, v in self.context.items() if v is not None},
        }


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(TalkingRockError):
    """Input validation failed.

    Raised when user input or parameters fail validation checks.

    Example:
        raise ValidationError("Username too short", field="username", min_length=3)
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        value: Any = None,
        constraint: str | None = None,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", {})
        if field:
            context["field"] = field
        if constraint:
            context["constraint"] = constraint
        # Don't include sensitive values
        if value is not None and not _is_sensitive(str(value)):
            context["value"] = _truncate(str(value), 100)
        super().__init__(message, recoverable=False, context=context)
        self.field = field
        self.constraint = constraint


class PathValidationError(ValidationError):
    """Path validation failed (traversal attempt, invalid chars, etc)."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            message,
            field="path",
            constraint=reason,
            context={"path": _truncate(path, 200) if path else None},
        )


class CommandValidationError(ValidationError):
    """Command validation failed (blocked pattern, too long, etc)."""

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        pattern: str | None = None,
    ) -> None:
        super().__init__(
            message,
            field="command",
            context={
                "command": _truncate(command, 200) if command else None,
                "blocked_pattern": pattern,
            },
        )


# =============================================================================
# Safety Errors
# =============================================================================


class SafetyError(TalkingRockError):
    """Safety constraint violated.

    Raised when an operation would violate safety boundaries.

    Example:
        raise SafetyError("Sudo escalation limit reached", limit_type="sudo")
    """

    def __init__(
        self,
        message: str,
        *,
        limit_type: str | None = None,
        current_value: int | None = None,
        limit_value: int | None = None,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", {})
        if limit_type:
            context["limit_type"] = limit_type
        if current_value is not None:
            context["current"] = current_value
        if limit_value is not None:
            context["limit"] = limit_value
        super().__init__(message, recoverable=False, context=context)
        self.limit_type = limit_type


class RateLimitError(SafetyError):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        category: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            message,
            limit_type="rate",
            context={
                "category": category,
                "retry_after_seconds": retry_after,
            },
        )
        # Rate limits are recoverable after waiting
        self.recoverable = True


class CircuitBreakerError(SafetyError):
    """Circuit breaker tripped (max iterations, timeout, etc)."""

    def __init__(
        self,
        message: str,
        *,
        breaker_type: str,
        iterations: int | None = None,
        elapsed_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message,
            limit_type=breaker_type,
            context={
                "iterations": iterations,
                "elapsed_seconds": elapsed_seconds,
            },
        )


# =============================================================================
# LLM Errors
# =============================================================================


class LLMError(TalkingRockError):
    """LLM operation failed.

    Base class for all LLM-related errors.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        recoverable: bool = False,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", {})
        if provider:
            context["provider"] = provider
        if model:
            context["model"] = model
        super().__init__(message, recoverable=recoverable, context=context)
        self.provider = provider
        self.model = model


class LLMConnectionError(LLMError):
    """Cannot connect to LLM provider."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        url: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            recoverable=True,  # Can retry after fixing connection
            context={"url": url, "suggestion": suggestion},
        )


class LLMTimeoutError(LLMError):
    """LLM request timed out."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            recoverable=True,  # Timeouts are often transient
            context={"timeout_seconds": timeout_seconds},
        )


class LLMModelError(LLMError):
    """Model-specific error (not found, overloaded, etc)."""

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            message,
            model=model,
            recoverable=False,
            context={"reason": reason},
        )


# =============================================================================
# Database Errors
# =============================================================================


class DatabaseError(TalkingRockError):
    """Database operation failed."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        table: str | None = None,
        recoverable: bool = False,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", {})
        if operation:
            context["operation"] = operation
        if table:
            context["table"] = table
        super().__init__(message, recoverable=recoverable, context=context)


class IntegrityError(DatabaseError):
    """Database integrity constraint violated."""

    def __init__(
        self,
        message: str,
        *,
        constraint: str | None = None,
        table: str | None = None,
    ) -> None:
        super().__init__(
            message,
            operation="constraint_check",
            table=table,
            recoverable=False,
            context={"constraint": constraint},
        )


class MigrationError(DatabaseError):
    """Database migration failed."""

    def __init__(
        self,
        message: str,
        *,
        version: int | None = None,
        migration_file: str | None = None,
    ) -> None:
        super().__init__(
            message,
            operation="migration",
            recoverable=False,
            context={"version": version, "migration_file": migration_file},
        )


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(TalkingRockError):
    """Configuration or setup issue."""

    def __init__(
        self,
        message: str,
        *,
        setting: str | None = None,
        expected: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(
            message,
            recoverable=False,
            context={
                "setting": setting,
                "expected": expected,
                "suggestion": suggestion,
            },
        )


class AuthenticationError(TalkingRockError):
    """Authentication failed."""

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        reason: str | None = None,
    ) -> None:
        super().__init__(
            message,
            recoverable=False,
            context={"reason": reason},
        )


class AuthorizationError(TalkingRockError):
    """User not authorized for this operation."""

    def __init__(
        self,
        message: str = "Not authorized",
        *,
        operation: str | None = None,
    ) -> None:
        super().__init__(
            message,
            recoverable=False,
            context={"operation": operation},
        )


class NotFoundError(TalkingRockError):
    """Resource not found."""

    def __init__(
        self,
        message: str,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            recoverable=False,
            context={"resource_type": resource_type, "resource_id": resource_id},
        )


# =============================================================================
# Execution Errors
# =============================================================================


class ExecutionError(TalkingRockError):
    """Code execution failed."""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        step: str | None = None,
        recoverable: bool = False,
        **kwargs: Any,
    ) -> None:
        context = kwargs.pop("context", {})
        if phase:
            context["phase"] = phase
        if step:
            context["step"] = step
        super().__init__(message, recoverable=recoverable, context=context)


class SandboxError(ExecutionError):
    """Sandbox operation failed."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(
            message,
            phase="sandbox",
            step=operation,
            context={"path": _truncate(path, 200) if path else None},
        )


# =============================================================================
# Helpers
# =============================================================================


def _is_sensitive(value: str) -> bool:
    """Check if a value appears to contain sensitive data."""
    sensitive_patterns = ["password", "token", "secret", "key", "auth"]
    lower = value.lower()
    return any(p in lower for p in sensitive_patterns)


def _truncate(value: str | None, max_len: int) -> str | None:
    """Truncate a string value for safe logging."""
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return value[:max_len] + "..."


# =============================================================================
# Error Recording (preserved from original)
# =============================================================================


_RECENT_SIGNATURES: dict[str, datetime] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _error_signature(*, operation: str, exc: BaseException) -> str:
    material = f"{operation}|{type(exc).__name__}|{str(exc)}".encode("utf-8", errors="replace")
    return hashlib.sha256(material).hexdigest()


def record_error(
    *,
    source: str,
    operation: str,
    exc: BaseException,
    context: dict[str, Any] | None = None,
    db: "Database | None" = None,
    dedupe_window_seconds: int = 60,
    include_traceback: bool = True,
) -> str | None:
    """Record an error as a local event.

    - Stores a metadata-only error summary in SQLite (or JSONL fallback via append_event).
    - Optionally deduplicates repeated identical errors for a short window.

    Returns the stored event id when known (SQLite path), else None.
    """
    # Avoid circular import
    from .db import Database
    from .models import Event

    signature = _error_signature(operation=operation, exc=exc)
    now = _utcnow()

    if dedupe_window_seconds > 0:
        cutoff = now - timedelta(seconds=dedupe_window_seconds)
        last_seen = _RECENT_SIGNATURES.get(signature)
        if last_seen is not None and last_seen >= cutoff:
            return None
        _RECENT_SIGNATURES[signature] = now

    tb_text: str | None = None
    if include_traceback:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # Keep the payload bounded.
        if len(tb_text) > 10_000:
            tb_text = tb_text[-10_000:]

    # Include structured context from TalkingRockError
    error_context = context or {}
    if isinstance(exc, TalkingRockError):
        error_context.update(exc.context)

    payload: dict[str, Any] = {
        "kind": "error",
        "signature": signature,
        "operation": operation,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "recoverable": getattr(exc, "recoverable", False),
        "context": error_context,
        "traceback": tb_text,
        "ts": now.isoformat(),
    }

    try:
        if db is not None:
            import uuid

            event_id = str(uuid.uuid4())
            db.insert_event(
                event_id=event_id,
                source=source,
                kind="error",
                ts=now.isoformat(),
                payload_metadata=json.dumps(payload),
                note=f"{operation}: {type(exc).__name__}",
            )
            return event_id

        # Imported lazily to avoid circular imports (storage -> alignment -> errors).
        from .storage import append_event

        append_event(Event(source=source, ts=now, payload_metadata=payload))
        return None
    except Exception as write_exc:  # noqa: BLE001
        # Elevate to warning - error recording failures should be visible in production
        logger.warning(
            "Failed to record error event for %s: %s (original error: %s)",
            operation,
            write_exc,
            type(exc).__name__,
        )
        return None


# =============================================================================
# Error Response Helpers
# =============================================================================


@dataclass
class ErrorResponse:
    """Structured error response for API/RPC layers."""

    error_type: str
    message: str
    recoverable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "error": {
                "type": self.error_type,
                "message": self.message,
                "recoverable": self.recoverable,
            }
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


def error_response(exc: Exception) -> ErrorResponse:
    """Convert an exception to a structured error response."""
    if isinstance(exc, TalkingRockError):
        return ErrorResponse(
            error_type=type(exc).__name__.lower().replace("error", ""),
            message=exc.message,
            recoverable=exc.recoverable,
            details=exc.context,
        )

    # Handle RPC errors from the RPC layer
    if hasattr(exc, "code") and hasattr(exc, "message"):
        return ErrorResponse(
            error_type="rpc",
            message=str(exc),
            recoverable=False,
            details={"code": getattr(exc, "code", None)},
        )

    # Unknown exception type
    return ErrorResponse(
        error_type="internal",
        message=str(exc) if str(exc) else "An unexpected error occurred",
        recoverable=False,
    )


# =============================================================================
# RPC Error Code Mapping
# =============================================================================


# Map domain errors to JSON-RPC error codes
ERROR_CODES: dict[type[TalkingRockError], int] = {
    ValidationError: -32000,
    PathValidationError: -32000,
    CommandValidationError: -32000,
    RateLimitError: -32001,
    AuthenticationError: -32002,
    AuthorizationError: -32002,
    NotFoundError: -32003,
    SafetyError: -32004,
    CircuitBreakerError: -32004,
    LLMError: -32010,
    LLMConnectionError: -32011,
    LLMTimeoutError: -32012,
    LLMModelError: -32013,
    DatabaseError: -32020,
    IntegrityError: -32021,
    MigrationError: -32022,
    ConfigurationError: -32030,
    ExecutionError: -32040,
    SandboxError: -32041,
}


def get_error_code(exc: TalkingRockError) -> int:
    """Get the JSON-RPC error code for a domain error."""
    # Check exact type first
    if type(exc) in ERROR_CODES:
        return ERROR_CODES[type(exc)]
    # Check parent types
    for error_type, code in ERROR_CODES.items():
        if isinstance(exc, error_type):
            return code
    # Default internal error
    return -32603
