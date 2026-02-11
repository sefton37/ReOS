"""CAIRN SQLite store.

Handles persistence for CAIRN metadata overlays, contact links, and activity logs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from reos.cairn.models import (
    ActivityLogEntry,
    ActivityType,
    CairnMetadata,
    ContactLink,
    ContactRelationship,
    KanbanState,
    PendingConfirmation,
    PriorityQueueItem,
    UndoContext,
)


class CairnStore:
    """SQLite store for CAIRN data."""

    def __init__(self, db_path: Path | str):
        """Initialize the store.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                -- Activity tracking for Play entities
                CREATE TABLE IF NOT EXISTS cairn_metadata (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    last_touched TEXT,
                    touch_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    kanban_state TEXT DEFAULT 'backlog',
                    waiting_on TEXT,
                    waiting_since TEXT,
                    priority INTEGER,
                    priority_set_at TEXT,
                    priority_reason TEXT,
                    due_date TEXT,
                    start_date TEXT,
                    defer_until TEXT,
                    PRIMARY KEY (entity_type, entity_id)
                );

                -- Contact knowledge graph
                CREATE TABLE IF NOT EXISTS contact_links (
                    link_id TEXT PRIMARY KEY,
                    contact_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    notes TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_contact_links_contact
                    ON contact_links(contact_id);
                CREATE INDEX IF NOT EXISTS idx_contact_links_entity
                    ON contact_links(entity_type, entity_id);

                -- Activity log (for trends and last-touched tracking)
                CREATE TABLE IF NOT EXISTS activity_log (
                    log_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    details TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_activity_log_entity
                    ON activity_log(entity_type, entity_id);
                CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp
                    ON activity_log(timestamp);

                -- Priority decisions needed (surfaced by CAIRN)
                CREATE TABLE IF NOT EXISTS priority_queue (
                    queue_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    surfaced_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_priority_queue_entity
                    ON priority_queue(entity_type, entity_id);

                -- Coherence verification traces (audit trail)
                CREATE TABLE IF NOT EXISTS coherence_traces (
                    trace_id TEXT PRIMARY KEY,
                    demand_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    checks_json TEXT NOT NULL,
                    final_score REAL NOT NULL,
                    recommendation TEXT NOT NULL,
                    user_override TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_coherence_traces_demand
                    ON coherence_traces(demand_id);
                CREATE INDEX IF NOT EXISTS idx_coherence_traces_timestamp
                    ON coherence_traces(timestamp);

                -- Integration preferences (Thunderbird, etc.)
                CREATE TABLE IF NOT EXISTS integration_preferences (
                    integration_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'not_configured',
                    config_json TEXT,
                    declined_at TEXT,
                    last_prompted TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Scene to Calendar Event links (many-to-many)
                -- A Scene can have multiple calendar events associated
                CREATE TABLE IF NOT EXISTS scene_calendar_links (
                    link_id TEXT PRIMARY KEY,
                    scene_id TEXT NOT NULL,
                    calendar_event_id TEXT NOT NULL,
                    calendar_event_title TEXT,
                    calendar_event_start TEXT,
                    calendar_event_end TEXT,
                    created_at TEXT NOT NULL,
                    notes TEXT,
                    recurrence_rule TEXT,       -- RRULE string for recurring events
                    next_occurrence TEXT,       -- Computed next occurrence datetime
                    act_id TEXT,                -- Act this Scene belongs to
                    UNIQUE(scene_id, calendar_event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_scene_calendar_scene
                    ON scene_calendar_links(scene_id);
                CREATE INDEX IF NOT EXISTS idx_scene_calendar_event
                    ON scene_calendar_links(calendar_event_id);
                CREATE INDEX IF NOT EXISTS idx_scene_calendar_start
                    ON scene_calendar_links(calendar_event_start);

                -- Extended thinking traces (audit trail for CAIRN's reasoning)
                CREATE TABLE IF NOT EXISTS extended_thinking_traces (
                    trace_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,

                    -- Serialized trace data
                    trace_json TEXT NOT NULL,

                    -- Quick-access summary fields
                    understood_count INTEGER DEFAULT 0,
                    ambiguous_count INTEGER DEFAULT 0,
                    assumption_count INTEGER DEFAULT 0,
                    tension_count INTEGER DEFAULT 0,
                    final_confidence REAL,
                    decision TEXT,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_ext_thinking_conversation
                    ON extended_thinking_traces(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_ext_thinking_decision
                    ON extended_thinking_traces(decision);

                -- Pending confirmations for irreversible actions
                -- These require explicit user approval before execution
                CREATE TABLE IF NOT EXISTS pending_confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    tool_args_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    warning TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    confirmed INTEGER DEFAULT 0,
                    executed INTEGER DEFAULT 0,
                    cancelled INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_pending_confirmations_created
                    ON pending_confirmations(created_at);
                CREATE INDEX IF NOT EXISTS idx_pending_confirmations_status
                    ON pending_confirmations(confirmed, executed, cancelled);
            """)

            # Health Pulse tables (Anti-Nag Protocol + Snapshots)
            from reos.cairn.health.anti_nag import init_health_tables
            from reos.cairn.health.snapshot import init_snapshot_tables
            init_health_tables(conn)
            init_snapshot_tables(conn)

            # Migrations for existing databases
            self._run_migrations(conn)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Run schema migrations for existing databases."""
        # Migrate beat_calendar_links to scene_calendar_links if old table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='beat_calendar_links'"
        )
        if cursor.fetchone():
            # Old table exists - migrate data
            logger.info("Migrating beat_calendar_links to scene_calendar_links")
            conn.execute("""
                INSERT OR IGNORE INTO scene_calendar_links
                (link_id, scene_id, calendar_event_id, calendar_event_title,
                 calendar_event_start, calendar_event_end, created_at, notes,
                 recurrence_rule, next_occurrence, act_id)
                SELECT link_id, beat_id, calendar_event_id, calendar_event_title,
                       calendar_event_start, calendar_event_end, created_at, notes,
                       recurrence_rule, next_occurrence, act_id
                FROM beat_calendar_links
            """)
            conn.execute("DROP TABLE beat_calendar_links")
            logger.info("Migration complete: beat_calendar_links -> scene_calendar_links")

        # Add new columns to scene_calendar_links if they don't exist
        columns_to_add = [
            ("recurrence_rule", "TEXT"),
            ("next_occurrence", "TEXT"),
            ("act_id", "TEXT"),
            ("calendar_name", "TEXT"),  # Human-readable calendar name (e.g., "Holidays in United States")
            ("category", "TEXT"),       # Classification: "event", "holiday", "birthday"
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(
                    f"ALTER TABLE scene_calendar_links ADD COLUMN {col_name} {col_type}"
                )
                logger.debug(f"Added column {col_name} to scene_calendar_links")
            except sqlite3.OperationalError:
                # Column already exists
                pass

    # =========================================================================
    # Metadata CRUD
    # =========================================================================

    def get_metadata(self, entity_type: str, entity_id: str) -> CairnMetadata | None:
        """Get metadata for a Play entity.

        Args:
            entity_type: Type of entity (act, scene).
            entity_id: ID of the entity.

        Returns:
            CairnMetadata if found, None otherwise.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM cairn_metadata
                WHERE entity_type = ? AND entity_id = ?
                """,
                (entity_type, entity_id),
            ).fetchone()

            if row is None:
                return None

            return CairnMetadata.from_dict(dict(row))

    def get_or_create_metadata(
        self, entity_type: str, entity_id: str
    ) -> CairnMetadata:
        """Get metadata for a Play entity, creating if it doesn't exist.

        Args:
            entity_type: Type of entity (act, scene).
            entity_id: ID of the entity.

        Returns:
            CairnMetadata for the entity.
        """
        metadata = self.get_metadata(entity_type, entity_id)
        if metadata is not None:
            return metadata

        # Create new metadata
        now = datetime.now()
        metadata = CairnMetadata(
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=now,
            last_touched=now,
            touch_count=0,
            kanban_state=KanbanState.BACKLOG,
        )
        self.save_metadata(metadata)
        return metadata

    def save_metadata(self, metadata: CairnMetadata) -> None:
        """Save or update metadata for a Play entity.

        Args:
            metadata: The metadata to save.
        """
        data = metadata.to_dict()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cairn_metadata (
                    entity_type, entity_id, last_touched, touch_count, created_at,
                    kanban_state, waiting_on, waiting_since, priority, priority_set_at,
                    priority_reason, due_date, start_date, defer_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["entity_type"],
                    data["entity_id"],
                    data["last_touched"],
                    data["touch_count"],
                    data["created_at"],
                    data["kanban_state"],
                    data["waiting_on"],
                    data["waiting_since"],
                    data["priority"],
                    data["priority_set_at"],
                    data["priority_reason"],
                    data["due_date"],
                    data["start_date"],
                    data["defer_until"],
                ),
            )

    def delete_metadata(self, entity_type: str, entity_id: str) -> bool:
        """Delete metadata for a Play entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.

        Returns:
            True if deleted, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM cairn_metadata
                WHERE entity_type = ? AND entity_id = ?
                """,
                (entity_type, entity_id),
            )
            return cursor.rowcount > 0

    def list_metadata(
        self,
        entity_type: str | None = None,
        kanban_state: KanbanState | None = None,
        has_priority: bool | None = None,
        is_overdue: bool = False,
        is_stale: bool = False,
        limit: int = 100,
    ) -> list[CairnMetadata]:
        """List metadata with filters.

        Args:
            entity_type: Filter by entity type.
            kanban_state: Filter by kanban state.
            has_priority: True = has priority, False = no priority, None = any.
            is_overdue: Only return overdue items.
            is_stale: Only return stale items.
            limit: Maximum items to return.

        Returns:
            List of matching CairnMetadata.
        """
        conditions = []
        params: list[Any] = []

        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)

        if kanban_state is not None:
            conditions.append("kanban_state = ?")
            params.append(kanban_state.value)

        if has_priority is True:
            conditions.append("priority IS NOT NULL")
        elif has_priority is False:
            conditions.append("priority IS NULL")

        now_iso = datetime.now().isoformat()
        if is_overdue:
            conditions.append("due_date IS NOT NULL AND due_date < ?")
            params.append(now_iso)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM cairn_metadata
            {where_clause}
            ORDER BY
                CASE WHEN due_date IS NOT NULL THEN 0 ELSE 1 END,
                due_date,
                priority DESC NULLS LAST,
                last_touched DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = [CairnMetadata.from_dict(dict(row)) for row in rows]

            # Post-filter for is_stale (requires property check)
            if is_stale:
                results = [m for m in results if m.is_stale]

            return results

    # =========================================================================
    # Touch / Activity Tracking
    # =========================================================================

    def touch(
        self,
        entity_type: str,
        entity_id: str,
        activity_type: ActivityType = ActivityType.VIEWED,
        details: dict[str, Any] | None = None,
    ) -> CairnMetadata:
        """Record an interaction with an entity.

        Updates last_touched, increments touch_count, and logs the activity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            activity_type: Type of activity (default: VIEWED).
            details: Optional additional details.

        Returns:
            Updated CairnMetadata.
        """
        now = datetime.now()

        # Update metadata
        metadata = self.get_or_create_metadata(entity_type, entity_id)
        metadata.last_touched = now
        metadata.touch_count += 1
        self.save_metadata(metadata)

        # Log activity
        self.log_activity(entity_type, entity_id, activity_type, details)

        return metadata

    def log_activity(
        self,
        entity_type: str,
        entity_id: str,
        activity_type: ActivityType,
        details: dict[str, Any] | None = None,
    ) -> str:
        """Log an activity without updating metadata.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            activity_type: Type of activity.
            details: Optional additional details.

        Returns:
            The log entry ID.
        """
        log_id = str(uuid.uuid4())
        now = datetime.now()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO activity_log (
                    log_id, entity_type, entity_id, activity_type, timestamp, details
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    entity_type,
                    entity_id,
                    activity_type.value,
                    now.isoformat(),
                    json.dumps(details) if details else None,
                ),
            )

        return log_id

    def get_activity_log(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ActivityLogEntry]:
        """Get activity log entries.

        Args:
            entity_type: Filter by entity type.
            entity_id: Filter by entity ID.
            since: Only return entries after this time.
            limit: Maximum entries to return.

        Returns:
            List of ActivityLogEntry.
        """
        conditions = []
        params: list[Any] = []

        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)

        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)

        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since.isoformat())

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM activity_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                details = {}
                if row["details"]:
                    details = json.loads(row["details"])
                results.append(
                    ActivityLogEntry(
                        log_id=row["log_id"],
                        entity_type=row["entity_type"],
                        entity_id=row["entity_id"],
                        activity_type=ActivityType(row["activity_type"]),
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        details=details,
                    )
                )
            return results

    # =========================================================================
    # Undo Tracking (Tool Execution Logging)
    # =========================================================================

    def log_tool_execution(
        self,
        tool_name: str,
        undo_context: UndoContext,
        conversation_id: str | None = None,
    ) -> str:
        """Log a tool execution with undo context to activity_log.

        This records reversible actions so they can be undone later.

        Args:
            tool_name: Name of the tool that was executed.
            undo_context: Context for reversing the action.
            conversation_id: Optional conversation ID to scope the undo.

        Returns:
            The log entry ID.
        """
        log_id = str(uuid.uuid4())
        now = datetime.now()

        # Store undo context in details
        details = {
            "undo_context": undo_context.to_dict(),
            "conversation_id": conversation_id,
        }

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO activity_log (
                    log_id, entity_type, entity_id, activity_type, timestamp, details
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    "tool_execution",  # Special entity type for tool executions
                    tool_name,  # Use tool name as entity ID
                    ActivityType.TOOL_EXECUTED.value,
                    now.isoformat(),
                    json.dumps(details),
                ),
            )

        return log_id

    def get_last_undoable_action(
        self,
        conversation_id: str | None = None,
    ) -> tuple[str, UndoContext] | None:
        """Get the most recent reversible action.

        Args:
            conversation_id: Optional conversation ID to scope the search.
                If None, returns the most recent undoable action globally.

        Returns:
            Tuple of (log_id, UndoContext) if found, None otherwise.
        """
        with self._get_connection() as conn:
            # Get the most recent TOOL_EXECUTED entry
            rows = conn.execute(
                """
                SELECT log_id, details FROM activity_log
                WHERE activity_type = ?
                ORDER BY timestamp DESC
                LIMIT 20
                """,
                (ActivityType.TOOL_EXECUTED.value,),
            ).fetchall()

            for row in rows:
                if not row["details"]:
                    continue

                try:
                    details = json.loads(row["details"])
                    undo_data = details.get("undo_context")
                    if not undo_data:
                        continue

                    # Check conversation_id if specified
                    entry_conv_id = details.get("conversation_id")
                    if conversation_id and entry_conv_id != conversation_id:
                        continue

                    undo_context = UndoContext.from_dict(undo_data)

                    # Only return if it's reversible
                    if undo_context.reversible:
                        return (row["log_id"], undo_context)

                except (json.JSONDecodeError, KeyError):
                    continue

            return None

    def mark_undo_executed(self, log_id: str) -> bool:
        """Mark an undo action as executed (prevents double-undo).

        After an action is undone, we update its undo_context to mark it
        as no longer reversible.

        Args:
            log_id: The log entry ID of the action that was undone.

        Returns:
            True if updated, False if not found.
        """
        with self._get_connection() as conn:
            # Get current details
            row = conn.execute(
                "SELECT details FROM activity_log WHERE log_id = ?",
                (log_id,),
            ).fetchone()

            if row is None:
                return False

            try:
                details = json.loads(row["details"]) if row["details"] else {}
                undo_context = details.get("undo_context", {})

                # Mark as no longer reversible
                undo_context["reversible"] = False
                undo_context["not_reversible_reason"] = "Already undone"
                details["undo_context"] = undo_context
                details["undone_at"] = datetime.now().isoformat()

                conn.execute(
                    "UPDATE activity_log SET details = ? WHERE log_id = ?",
                    (json.dumps(details), log_id),
                )
                return True

            except json.JSONDecodeError:
                return False

    # =========================================================================
    # Pending Confirmations (Irreversible Action Guard)
    # =========================================================================

    def create_pending_confirmation(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        description: str,
        warning: str,
        expires_in_minutes: int = 5,
    ) -> PendingConfirmation:
        """Create a pending confirmation for an irreversible action.

        The action will not execute until explicitly confirmed by the user.

        Args:
            tool_name: Name of the tool to execute.
            tool_args: Arguments for the tool.
            description: Human-readable description of what will happen.
            warning: Why this action needs confirmation.
            expires_in_minutes: How long until confirmation expires (default 5 min).

        Returns:
            PendingConfirmation object with unique ID.
        """
        confirmation_id = str(uuid.uuid4())[:8]  # Short ID for easy reference
        now = datetime.now()
        expires_at = now + timedelta(minutes=expires_in_minutes)

        pending = PendingConfirmation(
            confirmation_id=confirmation_id,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
            warning=warning,
            created_at=now,
            expires_at=expires_at,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pending_confirmations (
                    confirmation_id, tool_name, tool_args_json, description,
                    warning, created_at, expires_at, confirmed, executed, cancelled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (
                    confirmation_id,
                    tool_name,
                    json.dumps(tool_args),
                    description,
                    warning,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )

        return pending

    def get_pending_confirmation(
        self,
        confirmation_id: str,
    ) -> PendingConfirmation | None:
        """Get a pending confirmation by ID.

        Args:
            confirmation_id: The confirmation ID.

        Returns:
            PendingConfirmation if found, None otherwise.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()

            if row is None:
                return None

            return PendingConfirmation(
                confirmation_id=row["confirmation_id"],
                tool_name=row["tool_name"],
                tool_args=json.loads(row["tool_args_json"]),
                description=row["description"],
                warning=row["warning"],
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
                confirmed=bool(row["confirmed"]),
                executed=bool(row["executed"]),
                cancelled=bool(row["cancelled"]),
            )

    def get_latest_pending_confirmation(self) -> PendingConfirmation | None:
        """Get the most recent actionable pending confirmation.

        Returns:
            Most recent PendingConfirmation that can still be acted upon, or None.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM pending_confirmations
                WHERE confirmed = 0 AND executed = 0 AND cancelled = 0
                    AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (now,),
            ).fetchone()

            if row is None:
                return None

            return PendingConfirmation(
                confirmation_id=row["confirmation_id"],
                tool_name=row["tool_name"],
                tool_args=json.loads(row["tool_args_json"]),
                description=row["description"],
                warning=row["warning"],
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
                confirmed=bool(row["confirmed"]),
                executed=bool(row["executed"]),
                cancelled=bool(row["cancelled"]),
            )

    def confirm_pending(self, confirmation_id: str) -> bool:
        """Mark a pending confirmation as confirmed by user.

        Args:
            confirmation_id: The confirmation ID.

        Returns:
            True if confirmed, False if not found or not actionable.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE pending_confirmations
                SET confirmed = 1
                WHERE confirmation_id = ?
                    AND confirmed = 0 AND executed = 0 AND cancelled = 0
                    AND expires_at > ?
                """,
                (confirmation_id, now),
            )
            return cursor.rowcount > 0

    def mark_confirmation_executed(self, confirmation_id: str) -> bool:
        """Mark a confirmed action as executed.

        Args:
            confirmation_id: The confirmation ID.

        Returns:
            True if marked, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE pending_confirmations
                SET executed = 1
                WHERE confirmation_id = ? AND confirmed = 1
                """,
                (confirmation_id,),
            )
            return cursor.rowcount > 0

    def cancel_pending(self, confirmation_id: str) -> bool:
        """Cancel a pending confirmation.

        Args:
            confirmation_id: The confirmation ID.

        Returns:
            True if cancelled, False if not found or already actioned.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE pending_confirmations
                SET cancelled = 1
                WHERE confirmation_id = ?
                    AND confirmed = 0 AND executed = 0 AND cancelled = 0
                """,
                (confirmation_id,),
            )
            return cursor.rowcount > 0

    def cleanup_expired_confirmations(self) -> int:
        """Clean up expired pending confirmations.

        Returns:
            Number of confirmations cancelled.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE pending_confirmations
                SET cancelled = 1
                WHERE confirmed = 0 AND executed = 0 AND cancelled = 0
                    AND expires_at <= ?
                """,
                (now,),
            )
            return cursor.rowcount

    # =========================================================================
    # Scene-Calendar Event Links (DEPRECATED)
    # =========================================================================
    # Calendar data is now stored directly in play.db scenes table.
    # This table is kept for backward compatibility during data migration.
    # See play_db._migrate_calendar_data_from_cairn() for the migration.
    # DO NOT add new functions here - use play_db.update_scene_calendar_data().

    # =========================================================================
    # Kanban State Management
    # =========================================================================

    def set_kanban_state(
        self,
        entity_type: str,
        entity_id: str,
        state: KanbanState,
        waiting_on: str | None = None,
    ) -> CairnMetadata:
        """Set kanban state for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            state: New kanban state.
            waiting_on: Who/what we're waiting on (for WAITING state).

        Returns:
            Updated CairnMetadata.
        """
        metadata = self.get_or_create_metadata(entity_type, entity_id)
        old_state = metadata.kanban_state

        metadata.kanban_state = state

        if state == KanbanState.WAITING:
            metadata.waiting_on = waiting_on
            metadata.waiting_since = datetime.now()
        else:
            metadata.waiting_on = None
            metadata.waiting_since = None

        self.save_metadata(metadata)

        # Log the state change
        self.log_activity(
            entity_type,
            entity_id,
            ActivityType.STATE_CHANGED,
            {"old_state": old_state.value, "new_state": state.value},
        )

        return metadata

    # =========================================================================
    # Priority Management
    # =========================================================================

    def set_priority(
        self,
        entity_type: str,
        entity_id: str,
        priority: int,
        reason: str | None = None,
    ) -> CairnMetadata:
        """Set priority for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            priority: Priority level (1-5, higher = more important).
            reason: Optional reason for the priority.

        Returns:
            Updated CairnMetadata.
        """
        if not 1 <= priority <= 5:
            raise ValueError("Priority must be between 1 and 5")

        metadata = self.get_or_create_metadata(entity_type, entity_id)
        old_priority = metadata.priority

        metadata.priority = priority
        metadata.priority_set_at = datetime.now()
        metadata.priority_reason = reason

        self.save_metadata(metadata)

        # Log the priority change
        self.log_activity(
            entity_type,
            entity_id,
            ActivityType.PRIORITY_SET,
            {"old_priority": old_priority, "new_priority": priority, "reason": reason},
        )

        # Resolve any pending priority queue items
        self._resolve_priority_queue(entity_type, entity_id, f"Set to {priority}")

        return metadata

    def clear_priority(self, entity_type: str, entity_id: str) -> CairnMetadata:
        """Clear priority for an entity (needs decision again).

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.

        Returns:
            Updated CairnMetadata.
        """
        metadata = self.get_or_create_metadata(entity_type, entity_id)
        metadata.priority = None
        metadata.priority_set_at = None
        metadata.priority_reason = None
        self.save_metadata(metadata)
        return metadata

    # =========================================================================
    # Time Management
    # =========================================================================

    def set_due_date(
        self, entity_type: str, entity_id: str, due_date: datetime | None
    ) -> CairnMetadata:
        """Set due date for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            due_date: Due date (or None to clear).

        Returns:
            Updated CairnMetadata.
        """
        metadata = self.get_or_create_metadata(entity_type, entity_id)
        metadata.due_date = due_date
        self.save_metadata(metadata)
        return metadata

    def defer_until(
        self, entity_type: str, entity_id: str, defer_date: datetime
    ) -> CairnMetadata:
        """Defer an entity until a date.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            defer_date: Date to defer until.

        Returns:
            Updated CairnMetadata.
        """
        metadata = self.get_or_create_metadata(entity_type, entity_id)
        metadata.defer_until = defer_date

        # Move to someday if currently active
        if metadata.kanban_state == KanbanState.ACTIVE:
            metadata.kanban_state = KanbanState.SOMEDAY

        self.save_metadata(metadata)

        # Log the deferral
        self.log_activity(
            entity_type,
            entity_id,
            ActivityType.DEFERRED,
            {"defer_until": defer_date.isoformat()},
        )

        return metadata

    # =========================================================================
    # Contact Links
    # =========================================================================

    def link_contact(
        self,
        contact_id: str,
        entity_type: str,
        entity_id: str,
        relationship: ContactRelationship,
        notes: str | None = None,
    ) -> ContactLink:
        """Link a contact to a Play entity.

        Args:
            contact_id: Thunderbird contact ID.
            entity_type: Type of entity.
            entity_id: ID of the entity.
            relationship: Type of relationship.
            notes: Optional notes about the link.

        Returns:
            The created ContactLink.
        """
        link_id = str(uuid.uuid4())
        now = datetime.now()

        link = ContactLink(
            link_id=link_id,
            contact_id=contact_id,
            entity_type=entity_type,
            entity_id=entity_id,
            relationship=relationship,
            created_at=now,
            notes=notes,
        )

        with self._get_connection() as conn:
            data = link.to_dict()
            conn.execute(
                """
                INSERT INTO contact_links (
                    link_id, contact_id, entity_type, entity_id,
                    relationship, created_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["link_id"],
                    data["contact_id"],
                    data["entity_type"],
                    data["entity_id"],
                    data["relationship"],
                    data["created_at"],
                    data["notes"],
                ),
            )

        # Log the link
        self.log_activity(
            entity_type,
            entity_id,
            ActivityType.LINKED,
            {"contact_id": contact_id, "relationship": relationship.value},
        )

        return link

    def unlink_contact(self, link_id: str) -> bool:
        """Remove a contact link.

        Args:
            link_id: ID of the link to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM contact_links WHERE link_id = ?", (link_id,)
            )
            return cursor.rowcount > 0

    def get_contact_links(
        self,
        contact_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[ContactLink]:
        """Get contact links with optional filters.

        Args:
            contact_id: Filter by contact.
            entity_type: Filter by entity type.
            entity_id: Filter by entity ID.

        Returns:
            List of matching ContactLink.
        """
        conditions = []
        params: list[Any] = []

        if contact_id is not None:
            conditions.append("contact_id = ?")
            params.append(contact_id)

        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)

        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM contact_links
            {where_clause}
            ORDER BY created_at DESC
        """

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [ContactLink.from_dict(dict(row)) for row in rows]

    def get_entities_for_contact(self, contact_id: str) -> list[tuple[str, str]]:
        """Get all entities linked to a contact.

        Args:
            contact_id: Thunderbird contact ID.

        Returns:
            List of (entity_type, entity_id) tuples.
        """
        links = self.get_contact_links(contact_id=contact_id)
        return [(link.entity_type, link.entity_id) for link in links]

    def get_contacts_for_entity(
        self, entity_type: str, entity_id: str
    ) -> list[ContactLink]:
        """Get all contacts linked to an entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.

        Returns:
            List of ContactLink.
        """
        return self.get_contact_links(entity_type=entity_type, entity_id=entity_id)

    # =========================================================================
    # Priority Queue
    # =========================================================================

    def surface_priority_needed(
        self, entity_type: str, entity_id: str, reason: str
    ) -> str:
        """Add an item to the priority queue.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            reason: Why priority decision is needed.

        Returns:
            The queue entry ID.
        """
        queue_id = str(uuid.uuid4())
        now = datetime.now()

        with self._get_connection() as conn:
            # Check if already in queue (unresolved)
            existing = conn.execute(
                """
                SELECT queue_id FROM priority_queue
                WHERE entity_type = ? AND entity_id = ? AND resolved_at IS NULL
                """,
                (entity_type, entity_id),
            ).fetchone()

            if existing:
                return existing["queue_id"]

            conn.execute(
                """
                INSERT INTO priority_queue (
                    queue_id, entity_type, entity_id, reason, surfaced_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (queue_id, entity_type, entity_id, reason, now.isoformat()),
            )

        return queue_id

    def _resolve_priority_queue(
        self, entity_type: str, entity_id: str, resolution: str
    ) -> None:
        """Resolve priority queue items for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.
            resolution: How it was resolved.
        """
        now = datetime.now()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE priority_queue
                SET resolved_at = ?, resolution = ?
                WHERE entity_type = ? AND entity_id = ? AND resolved_at IS NULL
                """,
                (now.isoformat(), resolution, entity_type, entity_id),
            )

    def get_priority_queue(self, resolved: bool = False) -> list[PriorityQueueItem]:
        """Get priority queue items.

        Args:
            resolved: If True, include resolved items. If False, only unresolved.

        Returns:
            List of PriorityQueueItem.
        """
        if resolved:
            condition = ""
        else:
            condition = "WHERE resolved_at IS NULL"

        query = f"""
            SELECT * FROM priority_queue
            {condition}
            ORDER BY surfaced_at DESC
        """

        with self._get_connection() as conn:
            rows = conn.execute(query).fetchall()
            results = []
            for row in rows:
                results.append(
                    PriorityQueueItem(
                        queue_id=row["queue_id"],
                        entity_type=row["entity_type"],
                        entity_id=row["entity_id"],
                        reason=row["reason"],
                        surfaced_at=datetime.fromisoformat(row["surfaced_at"]),
                        resolved_at=(
                            datetime.fromisoformat(row["resolved_at"])
                            if row["resolved_at"]
                            else None
                        ),
                        resolution=row["resolution"],
                    )
                )
            return results

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def mark_completed(self, entity_type: str, entity_id: str) -> CairnMetadata:
        """Mark an entity as completed.

        Args:
            entity_type: Type of entity.
            entity_id: ID of the entity.

        Returns:
            Updated CairnMetadata.
        """
        metadata = self.set_kanban_state(entity_type, entity_id, KanbanState.DONE)

        # Log completion
        self.log_activity(entity_type, entity_id, ActivityType.COMPLETED, {})

        return metadata

    def get_waiting_items(self, max_days: int | None = None) -> list[CairnMetadata]:
        """Get items in WAITING state.

        Args:
            max_days: If set, only return items waiting longer than this.

        Returns:
            List of waiting CairnMetadata.
        """
        items = self.list_metadata(kanban_state=KanbanState.WAITING)

        if max_days is not None:
            now = datetime.now()
            items = [
                item
                for item in items
                if item.waiting_since
                and (now - item.waiting_since).days >= max_days
            ]

        return items

    def get_items_needing_priority(self) -> list[CairnMetadata]:
        """Get active items that need a priority decision.

        Returns:
            List of CairnMetadata that need priority.
        """
        items = self.list_metadata(kanban_state=KanbanState.ACTIVE, has_priority=False)
        return [item for item in items if item.needs_priority]

    # =========================================================================
    # Coherence Traces
    # =========================================================================

    def save_coherence_trace(
        self,
        trace_id: str,
        demand_id: str,
        timestamp: datetime,
        identity_hash: str,
        checks: list[dict],
        final_score: float,
        recommendation: str,
        user_override: str | None = None,
    ) -> None:
        """Save a coherence verification trace.

        Args:
            trace_id: Unique trace identifier.
            demand_id: ID of the demand that was verified.
            timestamp: When verification was performed.
            identity_hash: Hash of the identity model used.
            checks: List of coherence checks performed.
            final_score: The final coherence score.
            recommendation: The recommendation (accept/defer/reject).
            user_override: If user disagreed, their choice.
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO coherence_traces (
                    trace_id, demand_id, timestamp, identity_hash,
                    checks_json, final_score, recommendation, user_override
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    demand_id,
                    timestamp.isoformat(),
                    identity_hash,
                    json.dumps(checks),
                    final_score,
                    recommendation,
                    user_override,
                ),
            )

    def get_coherence_trace(self, trace_id: str) -> dict | None:
        """Get a coherence trace by ID.

        Args:
            trace_id: The trace ID to look up.

        Returns:
            Trace data as dict, or None if not found.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM coherence_traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()

            if row is None:
                return None

            return {
                "trace_id": row["trace_id"],
                "demand_id": row["demand_id"],
                "timestamp": row["timestamp"],
                "identity_hash": row["identity_hash"],
                "checks": json.loads(row["checks_json"]),
                "final_score": row["final_score"],
                "recommendation": row["recommendation"],
                "user_override": row["user_override"],
            }

    def list_coherence_traces(
        self,
        demand_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List coherence traces with optional filters.

        Args:
            demand_id: Filter by demand ID.
            since: Only return traces after this time.
            limit: Maximum traces to return.

        Returns:
            List of trace data dicts.
        """
        conditions = []
        params: list[Any] = []

        if demand_id is not None:
            conditions.append("demand_id = ?")
            params.append(demand_id)

        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since.isoformat())

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM coherence_traces
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "trace_id": row["trace_id"],
                    "demand_id": row["demand_id"],
                    "timestamp": row["timestamp"],
                    "identity_hash": row["identity_hash"],
                    "checks": json.loads(row["checks_json"]),
                    "final_score": row["final_score"],
                    "recommendation": row["recommendation"],
                    "user_override": row["user_override"],
                }
                for row in rows
            ]

    def record_user_override(
        self,
        trace_id: str,
        user_choice: str,
    ) -> bool:
        """Record that user overrode a coherence recommendation.

        Args:
            trace_id: The trace to update.
            user_choice: What the user chose instead.

        Returns:
            True if updated, False if trace not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE coherence_traces
                SET user_override = ?
                WHERE trace_id = ?
                """,
                (user_choice, trace_id),
            )
            return cursor.rowcount > 0

    # =========================================================================
    # Integration Preferences
    # =========================================================================

    def get_integration_state(self, integration_id: str) -> dict | None:
        """Get integration state by ID.

        Args:
            integration_id: The integration identifier (e.g., "thunderbird").

        Returns:
            Integration state dict, or None if not configured.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM integration_preferences WHERE integration_id = ?",
                (integration_id,),
            ).fetchone()

            if row is None:
                return None

            config = None
            if row["config_json"]:
                try:
                    config = json.loads(row["config_json"])
                except json.JSONDecodeError:
                    pass

            return {
                "integration_id": row["integration_id"],
                "state": row["state"],
                "config": config,
                "declined_at": row["declined_at"],
                "last_prompted": row["last_prompted"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def set_integration_active(
        self,
        integration_id: str,
        config: dict,
    ) -> None:
        """Set an integration as active with configuration.

        Args:
            integration_id: The integration identifier.
            config: Configuration dict (e.g., active_profiles, active_accounts).
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            # Check if exists
            existing = conn.execute(
                "SELECT integration_id FROM integration_preferences WHERE integration_id = ?",
                (integration_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE integration_preferences
                    SET state = 'active',
                        config_json = ?,
                        declined_at = NULL,
                        updated_at = ?
                    WHERE integration_id = ?
                    """,
                    (json.dumps(config), now, integration_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO integration_preferences (
                        integration_id, state, config_json, created_at, updated_at
                    ) VALUES (?, 'active', ?, ?, ?)
                    """,
                    (integration_id, json.dumps(config), now, now),
                )

    def set_integration_declined(self, integration_id: str) -> None:
        """Mark an integration as declined (user chose 'Never ask again').

        Args:
            integration_id: The integration identifier.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            # Check if exists
            existing = conn.execute(
                "SELECT integration_id FROM integration_preferences WHERE integration_id = ?",
                (integration_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE integration_preferences
                    SET state = 'declined',
                        declined_at = ?,
                        updated_at = ?
                    WHERE integration_id = ?
                    """,
                    (now, now, integration_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO integration_preferences (
                        integration_id, state, declined_at, created_at, updated_at
                    ) VALUES (?, 'declined', ?, ?, ?)
                    """,
                    (integration_id, now, now, now),
                )

    def clear_integration_decline(self, integration_id: str) -> bool:
        """Clear the declined state for an integration (re-enable prompts).

        Args:
            integration_id: The integration identifier.

        Returns:
            True if updated, False if not found.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE integration_preferences
                SET state = 'not_configured',
                    declined_at = NULL,
                    config_json = NULL,
                    updated_at = ?
                WHERE integration_id = ?
                """,
                (now, integration_id),
            )
            return cursor.rowcount > 0

    def record_integration_prompt(self, integration_id: str) -> None:
        """Record that we prompted the user about an integration.

        Args:
            integration_id: The integration identifier.
        """
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            # Check if exists
            existing = conn.execute(
                "SELECT integration_id FROM integration_preferences WHERE integration_id = ?",
                (integration_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE integration_preferences
                    SET last_prompted = ?, updated_at = ?
                    WHERE integration_id = ?
                    """,
                    (now, now, integration_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO integration_preferences (
                        integration_id, state, last_prompted, created_at, updated_at
                    ) VALUES (?, 'not_configured', ?, ?, ?)
                    """,
                    (integration_id, now, now, now),
                )

    def is_integration_declined(self, integration_id: str) -> bool:
        """Check if an integration was declined by the user.

        Args:
            integration_id: The integration identifier.

        Returns:
            True if declined, False otherwise.
        """
        state = self.get_integration_state(integration_id)
        return state is not None and state["state"] == "declined"

    def is_integration_active(self, integration_id: str) -> bool:
        """Check if an integration is active.

        Args:
            integration_id: The integration identifier.

        Returns:
            True if active, False otherwise.
        """
        state = self.get_integration_state(integration_id)
        return state is not None and state["state"] == "active"

    # =========================================================================
    # Extended Thinking Traces
    # =========================================================================

    def save_extended_thinking_trace(
        self,
        trace_id: str,
        conversation_id: str,
        message_id: str,
        prompt: str,
        started_at: datetime,
        completed_at: datetime | None,
        trace_json: str,
        summary: dict,
        decision: str,
        final_confidence: float,
    ) -> None:
        """Save an extended thinking trace.

        Args:
            trace_id: Unique trace identifier.
            conversation_id: The conversation this belongs to.
            message_id: The message this thinking was for.
            prompt: The user's original prompt.
            started_at: When thinking began.
            completed_at: When thinking completed.
            trace_json: Full serialized trace as JSON.
            summary: Summary counts dict.
            decision: The final decision (respond/ask/defer).
            final_confidence: Overall confidence score.
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO extended_thinking_traces (
                    trace_id, conversation_id, message_id, prompt,
                    started_at, completed_at, trace_json,
                    understood_count, ambiguous_count, assumption_count,
                    tension_count, final_confidence, decision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    conversation_id,
                    message_id,
                    prompt,
                    started_at.isoformat(),
                    completed_at.isoformat() if completed_at else None,
                    trace_json,
                    summary.get("understood_count", 0),
                    summary.get("ambiguous_count", 0),
                    summary.get("assumption_count", 0),
                    summary.get("tension_count", 0),
                    final_confidence,
                    decision,
                ),
            )

    def get_extended_thinking_trace(self, trace_id: str) -> dict | None:
        """Get an extended thinking trace by ID.

        Args:
            trace_id: The trace ID to look up.

        Returns:
            Full trace dict with parsed JSON, or None if not found.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM extended_thinking_traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()

            if row is None:
                return None

            return {
                "trace_id": row["trace_id"],
                "conversation_id": row["conversation_id"],
                "message_id": row["message_id"],
                "prompt": row["prompt"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "trace": json.loads(row["trace_json"]) if row["trace_json"] else {},
                "understood_count": row["understood_count"],
                "ambiguous_count": row["ambiguous_count"],
                "assumption_count": row["assumption_count"],
                "tension_count": row["tension_count"],
                "final_confidence": row["final_confidence"],
                "decision": row["decision"],
            }

    def list_extended_thinking_traces(
        self,
        conversation_id: str | None = None,
        decision: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List extended thinking traces with optional filters.

        Args:
            conversation_id: Filter by conversation.
            decision: Filter by decision type.
            since: Only return traces after this time.
            limit: Maximum traces to return.

        Returns:
            List of trace summary dicts (without full trace_json).
        """
        conditions = []
        params: list[Any] = []

        if conversation_id is not None:
            conditions.append("conversation_id = ?")
            params.append(conversation_id)

        if decision is not None:
            conditions.append("decision = ?")
            params.append(decision)

        if since is not None:
            conditions.append("started_at > ?")
            params.append(since.isoformat())

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT
                trace_id, conversation_id, message_id, prompt,
                started_at, completed_at,
                understood_count, ambiguous_count, assumption_count,
                tension_count, final_confidence, decision
            FROM extended_thinking_traces
            {where_clause}
            ORDER BY started_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "trace_id": row["trace_id"],
                    "conversation_id": row["conversation_id"],
                    "message_id": row["message_id"],
                    "prompt": row["prompt"][:100] + "..." if len(row["prompt"]) > 100 else row["prompt"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "understood_count": row["understood_count"],
                    "ambiguous_count": row["ambiguous_count"],
                    "assumption_count": row["assumption_count"],
                    "tension_count": row["tension_count"],
                    "final_confidence": row["final_confidence"],
                    "decision": row["decision"],
                }
                for row in rows
            ]

    def delete_extended_thinking_trace(self, trace_id: str) -> bool:
        """Delete an extended thinking trace.

        Args:
            trace_id: The trace ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM extended_thinking_traces WHERE trace_id = ?",
                (trace_id,),
            )
            return cursor.rowcount > 0
