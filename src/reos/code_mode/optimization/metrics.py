"""Execution metrics collection for RIVA optimization analysis.

This module provides metrics collection to understand where time and
tokens are being spent. Measure first, optimize second.

The goal is to identify:
- Where LLM calls are happening
- What decompositions could have been skipped
- What verifications could have been batched
- Overall success/failure patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """Metrics for a single RIVA execution session.

    Tracks timing, counts, and outcomes to inform optimization decisions.
    All fields are optional and only populated when relevant.
    """

    session_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    # Timing (milliseconds)
    total_duration_ms: int = 0
    llm_time_ms: int = 0
    verification_time_ms: int = 0
    execution_time_ms: int = 0

    # LLM call counts
    llm_calls_total: int = 0
    llm_calls_decomposition: int = 0
    llm_calls_action: int = 0
    llm_calls_verification: int = 0
    llm_calls_reflection: int = 0

    # Decomposition tracking
    decomposition_count: int = 0
    max_depth_reached: int = 0

    # Verification tracking
    verifications_total: int = 0
    verifications_high_risk: int = 0
    verifications_medium_risk: int = 0
    verifications_low_risk: int = 0

    # Retry tracking
    retry_count: int = 0
    failure_count: int = 0

    # Outcomes
    success: bool = False
    first_try_success: bool = False

    # Optimization analysis (what COULD have been optimized)
    # These are populated by analyzing the execution after the fact
    skippable_decompositions: int = 0  # Simple tasks that were decomposed
    skippable_verifications: int = 0  # Low-risk actions verified individually
    batchable_verifications: int = 0  # Verifications that could be batched

    # Token usage (if available from provider)
    tokens_input: int = 0
    tokens_output: int = 0

    def record_llm_call(
        self,
        purpose: str,
        duration_ms: int,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record an LLM call."""
        self.llm_calls_total += 1
        self.llm_time_ms += duration_ms
        self.tokens_input += tokens_in
        self.tokens_output += tokens_out

        if purpose == "decomposition":
            self.llm_calls_decomposition += 1
        elif purpose == "action":
            self.llm_calls_action += 1
        elif purpose == "verification":
            self.llm_calls_verification += 1
        elif purpose == "reflection":
            self.llm_calls_reflection += 1

    def record_decomposition(self, depth: int) -> None:
        """Record a decomposition event."""
        self.decomposition_count += 1
        self.max_depth_reached = max(self.max_depth_reached, depth)

    def record_verification(self, risk_level: str) -> None:
        """Record a verification event."""
        self.verifications_total += 1
        if risk_level == "high":
            self.verifications_high_risk += 1
        elif risk_level == "medium":
            self.verifications_medium_risk += 1
        elif risk_level == "low":
            self.verifications_low_risk += 1

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self.retry_count += 1

    def record_failure(self) -> None:
        """Record a failure."""
        self.failure_count += 1

    def complete(self, success: bool) -> None:
        """Mark execution as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.success = success
        self.total_duration_ms = int(
            (self.completed_at - self.started_at).total_seconds() * 1000
        )
        # First try success = no retries and succeeded
        self.first_try_success = success and self.retry_count == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/analysis."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "timing": {
                "total_ms": self.total_duration_ms,
                "llm_ms": self.llm_time_ms,
                "verification_ms": self.verification_time_ms,
                "execution_ms": self.execution_time_ms,
            },
            "llm_calls": {
                "total": self.llm_calls_total,
                "decomposition": self.llm_calls_decomposition,
                "action": self.llm_calls_action,
                "verification": self.llm_calls_verification,
                "reflection": self.llm_calls_reflection,
            },
            "decomposition": {
                "count": self.decomposition_count,
                "max_depth": self.max_depth_reached,
            },
            "verifications": {
                "total": self.verifications_total,
                "high_risk": self.verifications_high_risk,
                "medium_risk": self.verifications_medium_risk,
                "low_risk": self.verifications_low_risk,
            },
            "retries": self.retry_count,
            "failures": self.failure_count,
            "outcome": {
                "success": self.success,
                "first_try": self.first_try_success,
            },
            "optimization_potential": {
                "skippable_decompositions": self.skippable_decompositions,
                "skippable_verifications": self.skippable_verifications,
                "batchable_verifications": self.batchable_verifications,
            },
            "tokens": {
                "input": self.tokens_input,
                "output": self.tokens_output,
            },
        }

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Session {self.session_id}: "
            f"{'SUCCESS' if self.success else 'FAILED'} in {self.total_duration_ms}ms, "
            f"{self.llm_calls_total} LLM calls, "
            f"{self.decomposition_count} decompositions, "
            f"{self.verifications_total} verifications"
        )


def create_metrics(session_id: str) -> ExecutionMetrics:
    """Create a new metrics instance for a session."""
    return ExecutionMetrics(session_id=session_id)
