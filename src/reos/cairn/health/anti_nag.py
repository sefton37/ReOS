"""Anti-Nag Protocol — Rate limiting and deduplication for health surfacing.

The master dialectic: "The system genuinely needs you AND must never coerce you."

This module ensures health findings are surfaced respectfully:
- Rate limiting per check (min interval between surfacing)
- Session-level caps (max surfacings per session)
- Deduplication (same finding not shown twice without change)
- Snooze (user can dismiss for N hours)
- Acknowledgment (user can dismiss permanently until state changes)

Critical severity bypasses rate limits but still respects acknowledgment.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Default configuration for health checks
DEFAULT_CHECK_CONFIG: dict[str, dict[str, Any]] = {
    "context_freshness": {
        "min_interval_hours": 24,
        "max_per_session": 2,
        "enabled": True,
    },
    "act_vitality": {
        "min_interval_hours": 24,
        "max_per_session": 2,
        "enabled": True,
    },
    "data_integrity": {
        "min_interval_hours": 1,
        "max_per_session": 5,
        "enabled": True,
    },
    "correction_intake": {
        "min_interval_hours": 48,
        "max_per_session": 1,
        "enabled": True,
    },
    "signal_quality": {
        "min_interval_hours": 48,
        "max_per_session": 1,
        "enabled": True,
    },
    "preference_alignment": {
        "min_interval_hours": 24,
        "max_per_session": 2,
        "enabled": True,
    },
    "pattern_currency": {
        "min_interval_hours": 72,
        "max_per_session": 1,
        "enabled": True,
    },
    "software_currency": {
        "min_interval_hours": 24,
        "max_per_session": 2,
        "enabled": True,
    },
    "security_posture": {
        "min_interval_hours": 24,
        "max_per_session": 1,
        "enabled": True,
    },
}


class AntiNagProtocol:
    """Rate limiting and deduplication for health surfacing."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._session_counts: dict[str, int] = {}

    def should_surface(
        self,
        check_name: str,
        severity: str,
        finding_key: str,
    ) -> bool:
        """Determine whether a health finding should be surfaced.

        Args:
            check_name: Name of the health check.
            severity: "healthy", "warning", or "critical".
            finding_key: Unique key for this specific finding (for dedup).

        Returns:
            True if the finding should be shown to the user.
        """
        # Healthy findings are never surfaced as messages
        if severity == "healthy":
            return False

        # Check if this check is enabled
        config = self._get_config(check_name)
        if not config.get("enabled", True):
            return False

        # Check acknowledgment (user dismissed this specific finding)
        if self._is_acknowledged(finding_key):
            return False

        # Check snooze
        if self._is_snoozed(finding_key):
            return False

        # Critical severity bypasses rate limits
        if severity == "critical":
            return True

        # Check rate limit (min interval between surfacing)
        min_interval = config.get("min_interval_hours", 24)
        if self._was_recently_surfaced(check_name, hours=min_interval):
            return False

        # Check session cap
        max_per_session = config.get("max_per_session", 2)
        session_count = self._session_counts.get(check_name, 0)
        if session_count >= max_per_session:
            return False

        return True

    def log_surfaced(
        self,
        check_name: str,
        severity: str,
        finding_key: str,
        title: str,
        details: str = "",
    ) -> str:
        """Record that a finding was surfaced to the user.

        Args:
            check_name: Name of the health check.
            severity: Severity level.
            finding_key: Unique key for dedup.
            title: Human-readable title.
            details: Additional details.

        Returns:
            The log entry ID.
        """
        log_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        self._conn.execute(
            """
            INSERT INTO health_surfacing_log
            (log_id, check_name, severity, finding_key, title, details,
             surfaced_at, acknowledged, snoozed_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (log_id, check_name, severity, finding_key, title, details, now),
        )
        self._conn.commit()

        # Track session count
        self._session_counts[check_name] = self._session_counts.get(check_name, 0) + 1

        return log_id

    def acknowledge(self, log_id: str) -> bool:
        """Mark a surfaced finding as acknowledged (dismissed permanently).

        Args:
            log_id: The surfacing log entry ID.

        Returns:
            True if acknowledged, False if not found.
        """
        cursor = self._conn.execute(
            """
            UPDATE health_surfacing_log
            SET acknowledged = 1, acknowledged_at = ?
            WHERE log_id = ? AND acknowledged = 0
            """,
            (datetime.now().isoformat(), log_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def snooze(self, log_id: str, hours: int = 24) -> bool:
        """Snooze a finding for N hours.

        Args:
            log_id: The surfacing log entry ID.
            hours: Hours to snooze (default 24).

        Returns:
            True if snoozed, False if not found.
        """
        snooze_until = (datetime.now() + timedelta(hours=hours)).isoformat()
        cursor = self._conn.execute(
            """
            UPDATE health_surfacing_log
            SET snoozed_until = ?
            WHERE log_id = ?
            """,
            (snooze_until, log_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_unacknowledged_count(self) -> int:
        """Get count of unacknowledged surfaced findings."""
        row = self._conn.execute(
            """
            SELECT COUNT(*) as cnt FROM health_surfacing_log
            WHERE acknowledged = 0
            AND (snoozed_until IS NULL OR snoozed_until < ?)
            """,
            (datetime.now().isoformat(),),
        ).fetchone()
        return row[0] if row else 0

    def _get_config(self, check_name: str) -> dict[str, Any]:
        """Get configuration for a check."""
        row = self._conn.execute(
            "SELECT config_json FROM health_check_config WHERE check_name = ?",
            (check_name,),
        ).fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                pass
        return DEFAULT_CHECK_CONFIG.get(check_name, {
            "min_interval_hours": 24,
            "max_per_session": 2,
            "enabled": True,
        })

    def _is_acknowledged(self, finding_key: str) -> bool:
        """Check if a finding has been acknowledged."""
        row = self._conn.execute(
            """
            SELECT 1 FROM health_surfacing_log
            WHERE finding_key = ? AND acknowledged = 1
            ORDER BY surfaced_at DESC LIMIT 1
            """,
            (finding_key,),
        ).fetchone()
        return row is not None

    def _is_snoozed(self, finding_key: str) -> bool:
        """Check if a finding is currently snoozed."""
        now = datetime.now().isoformat()
        row = self._conn.execute(
            """
            SELECT 1 FROM health_surfacing_log
            WHERE finding_key = ? AND snoozed_until IS NOT NULL AND snoozed_until > ?
            ORDER BY surfaced_at DESC LIMIT 1
            """,
            (finding_key, now),
        ).fetchone()
        return row is not None

    def _was_recently_surfaced(self, check_name: str, hours: int) -> bool:
        """Check if this check was surfaced within the given hours."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        row = self._conn.execute(
            """
            SELECT 1 FROM health_surfacing_log
            WHERE check_name = ? AND surfaced_at > ?
            ORDER BY surfaced_at DESC LIMIT 1
            """,
            (check_name, cutoff),
        ).fetchone()
        return row is not None


