"""ReOS Telemetry — Structured event storage for the terminal pipeline.

Records events from the PTY output → error detection → NL proposal → model
response → user action pipeline. All writes are fire-and-forget: telemetry
failures must never affect the proposal flow.

DB location: ~/.talkingrock/reos_telemetry.db  (separate from talkingrock.db)

Schema is append-only with a single polymorphic table keyed on (session_id,
trace_id). A single user action generates multiple events sharing one trace_id:
  error_detected → proposal_requested → proposal_generated → user_action

Note: Orphaned error_detected events (no following proposal_generated) are
expected behaviour when proposalPending is already true on the frontend. The
analysis queries account for this via LEFT JOINs.

Retention: rows older than TALKINGROCK_TELEMETRY_RETENTION_DAYS (default 90)
are trimmed lazily on init_db().
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_FILENAME = "reos_telemetry.db"
_DEFAULT_RETENTION_DAYS = 90

# Module-level lazy singleton connection.
_conn: sqlite3.Connection | None = None

_DDL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS reos_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,
    trace_id      TEXT    NOT NULL,
    ts            INTEGER NOT NULL,
    event_type    TEXT    NOT NULL,
    payload_json  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_session  ON reos_events (session_id);
CREATE INDEX IF NOT EXISTS idx_events_trace    ON reos_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts  ON reos_events (event_type, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts       ON reos_events (ts);
"""


def get_db_path() -> Path:
    """Return the path to the telemetry database."""
    return Path.home() / ".talkingrock" / _DB_FILENAME


def init_db() -> sqlite3.Connection:
    """Lazily initialise the telemetry DB and return the connection.

    Creates the ~/.talkingrock directory if it doesn't exist, applies the DDL,
    and trims old events. Safe to call multiple times — idempotent.
    """
    global _conn

    if _conn is not None:
        return _conn

    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(_DDL)
    conn.commit()

    _conn = conn

    # Trim old events on startup (lazy retention enforcement).
    try:
        retention_days = int(
            os.environ.get("TALKINGROCK_TELEMETRY_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)
        )
        trim_old_events(conn, days=retention_days)
    except Exception as exc:
        logger.debug("Telemetry trim failed (non-fatal): %s", exc)

    return conn


def get_connection() -> sqlite3.Connection:
    """Return the module-level lazy singleton connection, initialising if needed."""
    return init_db()


def trim_old_events(conn: sqlite3.Connection, days: int = _DEFAULT_RETENTION_DAYS) -> None:
    """Delete events older than *days* days.

    Called lazily on init_db(). At ~500 bytes/event this bounds the DB to a
    manageable size without requiring any user action.
    """
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    conn.execute("DELETE FROM reos_events WHERE ts < ?", (cutoff_ms,))
    conn.commit()


def record_event(
    session_id: str,
    trace_id: str,
    ts: int,
    event_type: str,
    payload: dict,
) -> None:
    """Write a single telemetry event. Fire-and-forget — never raises.

    If the DB is unavailable or corrupt, the error is logged at DEBUG level and
    the call returns silently. This guarantees that telemetry failures never
    surface to the user or affect the proposal flow.
    """
    try:
        conn = get_connection()
        payload_json = json.dumps(payload)
        conn.execute(
            "INSERT INTO reos_events (session_id, trace_id, ts, event_type, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, trace_id, ts, event_type, payload_json),
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Telemetry write failed (non-fatal): %s", exc)
