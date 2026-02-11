"""Context Freshness Check — Are Acts being maintained?

Checks cairn_metadata.last_touched for each active Act.
Thresholds: <14d healthy, 14-30d warning, 30d+ critical.

Reframe Protocol: Messages frame staleness as system limitation
("I may have outdated context"), never user failure.
"""

from __future__ import annotations

from datetime import datetime

from reos.cairn.health.runner import HealthCheckResult, Severity
from reos.cairn.store import CairnStore


class ContextFreshnessCheck:
    """Check freshness of context for active Acts."""

    name = "context_freshness"

    WARNING_DAYS = 14
    CRITICAL_DAYS = 30

    def __init__(self, store: CairnStore) -> None:
        self._store = store

    def run(self) -> list[HealthCheckResult]:
        """Run the freshness check across all Act metadata."""
        results: list[HealthCheckResult] = []

        # Get all act metadata
        act_metadata = self._store.list_metadata(entity_type="act", limit=500)

        if not act_metadata:
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="No Acts tracked yet",
                finding_key=f"{self.name}:no_acts",
            ))
            return results

        now = datetime.now()
        stale_acts: list[tuple[str, int]] = []  # (entity_id, days_stale)

        for meta in act_metadata:
            if meta.last_touched is None:
                days = 999
            else:
                days = (now - meta.last_touched).days

            if days >= self.WARNING_DAYS:
                stale_acts.append((meta.entity_id, days))

        if not stale_acts:
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="All Acts have recent context",
                finding_key=f"{self.name}:all_fresh",
            ))
            return results

        # Determine worst severity
        worst_days = max(days for _, days in stale_acts)
        if worst_days >= self.CRITICAL_DAYS:
            severity = Severity.CRITICAL
        else:
            severity = Severity.WARNING

        # Build details with Reframe Protocol language
        act_lines = []
        for entity_id, days in sorted(stale_acts, key=lambda x: -x[1]):
            act_lines.append(f"  - Act {entity_id[:8]}...: {days} days since last touch")

        details = (
            f"My context for {len(stale_acts)} Act(s) may be outdated. "
            "I work best with fresh information.\n"
            + "\n".join(act_lines)
        )

        results.append(HealthCheckResult(
            check_name=self.name,
            severity=severity,
            title=f"{len(stale_acts)} Act(s) have stale context",
            details=details,
            finding_key=f"{self.name}:stale:{len(stale_acts)}:{worst_days}",
        ))

        return results