def init_health_tables(conn: sqlite3.Connection) -> None:
    """Create health-related tables if they don't exist.

    Called from CairnStore._init_schema().
    """
    conn.executescript("""
        -- Health surfacing log: tracks what was shown, when, acknowledgment
        CREATE TABLE IF NOT EXISTS health_surfacing_log (
            log_id TEXT PRIMARY KEY,
            check_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_key TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT,
            surfaced_at TEXT NOT NULL,
            acknowledged INTEGER DEFAULT 0,
            acknowledged_at TEXT,
            snoozed_until TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_health_surfacing_check
            ON health_surfacing_log(check_name);
        CREATE INDEX IF NOT EXISTS idx_health_surfacing_key
            ON health_surfacing_log(finding_key);
        CREATE INDEX IF NOT EXISTS idx_health_surfacing_time
            ON health_surfacing_log(surfaced_at);

        -- Health check configuration: per-check rate limits
        CREATE TABLE IF NOT EXISTS health_check_config (
            check_name TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)


def init_health_check_defaults(conn: sqlite3.Connection) -> None:
    """Seed default configuration for all health checks.

    Only inserts if no config exists (won't override user changes).
    """
    now = datetime.now().isoformat()
    for check_name, config in DEFAULT_CHECK_CONFIG.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO health_check_config
            (check_name, config_json, updated_at)
            VALUES (?, ?, ?)
            """,
            (check_name, json.dumps(config), now),
        )
    conn.commit()
