"""Health Pulse RPC handlers.

Endpoints for the frontend to poll health status, view findings,
and acknowledge/snooze health findings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from reos.db import Database

from . import RpcError
from .play import get_current_play_path

logger = logging.getLogger(__name__)


def _get_health_components(db: Database) -> tuple:
    """Get health runner, anti-nag, and store for the current play.

    Returns:
        Tuple of (runner, anti_nag, store) or raises RpcError.
    """
    from reos.cairn.health.anti_nag import AntiNagProtocol
    from reos.cairn.health.checks.act_vitality import ActVitalityCheck
    from reos.cairn.health.checks.context_freshness import ContextFreshnessCheck
    from reos.cairn.health.checks.data_integrity import DataIntegrityCheck
    from reos.cairn.health.runner import HealthCheckRunner
    from reos.cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32603, message="No active play")

    cairn_db_path = Path(play_path) / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db_path)

    # Build runner with Phase 1 checks
    runner = HealthCheckRunner()
    runner.register(ContextFreshnessCheck(store))
    runner.register(ActVitalityCheck(store))
    runner.register(DataIntegrityCheck(cairn_db_path))

    # Try to register Phase 2+ checks if available
    try:
        from reos.cairn.health.checks.correction_intake import CorrectionIntakeCheck
        runner.register(CorrectionIntakeCheck(db))
    except ImportError:
        pass

    try:
        from reos.cairn.health.checks.signal_quality import SignalQualityCheck
        runner.register(SignalQualityCheck(db))
    except ImportError:
        pass

    try:
        from reos.cairn.health.checks.preference_alignment import PreferenceAlignmentCheck
        runner.register(PreferenceAlignmentCheck(store))
    except ImportError:
        pass

    try:
        from reos.cairn.health.checks.pattern_currency import PatternCurrencyCheck
        runner.register(PatternCurrencyCheck(db))
    except ImportError:
        pass

    try:
        from reos.cairn.health.checks.software_currency import SoftwareCurrencyCheck
        runner.register(SoftwareCurrencyCheck())
    except ImportError:
        pass

    try:
        from reos.cairn.health.checks.security_posture import SecurityPostureCheck
        runner.register(SecurityPostureCheck())
    except ImportError:
        pass

    # Anti-nag needs a connection
    conn = store._get_connection()
    anti_nag = AntiNagProtocol(conn)

    return runner, anti_nag, store


def handle_health_status(db: Database) -> dict[str, Any]:
    """Lightweight health status for UI polling.

    Returns:
        Dict with overall_severity, finding_count, unacknowledged_count.
    """
    try:
        runner, anti_nag, _ = _get_health_components(db)
        status = runner.get_status_summary()
        unack = anti_nag.get_unacknowledged_count()

        return {
            "overall_severity": status.overall_severity.value,
            "finding_count": status.finding_count,
            "unacknowledged_count": unack,
        }
    except Exception as e:
        logger.debug("Health status check failed: %s", e)
        return {
            "overall_severity": "healthy",
            "finding_count": 0,
            "unacknowledged_count": 0,
        }


def handle_health_findings(db: Database) -> dict[str, Any]:
    """Full health findings list for the health detail view.

    Returns:
        Dict with findings list and summary.
    """
    try:
        runner, anti_nag, _ = _get_health_components(db)
        findings = runner.get_findings()
        status = runner.get_status_summary()

        return {
            "findings": [f.to_dict() for f in findings],
            "overall_severity": status.overall_severity.value,
            "finding_count": len(findings),
            "unacknowledged_count": anti_nag.get_unacknowledged_count(),
        }
    except Exception as e:
        logger.debug("Health findings check failed: %s", e)
        return {
            "findings": [],
            "overall_severity": "healthy",
            "finding_count": 0,
            "unacknowledged_count": 0,
        }


def handle_health_acknowledge(db: Database, *, log_id: str) -> dict[str, Any]:
    """Acknowledge a health finding.

    Args:
        db: Database instance.
        log_id: The surfacing log entry ID to acknowledge.

    Returns:
        Dict with success status.
    """
    _, anti_nag, _ = _get_health_components(db)
    success = anti_nag.acknowledge(log_id)
    return {"success": success}
