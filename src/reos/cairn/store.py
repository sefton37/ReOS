"""CAIRN SQLite store.

Handles persistence for CAIRN metadata overlays, contact links, and activity logs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
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
    PriorityQueueItem,
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
            """)

    # =========================================================================
    # Metadata CRUD
    # =========================================================================

    def get_metadata(self, entity_type: str, entity_id: str) -> CairnMetadata | None:
        """Get metadata for a Play entity.

        Args:
            entity_type: Type of entity (act, scene, beat).
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
            entity_type: Type of entity (act, scene, beat).
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
