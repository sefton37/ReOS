"""Signal Quality Check — Is the user engaging deliberately with approvals?

Reads user_feedback.time_to_decision_ms to detect patterns:
- Rapid-fire approvals (<1s) suggest rubber-stamping
- Very slow approvals (>30s) suggest confusion
- Healthy: mix of deliberate review times

Reframe Protocol: "Some approvals seem very quick — the system may not be
giving you enough time to review."
"""

from __future__ import annotations

import logging
from typing import Any

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)


class SignalQualityCheck:
    """Check quality of user feedback signals."""

    name = "signal_quality"

    MINIMUM_FEEDBACK = 10  # Need at least this many for analysis
    RAPID_THRESHOLD_MS = 1000  # <1 second = rapid approval
    RAPID_PROPORTION_WARNING = 0.5  # >50% rapid = warning

    def __init__(self, db: Any) -> None:
        """Initialize with the main ReOS Database object."""
        self._db = db

    def run(self) -> list[HealthCheckResult]:
        """Run the signal quality check."""
        try:
            conn = self._db.connect()
            cursor = conn.execute("""
                SELECT time_to_decision_ms
                FROM user_feedback
                WHERE time_to_decision_ms IS NOT NULL
                    AND feedback_type = 'approval'
                ORDER BY created_at DESC
                LIMIT 100
            """)
            times = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.debug("Signal quality check failed: %s", e)
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Approval timing data not yet available",
                finding_key=f"{self.name}:unavailable",
            )]

        if len(times) < self.MINIMUM_FEEDBACK:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title=f"Not enough data yet ({len(times)} approvals)",
                finding_key=f"{self.name}:insufficient_data",
            )]

        rapid_count = sum(1 for t in times if t < self.RAPID_THRESHOLD_MS)
        rapid_proportion = rapid_count / len(times) if times else 0

        if rapid_proportion >= self.RAPID_PROPORTION_WARNING:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title=f"{rapid_proportion:.0%} of approvals are very quick (<1s)",
                details=(
                    f"{rapid_count} of {len(times)} recent approvals took less than 1 second. "
                    "The system may not be giving enough time to review classifications."
                ),
                finding_key=f"{self.name}:rapid:{rapid_proportion:.2f}",
            )]

        return [HealthCheckResult(
            check_name=self.name,
            severity=Severity.HEALTHY,
            title="Approval patterns look deliberate",
            finding_key=f"{self.name}:ok",
        )]
