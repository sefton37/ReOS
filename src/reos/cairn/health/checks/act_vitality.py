"""Act Vitality Check — Are active Acts actually progressing?

Finds Acts marked active (have CAIRN metadata) but with no scene activity
in N days. This surfaces Acts that may be stalled.

Reframe Protocol: "This Act hasn't had scene activity recently —
it might be waiting for you when you're ready."
"""

from __future__ import annotations

from datetime import datetime, timedelta

from reos.cairn.health.runner import HealthCheckResult, Severity
from reos.cairn.store import CairnStore


class ActVitalityCheck:
    """Check that active Acts have recent scene activity."""

    name = "act_vitality"

    STALE_DAYS = 14  # No scene activity in this many days = warning

    def __init__(self, store: CairnStore) -> None:
        self._store = store

    def run(self) -> list[HealthCheckResult]:
        """Run the vitality check."""
        results: list[HealthCheckResult] = []

        # Get all act metadata entries
        act_metadata = self._store.list_metadata(entity_type="act", limit=500)

        if not act_metadata:
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="No Acts tracked",
                finding_key=f"{self.name}:no_acts",
            ))
            return results

        now = datetime.now()
        cutoff = now - timedelta(days=self.STALE_DAYS)
        stalled_acts: list[str] = []

        for act_meta in act_metadata:
            # Check if any scenes under this act have recent activity
            scene_metadata = self._store.list_metadata(entity_type="scene", limit=500)
            has_recent_scene = False

            for scene_meta in scene_metadata:
                # We check activity log for scenes that touched this act
                activities = self._store.get_activity_log(
                    entity_type="scene",
                    entity_id=scene_meta.entity_id,
                    since=cutoff,
                    limit=1,
                )
                if activities:
                    has_recent_scene = True
                    break

            if not has_recent_scene:
                # Also check if the act itself was touched recently
                if act_meta.last_touched and act_meta.last_touched >= cutoff:
                    continue
                stalled_acts.append(act_meta.entity_id)

        if not stalled_acts:
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="All tracked Acts show recent activity",
                finding_key=f"{self.name}:all_vital",
            ))
            return results

        details = (
            f"{len(stalled_acts)} Act(s) haven't had scene activity in "
            f"{self.STALE_DAYS}+ days. They might be waiting for you when you're ready.\n"
        )
        for act_id in stalled_acts:
            details += f"  - Act {act_id[:8]}...\n"

        results.append(HealthCheckResult(
            check_name=self.name,
            severity=Severity.WARNING,
            title=f"{len(stalled_acts)} Act(s) may need attention",
            details=details.rstrip(),
            finding_key=f"{self.name}:stalled:{len(stalled_acts)}",
        ))

        return results
