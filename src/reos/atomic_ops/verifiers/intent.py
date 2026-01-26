"""Intent verification layer.

Verifies that the operation matches the user's actual intent.
This is the only layer that uses LLM calls for verification.

Checks:
- Operation aligns with user's stated goals
- No obvious misinterpretation
- Context-appropriate response
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..models import (
    AtomicOperation,
    VerificationLayer,
    VerificationResult,
)
from .base import BaseVerifier, VerificationContext


class LLMProvider(Protocol):
    """Protocol for LLM providers used in intent verification."""

    def verify_intent(
        self,
        request: str,
        classification: dict,
        context: Optional[str] = None,
    ) -> tuple[bool, float, str]:
        """Verify that classification matches intent.

        Args:
            request: User's original request.
            classification: The system's classification.
            context: Optional context about user goals.

        Returns:
            Tuple of (aligned, confidence, reasoning).
        """
        ...


class IntentVerifier(BaseVerifier):
    """Verify operation matches user intent.

    This verifier uses LLM calls to verify that the system's
    interpretation of the request actually matches what the
    user intended. This is the final check before execution.

    If no LLM is available, falls back to heuristic checking.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        """Initialize intent verifier.

        Args:
            llm_provider: Optional LLM provider for intent verification.
        """
        self._llm = llm_provider

    @property
    def layer(self) -> VerificationLayer:
        return VerificationLayer.INTENT

    def set_llm_provider(self, provider: LLMProvider):
        """Set the LLM provider."""
        self._llm = provider

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify operation intent alignment."""
        # Try LLM verification if available
        if context.llm_available and self._llm is not None:
            return self._verify_with_llm(operation, context)

        # Fall back to heuristic verification
        return self._verify_heuristic(operation, context)

    def _verify_with_llm(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify intent using LLM."""
        if not operation.classification:
            return self._warn(
                ["No classification for intent verification"],
                confidence=0.5,
            )

        # Build context string from recent operations
        context_str = None
        if context.recent_operations:
            recent = context.recent_operations[:5]
            context_str = "Recent operations: " + ", ".join(
                op.user_request[:50] for op in recent
            )

        try:
            aligned, confidence, reasoning = self._llm.verify_intent(
                request=operation.user_request,
                classification={
                    "destination": operation.classification.destination.value,
                    "consumer": operation.classification.consumer.value,
                    "semantics": operation.classification.semantics.value,
                },
                context=context_str,
            )

            if aligned:
                return self._pass(
                    confidence=confidence,
                    details=f"Intent verified: {reasoning}",
                )
            else:
                return self._fail(
                    [f"Intent mismatch: {reasoning}"],
                    confidence=confidence,
                )

        except Exception as e:
            # LLM call failed - fall back to heuristic
            return self._verify_heuristic(operation, context)

    def _verify_heuristic(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify intent using heuristics (no LLM)."""
        issues = []

        if not operation.classification:
            return self._warn(
                ["Cannot verify intent without classification"],
                confidence=0.5,
            )

        # Check classification confidence
        if operation.classification.confidence < 0.6:
            issues.append(
                f"Low confidence ({operation.classification.confidence:.2f}) "
                "suggests possible misinterpretation"
            )

        # Check for obvious mismatches
        request_lower = operation.user_request.lower()

        # Question classified as execute
        if "?" in operation.user_request:
            if operation.classification.semantics.value == "execute":
                issues.append("Question classified as execute action")

        # Destructive words classified as read
        destructive_words = ["delete", "remove", "kill", "stop", "clear"]
        has_destructive = any(w in request_lower for w in destructive_words)
        if has_destructive and operation.classification.semantics.value == "read":
            issues.append("Destructive action classified as read-only")

        # Read words classified as execute
        read_words = ["show", "display", "list", "what is", "what are"]
        has_read = any(w in request_lower for w in read_words)
        if has_read and operation.classification.semantics.value == "execute":
            if not any(w in request_lower for w in destructive_words):
                issues.append("Read request classified as execute action")

        # Check for context consistency
        if context.recent_operations:
            context_issues = self._check_context_consistency(
                operation, context.recent_operations
            )
            issues.extend(context_issues)

        # Calculate confidence
        confidence = operation.classification.confidence
        if issues:
            confidence *= 0.7

        if issues:
            return self._warn(issues, confidence=confidence)

        return self._pass(
            confidence=confidence,
            details="Intent appears aligned (heuristic check)",
        )

    def _check_context_consistency(
        self,
        operation: AtomicOperation,
        recent_ops: list[AtomicOperation],
    ) -> list[str]:
        """Check if operation is consistent with recent context."""
        issues = []

        if not recent_ops:
            return issues

        # Check for sudden context switches
        last_op = recent_ops[0]
        if last_op.source_agent and operation.source_agent:
            if last_op.source_agent != operation.source_agent:
                # Agent switch - not necessarily an issue, but note it
                pass

        # Check for repeated operations (possible confusion)
        request_lower = operation.user_request.lower().strip()
        similar_count = sum(
            1 for op in recent_ops[:3]
            if op.user_request.lower().strip() == request_lower
        )
        if similar_count >= 2:
            issues.append("Repeated request - possible retry or confusion")

        return issues
