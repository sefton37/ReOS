"""Session-level trust budget for dynamic verification cadence.

This module implements a trust budget system that adjusts verification
strictness based on session history. Start with trust, deplete on
failures, replenish on success.

Philosophy: Don't be maximally paranoid about everything.
Verify more when trust is low, less when trust is high.

The budget has a hard floor - we never skip HIGH risk verification.

Cost Model
----------
Trust is "spent" when skipping verification (you're gambling):
    - Skip LOW risk: -2 trust
    - Skip MEDIUM risk: -7 trust
    - Skip HIGH risk: (never allowed)

Trust is "earned" when verification succeeds:
    - Immediate verify + success: +10 trust (via replenish())
    - Batch verify + success: +3 per item (called from intention.py)
    - Catch failure: +5 trust (system working correctly)

Trust is "lost" when verification fails or is missed:
    - Batch failure: -20 trust (via deplete())
    - Missed failure: -20 trust

Thresholds:
    - LOW risk can skip when trust > 70
    - MEDIUM risk can skip when trust > 85
    - Floor is 20 (never go below, always verify at floor)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.optimization.risk import ActionRisk, RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class TrustBudget:
    """Session-level trust budget.

    Tracks trust level through the session and determines
    when verification can be relaxed.

    Attributes:
        initial: Starting trust budget
        remaining: Current trust budget
        floor: Minimum trust level (never go below this)
        verifications_skipped: Count of skipped verifications
        verifications_performed: Count of performed verifications
        failures_caught: Failures caught by verification
        failures_missed: Failures that slipped through
    """

    initial: int = 100
    remaining: int = 100
    floor: int = 20  # Never go below this

    # Statistics
    verifications_skipped: int = 0
    verifications_performed: int = 0
    failures_caught: int = 0
    failures_missed: int = 0

    # History for analysis
    _history: list[dict] = field(default_factory=list)

    def should_verify(self, risk: "ActionRisk") -> bool:
        """Should we verify this action?

        Args:
            risk: Risk assessment for the action

        Returns:
            True if we should verify, False if we can skip
        """
        from reos.code_mode.optimization.risk import RiskLevel

        cost = self._risk_cost(risk.level)

        # Always verify HIGH risk regardless of budget
        if risk.level == RiskLevel.HIGH:
            self._record("verify", "high_risk_always_verify", cost)
            self.verifications_performed += 1
            return True

        # Below floor: must verify everything
        if self.remaining <= self.floor:
            self._record("verify", "below_floor", cost)
            self.verifications_performed += 1
            return True

        # LOW risk with good budget: can skip
        if risk.level == RiskLevel.LOW and self.remaining > 70:
            self.remaining -= cost // 2  # Partial cost for skipping
            self._record("skip", "low_risk_high_budget", cost // 2)
            logger.info(
                "Skipping verification: LOW risk, trust=%d (factors: %s)",
                self.remaining,
                ", ".join(risk.factors) if risk.factors else "none",
            )
            self.verifications_skipped += 1
            return False

        # MEDIUM risk with good budget: can sometimes skip
        if risk.level == RiskLevel.MEDIUM and self.remaining > 85:
            self.remaining -= cost // 2
            self._record("skip", "medium_risk_very_high_budget", cost // 2)
            logger.info(
                "Skipping verification: MEDIUM risk, trust=%d (factors: %s)",
                self.remaining,
                ", ".join(risk.factors) if risk.factors else "none",
            )
            self.verifications_skipped += 1
            return False

        # Default: verify
        self._record("verify", "default", cost)
        self.verifications_performed += 1
        return True

    def replenish(self, amount: int = 10) -> None:
        """Successful execution replenishes trust.

        Call after a verified action succeeds.
        """
        old = self.remaining
        self.remaining = min(self.initial, self.remaining + amount)
        self._record("replenish", f"+{amount}", self.remaining - old)
        logger.debug("Trust replenished: %d -> %d", old, self.remaining)

    def deplete(self, amount: int = 20) -> None:
        """Failed execution depletes trust.

        Call when an action fails, especially if verification was skipped.
        """
        old = self.remaining
        self.remaining = max(self.floor, self.remaining - amount)
        self.failures_missed += 1
        self._record("deplete", f"-{amount}", old - self.remaining)
        logger.warning("Trust depleted: %d -> %d", old, self.remaining)

    def record_failure_caught(self) -> None:
        """Record that verification caught a failure.

        This is good - verification is working.
        """
        self.failures_caught += 1
        # Small replenishment for verification working correctly
        self.replenish(5)

    def _risk_cost(self, level: "RiskLevel") -> int:
        """Get the trust cost for a risk level."""
        from reos.code_mode.optimization.risk import RiskLevel

        return {
            RiskLevel.LOW: 5,
            RiskLevel.MEDIUM: 15,
            RiskLevel.HIGH: 30,
        }[level]

    def _record(self, action: str, reason: str, delta: int) -> None:
        """Record action for history/debugging."""
        self._history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "reason": reason,
            "delta": delta,
            "remaining": self.remaining,
        })

    @property
    def trust_level(self) -> float:
        """Current trust level as percentage."""
        return self.remaining / self.initial

    @property
    def is_low_trust(self) -> bool:
        """Are we in low trust mode?"""
        return self.remaining <= 50

    @property
    def is_high_trust(self) -> bool:
        """Are we in high trust mode?"""
        return self.remaining >= 80

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Trust: {self.remaining}/{self.initial} "
            f"(verified={self.verifications_performed}, "
            f"skipped={self.verifications_skipped}, "
            f"caught={self.failures_caught}, "
            f"missed={self.failures_missed})"
        )

    def to_dict(self) -> dict:
        """Serialize for logging/storage."""
        return {
            "initial": self.initial,
            "remaining": self.remaining,
            "floor": self.floor,
            "trust_level": self.trust_level,
            "statistics": {
                "verifications_performed": self.verifications_performed,
                "verifications_skipped": self.verifications_skipped,
                "failures_caught": self.failures_caught,
                "failures_missed": self.failures_missed,
            },
            "history": self._history[-20:],  # Last 20 events
        }


def create_trust_budget(
    initial: int = 100,
    floor: int = 20,
) -> TrustBudget:
    """Create a new trust budget for a session.

    Args:
        initial: Starting trust level (default 100)
        floor: Minimum trust level (default 20)

    Returns:
        New TrustBudget instance
    """
    return TrustBudget(initial=initial, remaining=initial, floor=floor)
