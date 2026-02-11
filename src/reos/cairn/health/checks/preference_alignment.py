"""Preference Alignment Check — Do stated priorities match actual behavior?

Compares cairn_metadata.priority (stated importance) against activity_log
(demonstrated engagement). Surfaces high-priority Acts with no recent activity.

Reframe Protocol: "Some high-priority items haven't seen activity recently —
they're ready when you are."
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from reos.cairn.health.runner import HealthCheckResult, Severity
from reos.cairn.store import CairnStore

logger = logging.getLogger(__name__)


class PreferenceAlignmentCheck:
    """Check that high-priority items have matching activity."""

    name = "preference_alignment"

    INACTIVITY_DAYS = 14  # Days without activity for high-priority to trigger

    def __init__(self, store: CairnStore) -> None:
        self._store = store

    def run(self) -> list[HealthCheckResult]:
        """Run the preference alignment check."""
        # Get items with priority set
        all_metadata = self._store.list_metadata(has_priority=True, limit=500)

        if not all_metadata:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="No prioritized items to check",
                finding_key=f"{self.name}:no_priorities",
            )]

        # Find high-priority items (4-5) with no recent activity
        cutoff = datetime.now() - timedelta(days=self.INACTIVITY_DAYS)
        misaligned: list[tuple[str, str, int]] = []  # (type, id, priority)

        for meta in all_metadata:
            if meta.priority is not None and meta.priority >= 4:
                # Check if there's recent activity
                if meta.last_touched and meta.last_touched >= cutoff:
                    continue

                misaligned.append((meta.entity_type, meta.entity_id, meta.priority))

        if not misaligned:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Priorities align with activity",
                finding_key=f"{self.name}:aligned",
            )]

        details_lines = []
        for entity_type, entity_id, priority in misaligned:
            details_lines.append(
                f"  - {entity_type} {entity_id[:8]}... (priority {priority})"
            )

        return [HealthCheckResult(
            check_name=self.name,
            severity=Severity.WARNING,
            title=f"{len(misaligned)} high-priority item(s) haven't seen activity",
            details=(
                f"These items are marked priority 4-5 but haven't been touched in "
                f"{self.INACTIVITY_DAYS}+ days. They're ready when you are.\n"
                + "\n".join(details_lines)
            ),
            finding_key=f"{self.name}:misaligned:{len(misaligned)}",
        )]
