"""Pattern Currency Check — Has the classification distribution shifted?

Compares classification distributions: baseline (60d) vs recent (7d).
Uses total variation distance to measure drift magnitude.
Logs drift events when magnitude > 15%.

This catches LLM model updates or user behavior changes that cause
the classification system to produce different distributions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)


class PatternCurrencyCheck:
    """Check for classification distribution drift."""

    name = "pattern_currency"

    BASELINE_DAYS = 60
    RECENT_DAYS = 7
    MINIMUM_OPERATIONS = 20  # Minimum ops in both windows
    WARNING_THRESHOLD = 0.15  # 15% total variation distance
    CRITICAL_THRESHOLD = 0.30  # 30% total variation distance

    def __init__(self, db: Any) -> None:
        """Initialize with the main ReOS Database object."""
        self._db = db

    def run(self) -> list[HealthCheckResult]:
        """Run the pattern currency check."""
        try:
            conn = self._db.connect()
            now = datetime.now()
            baseline_start = (now - timedelta(days=self.BASELINE_DAYS)).isoformat()
            recent_start = (now - timedelta(days=self.RECENT_DAYS)).isoformat()
            recent_start_baseline_end = recent_start  # Baseline excludes recent window

            # Get baseline distribution (60d ago to 7d ago)
            baseline_dist = self._get_distribution(
                conn, baseline_start, recent_start_baseline_end
            )

            # Get recent distribution (last 7d)
            recent_dist = self._get_distribution(conn, recent_start, now.isoformat())

        except Exception as e:
            logger.debug("Pattern currency check failed: %s", e)
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Classification history not yet available",
                finding_key=f"{self.name}:unavailable",
            )]

        baseline_total = sum(baseline_dist.values())
        recent_total = sum(recent_dist.values())

        if baseline_total < self.MINIMUM_OPERATIONS or recent_total < self.MINIMUM_OPERATIONS:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Not enough data for drift detection",
                details=(
                    f"Baseline: {baseline_total} ops, Recent: {recent_total} ops. "
                    f"Need {self.MINIMUM_OPERATIONS}+ in each window."
                ),
                finding_key=f"{self.name}:insufficient_data",
            )]

        # Calculate total variation distance
        tvd = self._total_variation_distance(baseline_dist, recent_dist)

        if tvd >= self.CRITICAL_THRESHOLD:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.CRITICAL,
                title=f"Significant classification drift detected ({tvd:.0%})",
                details=(
                    "The distribution of classification types has shifted significantly "
                    "compared to the baseline period. This may indicate a model update "
                    "or a change in usage patterns."
                ),
                finding_key=f"{self.name}:critical:{tvd:.2f}",
            )]

        if tvd >= self.WARNING_THRESHOLD:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title=f"Mild classification drift detected ({tvd:.0%})",
                details=(
                    "The distribution of classification types has shifted slightly "
                    "compared to the baseline period. Worth monitoring."
                ),
                finding_key=f"{self.name}:warning:{tvd:.2f}",
            )]

        return [HealthCheckResult(
            check_name=self.name,
            severity=Severity.HEALTHY,
            title="Classification patterns stable",
            finding_key=f"{self.name}:ok",
        )]

    def _get_distribution(
        self,
        conn: Any,
        start: str,
        end: str,
    ) -> dict[str, int]:
        """Get classification type distribution for a time window."""
        cursor = conn.execute("""
            SELECT
                destination_type || '/' || consumer_type || '/' || execution_semantics as combo,
                COUNT(*) as cnt
            FROM atomic_operations
            WHERE created_at >= ? AND created_at < ?
            GROUP BY combo
        """, (start, end))

        return {row[0]: row[1] for row in cursor.fetchall()}

    @staticmethod
    def _total_variation_distance(
        dist1: dict[str, int],
        dist2: dict[str, int],
    ) -> float:
        """Compute total variation distance between two distributions.

        TVD = 0.5 * sum(|p(x) - q(x)|) for all categories x.
        Range: 0.0 (identical) to 1.0 (completely different).
        """
        all_keys = set(dist1.keys()) | set(dist2.keys())
        total1 = sum(dist1.values()) or 1
        total2 = sum(dist2.values()) or 1

        tvd = 0.0
        for key in all_keys:
            p = dist1.get(key, 0) / total1
            q = dist2.get(key, 0) / total2
            tvd += abs(p - q)

        return tvd / 2.0
