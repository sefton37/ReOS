"""Base verifier interface and common types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
import time

from ..models import AtomicOperation, VerificationLayer, VerificationResult


@dataclass
class VerificationContext:
    """Context provided to verifiers.

    Contains information about the user, system state, and
    recent operations that verifiers may use.
    """
    user_id: str
    source_agent: str

    # User preferences and history
    user_preferences: dict[str, Any] = field(default_factory=dict)
    recent_operations: list[AtomicOperation] = field(default_factory=list)

    # System state
    current_directory: str = ""
    environment_vars: dict[str, str] = field(default_factory=dict)
    available_commands: set[str] = field(default_factory=set)

    # Safety configuration
    safety_level: str = "standard"  # "permissive", "standard", "strict"
    blocked_commands: set[str] = field(default_factory=set)
    allowed_paths: list[str] = field(default_factory=list)

    # LLM access (for intent verification)
    llm_available: bool = False
    llm_model: Optional[str] = None


class BaseVerifier(ABC):
    """Base class for all verifiers.

    Each verifier implements a single layer of the 5-layer
    verification system. Verifiers should be fast and focused.
    """

    @property
    @abstractmethod
    def layer(self) -> VerificationLayer:
        """The verification layer this verifier implements."""
        pass

    @abstractmethod
    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify an operation.

        Args:
            operation: The operation to verify.
            context: Verification context with user/system state.

        Returns:
            VerificationResult with pass/fail status and details.
        """
        pass

    def _timed_verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Wrapper that tracks execution time."""
        start_time = time.time()
        result = self.verify(operation, context)
        elapsed_ms = int((time.time() - start_time) * 1000)
        result.execution_time_ms = elapsed_ms
        return result

    def _pass(
        self,
        confidence: float = 1.0,
        details: str = "",
    ) -> VerificationResult:
        """Create a passing result."""
        return VerificationResult(
            layer=self.layer,
            passed=True,
            confidence=confidence,
            details=details,
        )

    def _fail(
        self,
        issues: list[str],
        confidence: float = 1.0,
        details: str = "",
    ) -> VerificationResult:
        """Create a failing result."""
        return VerificationResult(
            layer=self.layer,
            passed=False,
            confidence=confidence,
            issues=issues,
            details=details,
        )

    def _warn(
        self,
        issues: list[str],
        confidence: float = 0.7,
        details: str = "",
    ) -> VerificationResult:
        """Create a passing result with warnings."""
        return VerificationResult(
            layer=self.layer,
            passed=True,
            confidence=confidence,
            issues=issues,
            details=details,
        )
