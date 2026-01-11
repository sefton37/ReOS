"""Batch verification for reduced LLM calls.

This module batches multiple verifications into single LLM calls.
Instead of verifying each action individually, we verify the
plan as a whole and check multiple outcomes at once.

Goal: 50% reduction in verification-related LLM calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.intention import Action
    from reos.providers import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class DeferredVerification:
    """A verification to run later in batch.

    Attributes:
        action: The action that was executed
        result: The result of execution
        expected: What we expected to happen
    """

    action: "Action"
    result: str
    expected: str


@dataclass
class BatchVerificationResult:
    """Result of a batch verification.

    Attributes:
        success: Whether all verifications passed
        results: Individual results for each verification
        failures: List of failed verifications
    """

    success: bool
    results: list[tuple[DeferredVerification, bool]]
    failures: list[DeferredVerification]

    @property
    def passed_count(self) -> int:
        return sum(1 for _, passed in self.results if passed)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


class VerificationBatcher:
    """Batch multiple verifications together.

    Usage:
        batcher = VerificationBatcher(llm)

        # During execution, defer low-risk verifications
        batcher.defer(action1, result1, "file created")
        batcher.defer(action2, result2, "function added")

        # At intention boundary, flush and check
        batch_result = batcher.flush()
        if not batch_result.success:
            # Handle failures
            for failed in batch_result.failures:
                logger.error("Verification failed: %s", failed.expected)
    """

    def __init__(self, llm: "LLMProvider | None" = None):
        """Initialize the batcher.

        Args:
            llm: LLM provider for batch verification. If None, uses heuristics.
        """
        self.llm = llm
        self.deferred: list[DeferredVerification] = []

    def defer(
        self,
        action: "Action",
        result: str,
        expected: str,
    ) -> None:
        """Defer a verification for later batch processing.

        Args:
            action: The action that was executed
            result: The result of execution
            expected: What we expected to happen
        """
        self.deferred.append(DeferredVerification(
            action=action,
            result=result,
            expected=expected,
        ))
        logger.debug(
            "Deferred verification: %s (total: %d)",
            expected[:30],
            len(self.deferred),
        )

    def flush(self) -> BatchVerificationResult:
        """Run all deferred verifications in batch.

        Returns:
            BatchVerificationResult with all outcomes
        """
        if not self.deferred:
            return BatchVerificationResult(success=True, results=[], failures=[])

        logger.info("Flushing %d deferred verifications", len(self.deferred))

        if self.llm:
            results = self._verify_with_llm()
        else:
            results = self._verify_with_heuristics()

        # Collect failures
        failures = [v for v, passed in results if not passed]

        self.deferred = []  # Clear after flush

        return BatchVerificationResult(
            success=len(failures) == 0,
            results=results,
            failures=failures,
        )

    def clear(self) -> None:
        """Clear all deferred verifications without running them."""
        count = len(self.deferred)
        self.deferred = []
        logger.debug("Cleared %d deferred verifications", count)

    def _verify_with_llm(self) -> list[tuple[DeferredVerification, bool]]:
        """Verify all deferred items with a single LLM call."""
        prompt = self._build_batch_prompt()

        system = """You are verifying multiple code execution outcomes.
For each item, determine if the result matches the expected outcome.
Respond with a JSON array of booleans, one for each item.
Example: [true, true, false, true]"""

        try:
            response = self.llm.chat_json(
                system=system,
                user=prompt,
                timeout_seconds=30.0,
            )

            # Parse response as list of booleans
            if isinstance(response, list):
                results = [bool(r) for r in response]
            else:
                # Fallback to heuristics if response is unexpected
                logger.warning("Unexpected LLM response format, using heuristics")
                return self._verify_with_heuristics()

            # Match results to deferred items
            return list(zip(self.deferred, results))

        except Exception as e:
            logger.warning("Batch verification LLM failed: %s, using heuristics", e)
            return self._verify_with_heuristics()

    def _verify_with_heuristics(self) -> list[tuple[DeferredVerification, bool]]:
        """Verify using heuristics when LLM unavailable."""
        results = []

        for v in self.deferred:
            passed = self._heuristic_verify(v)
            results.append((v, passed))

        return results

    def _heuristic_verify(self, v: DeferredVerification) -> bool:
        """Heuristic verification of a single item."""
        result_lower = v.result.lower()
        expected_lower = v.expected.lower()

        # Check for clear failure indicators
        failure_indicators = [
            "error",
            "exception",
            "traceback",
            "failed",
            "permission denied",
            "not found",
            "does not exist",
        ]
        if any(ind in result_lower for ind in failure_indicators):
            return False

        # Check for success indicators
        success_indicators = [
            "success",
            "created",
            "done",
            "complete",
            "written",
            "added",
        ]
        if any(ind in result_lower for ind in success_indicators):
            return True

        # Check if expected outcome mentioned in result
        expected_words = expected_lower.split()
        matches = sum(1 for w in expected_words if w in result_lower)
        if matches > len(expected_words) * 0.5:
            return True

        # Default: assume failure if unclear
        return False

    def _build_batch_prompt(self) -> str:
        """Build a single prompt to verify multiple actions."""
        items = []
        for i, v in enumerate(self.deferred):
            items.append(f"Item {i+1}:")
            items.append(f"  Action: {v.action.type.value}")
            items.append(f"  Expected: {v.expected}")
            items.append(f"  Result: {v.result[:200]}")
            items.append("")

        return "\n".join(items)

    @property
    def pending_count(self) -> int:
        """Number of pending verifications."""
        return len(self.deferred)

    def has_pending(self) -> bool:
        """Are there pending verifications?"""
        return len(self.deferred) > 0
