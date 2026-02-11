"""Correction Intake Check — Is the classification system learning from feedback?

Uses AtomicOpsStore.get_classification_stats() to check correction rates.
Thresholds: <15% healthy, 15-30% warning, >30% critical.
Graceful "not enough data" fallback for <10 operations.
"""

from __future__ import annotations

import logging
from typing import Any

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)


class CorrectionIntakeCheck:
    """Check classification correction rates."""

    name = "correction_intake"

    MINIMUM_OPERATIONS = 10  # Need at least this many ops for meaningful stats
    WARNING_THRESHOLD = 0.15  # 15% correction rate = warning
    CRITICAL_THRESHOLD = 0.30  # 30% correction rate = critical

    def __init__(self, db: Any) -> None:
        """Initialize with the main ReOS Database object."""
        self._db = db

    def run(self) -> list[HealthCheckResult]:
        """Run the correction intake check."""
        try:
            from reos.atomic_ops.schema import AtomicOpsStore

            conn = self._db.connect()
            store = AtomicOpsStore(conn)
            stats = store.get_classification_stats("local")
        except Exception as e:
            logger.debug("Correction intake check failed: %s", e)
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Classification feedback not yet available",
                finding_key=f"{self.name}:unavailable",
            )]

        total_ops = stats.get("total_operations", 0)
        feedback_count = stats.get("feedback_count", 0)
        correction_rate = stats.get("correction_rate", 0.0)

        if total_ops < self.MINIMUM_OPERATIONS:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title=f"Not enough data yet ({total_ops} operations)",
                details="Need at least 10 operations for meaningful feedback analysis.",
                finding_key=f"{self.name}:insufficient_data",
            )]

        if correction_rate >= self.CRITICAL_THRESHOLD:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.CRITICAL,
                title=f"High correction rate: {correction_rate:.0%}",
                details=(
                    f"Out of {feedback_count} feedback entries, {correction_rate:.0%} required "
                    "corrections. The classification system may need retuning."
                ),
                finding_key=f"{self.name}:high:{correction_rate:.2f}",
            )]

        if correction_rate >= self.WARNING_THRESHOLD:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title=f"Moderate correction rate: {correction_rate:.0%}",
                details=(
                    f"Out of {feedback_count} feedback entries, {correction_rate:.0%} required "
                    "corrections. Worth monitoring."
                ),
                finding_key=f"{self.name}:moderate:{correction_rate:.2f}",
            )]

        return [HealthCheckResult(
            check_name=self.name,
            severity=Severity.HEALTHY,
            title=f"Classification accuracy: {1 - correction_rate:.0%}",
            finding_key=f"{self.name}:ok",
        )]
