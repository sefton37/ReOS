"""Health Snapshots — Daily rollups of health metrics for trend analysis.

Creates a daily snapshot of key health metrics at first daily interaction.
These snapshots enable the health_history MCP tool to show trends over time.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


def init_snapshot_tables(conn: sqlite3.Connection) -> None:
    """Create snapshot tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS health_snapshots (
            snapshot_date TEXT PRIMARY KEY,
            metrics_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pattern_drift_events (
            event_id TEXT PRIMARY KEY,
            detected_at TEXT NOT NULL,
            drift_magnitude REAL NOT NULL,
            baseline_window_days INTEGER NOT NULL,
            recent_window_days INTEGER NOT NULL,
            details_json TEXT
        );
    """)


def create_daily_snapshot(
    conn: sqlite3.Connection,
    metrics: dict[str, Any],
) -> bool:
    """Create a daily snapshot if one doesn't exist for today.

    Args:
        conn: SQLite connection (to cairn.db).
        metrics: Dict of metric name -> value.

    Returns:
        True if snapshot was created, False if already exists.
    """
    today = date.today().isoformat()
    now = datetime.now().isoformat()

    # Check if today's snapshot exists
    existing = conn.execute(
        "SELECT 1 FROM health_snapshots WHERE snapshot_date = ?",
        (today,),
    ).fetchone()

    if existing:
        return False

    conn.execute(
        """
        INSERT INTO health_snapshots (snapshot_date, metrics_json, created_at)
        VALUES (?, ?, ?)
        """,
        (today, json.dumps(metrics), now),
    )
    conn.commit()
    return True


def get_snapshots(
    conn: sqlite3.Connection,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get recent snapshots for trend display.

    Args:
        conn: SQLite connection.
        days: Number of days of history to return.

    Returns:
        List of snapshot dicts ordered by date ascending.
    """
    cursor = conn.execute(
        """
        SELECT snapshot_date, metrics_json, created_at
        FROM health_snapshots
        ORDER BY snapshot_date DESC
        LIMIT ?
        """,
        (days,),
    )

    results = []
    for row in cursor.fetchall():
        metrics = {}
        try:
            metrics = json.loads(row[1])
        except json.JSONDecodeError:
            pass
        results.append({
            "date": row[0],
            "metrics": metrics,
            "created_at": row[2],
        })

    # Return chronological order
    results.reverse()
    return results


def log_drift_event(
    conn: sqlite3.Connection,
    event_id: str,
    drift_magnitude: float,
    baseline_days: int,
    recent_days: int,
    details: dict[str, Any] | None = None,
) -> None:
    """Log a pattern drift detection event.

    Args:
        conn: SQLite connection.
        event_id: Unique event ID.
        drift_magnitude: Total variation distance.
        baseline_days: Baseline window size.
        recent_days: Recent window size.
        details: Optional additional details.
    """
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO pattern_drift_events
        (event_id, detected_at, drift_magnitude, baseline_window_days,
         recent_window_days, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, now, drift_magnitude, baseline_days, recent_days,
         json.dumps(details) if details else None),
    )
    conn.commit()
