"""SQLite-based storage for The Play.

This module provides atomic, efficient storage for Play data (Acts, Scenes, Beats)
using SQLite instead of JSON files. The KB files (markdown) remain as files since
they are human-editable and can be large.

Migration: On first use, existing JSON data is automatically migrated to SQLite.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .settings import settings

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_local = threading.local()

# Schema version for migrations
# v1: Initial schema
# v2: Added color column to acts table
SCHEMA_VERSION = 2


def _play_db_path() -> Path:
    """Get the path to the play database."""
    base = Path(os.environ.get("REOS_DATA_DIR", settings.data_dir))
    return base / "play" / "play.db"


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _play_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        # Enable foreign keys
        _local.conn.execute("PRAGMA foreign_keys = ON")
        # WAL mode for better concurrent access
        _local.conn.execute("PRAGMA journal_mode = WAL")
    return _local.conn


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    """Context manager for database transactions."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    conn.executescript("""
        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        -- Acts table
        CREATE TABLE IF NOT EXISTS acts (
            act_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            color TEXT,  -- Hex color for UI display (e.g., "#8b5cf6")
            repo_path TEXT,
            artifact_type TEXT,
            code_config TEXT,  -- JSON string
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Scenes table
        CREATE TABLE IF NOT EXISTS scenes (
            scene_id TEXT PRIMARY KEY,
            act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            time_horizon TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            is_stage_direction INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_scenes_act_id ON scenes(act_id);

        -- Beats table
        CREATE TABLE IF NOT EXISTS beats (
            beat_id TEXT PRIMARY KEY,
            scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'planning',
            notes TEXT NOT NULL DEFAULT '',
            link TEXT,
            calendar_event_id TEXT,
            recurrence_rule TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_beats_scene_id ON beats(scene_id);
        CREATE INDEX IF NOT EXISTS idx_beats_calendar_event ON beats(calendar_event_id);

        -- Attachments table
        CREATE TABLE IF NOT EXISTS attachments (
            attachment_id TEXT PRIMARY KEY,
            act_id TEXT REFERENCES acts(act_id) ON DELETE CASCADE,
            scene_id TEXT REFERENCES scenes(scene_id) ON DELETE CASCADE,
            beat_id TEXT REFERENCES beats(beat_id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            added_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_act ON attachments(act_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_scene ON attachments(scene_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_beat ON attachments(beat_id);
    """)

    # Set schema version if not exists
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    else:
        current_version = row[0]
        # Run migrations
        _run_schema_migrations(conn, current_version)


def _run_schema_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Run schema migrations from current_version to SCHEMA_VERSION."""
    if current_version >= SCHEMA_VERSION:
        return

    logger.info(f"Running schema migrations from v{current_version} to v{SCHEMA_VERSION}")

    # Migration v1 -> v2: Add color column to acts table
    if current_version < 2:
        # Check if color column already exists
        cursor = conn.execute("PRAGMA table_info(acts)")
        columns = [row[1] for row in cursor.fetchall()]
        if "color" not in columns:
            logger.info("Adding color column to acts table")
            conn.execute("ALTER TABLE acts ADD COLUMN color TEXT")

    # Update schema version
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    logger.info(f"Schema migrated to v{SCHEMA_VERSION}")


def _now_iso() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    """Generate a new unique ID with prefix."""
    return f"{prefix}-{uuid4().hex[:12]}"


# =============================================================================
# Migration from JSON to SQLite
# =============================================================================

def _migrate_from_json(conn: sqlite3.Connection) -> None:
    """Migrate existing JSON data to SQLite."""
    base = Path(os.environ.get("REOS_DATA_DIR", settings.data_dir))
    play_root = base / "play"
    acts_json = play_root / "acts.json"

    if not acts_json.exists():
        logger.info("No existing JSON data to migrate")
        return

    # Check if already migrated (acts table has data)
    cursor = conn.execute("SELECT COUNT(*) FROM acts")
    if cursor.fetchone()[0] > 0:
        logger.info("SQLite already has data, skipping JSON migration")
        return

    logger.info("Migrating Play data from JSON to SQLite...")

    try:
        # Load acts
        with open(acts_json, encoding="utf-8") as f:
            acts_data = json.load(f)

        acts_list = acts_data.get("acts", [])
        now = _now_iso()

        for position, act in enumerate(acts_list):
            if not isinstance(act, dict):
                continue

            act_id = act.get("act_id", "")
            if not act_id:
                continue

            # Insert act
            code_config = act.get("code_config")
            code_config_json = json.dumps(code_config) if code_config else None

            conn.execute("""
                INSERT OR IGNORE INTO acts
                (act_id, title, active, notes, repo_path, artifact_type, code_config, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                act_id,
                act.get("title", "Untitled"),
                1 if act.get("active") else 0,
                act.get("notes", ""),
                act.get("repo_path"),
                act.get("artifact_type"),
                code_config_json,
                position,
                now,
                now,
            ))

            # Load scenes for this act
            scenes_json = play_root / "acts" / act_id / "scenes.json"
            if scenes_json.exists():
                try:
                    with open(scenes_json, encoding="utf-8") as f:
                        scenes_data = json.load(f)

                    scenes_list = scenes_data.get("scenes", [])
                    for scene_pos, scene in enumerate(scenes_list):
                        if not isinstance(scene, dict):
                            continue

                        scene_id = scene.get("scene_id", "")
                        if not scene_id:
                            continue

                        # Insert scene
                        conn.execute("""
                            INSERT OR IGNORE INTO scenes
                            (scene_id, act_id, title, intent, status, time_horizon, notes, is_stage_direction, position, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            scene_id,
                            act_id,
                            scene.get("title", "Untitled"),
                            scene.get("intent", ""),
                            scene.get("status", ""),
                            scene.get("time_horizon", ""),
                            scene.get("notes", ""),
                            1 if scene.get("is_stage_direction") else 0,
                            scene_pos,
                            now,
                            now,
                        ))

                        # Load beats for this scene
                        beats_list = scene.get("beats", [])
                        for beat_pos, beat in enumerate(beats_list):
                            if not isinstance(beat, dict):
                                continue

                            beat_id = beat.get("beat_id", "")
                            if not beat_id:
                                continue

                            # Migrate status to stage if needed
                            stage = beat.get("stage") or beat.get("status", "planning")
                            if stage in ("pending", "todo"):
                                stage = "planning"
                            elif stage in ("blocked", "waiting"):
                                stage = "awaiting_data"
                            elif stage in ("completed", "done"):
                                stage = "complete"

                            # Insert beat
                            conn.execute("""
                                INSERT OR IGNORE INTO beats
                                (beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule, position, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                beat_id,
                                scene_id,
                                beat.get("title", "Untitled"),
                                stage,
                                beat.get("notes", ""),
                                beat.get("link"),
                                beat.get("calendar_event_id"),
                                beat.get("recurrence_rule"),
                                beat_pos,
                                now,
                                now,
                            ))
                except Exception as e:
                    logger.warning(f"Error migrating scenes for act {act_id}: {e}")

            # Load attachments for this act
            attachments_json = play_root / "acts" / act_id / "attachments.json"
            if attachments_json.exists():
                try:
                    with open(attachments_json, encoding="utf-8") as f:
                        attachments_list = json.load(f)

                    if isinstance(attachments_list, list):
                        for att in attachments_list:
                            if not isinstance(att, dict):
                                continue

                            conn.execute("""
                                INSERT OR IGNORE INTO attachments
                                (attachment_id, act_id, scene_id, beat_id, file_path, file_name, file_type, added_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                att.get("attachment_id", _new_id("att")),
                                att.get("act_id"),
                                att.get("scene_id"),
                                att.get("beat_id"),
                                att.get("file_path", ""),
                                att.get("file_name", ""),
                                att.get("file_type", ""),
                                att.get("added_at", now),
                            ))
                except Exception as e:
                    logger.warning(f"Error migrating attachments for act {act_id}: {e}")

        logger.info(f"Migration complete: migrated {len(acts_list)} acts")

    except Exception as e:
        logger.error(f"Error during JSON migration: {e}")
        raise


def init_db() -> None:
    """Initialize the database and run migrations."""
    with _transaction() as conn:
        _init_schema(conn)
        _migrate_from_json(conn)


# =============================================================================
# Acts Operations
# =============================================================================

def list_acts() -> tuple[list[dict[str, Any]], str | None]:
    """List all acts and return the active act ID."""
    init_db()
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config
        FROM acts
        ORDER BY position ASC
    """)

    acts = []
    active_act_id = None

    for row in cursor:
        code_config = None
        if row["code_config"]:
            try:
                code_config = json.loads(row["code_config"])
            except json.JSONDecodeError:
                pass

        act = {
            "act_id": row["act_id"],
            "title": row["title"],
            "active": bool(row["active"]),
            "notes": row["notes"],
            "repo_path": row["repo_path"],
            "artifact_type": row["artifact_type"],
            "code_config": code_config,
        }
        acts.append(act)

        if row["active"]:
            active_act_id = row["act_id"]

    return acts, active_act_id


def get_act(act_id: str) -> dict[str, Any] | None:
    """Get a single act by ID."""
    conn = _get_connection()
    cursor = conn.execute("""
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config
        FROM acts WHERE act_id = ?
    """, (act_id,))

    row = cursor.fetchone()
    if not row:
        return None

    code_config = None
    if row["code_config"]:
        try:
            code_config = json.loads(row["code_config"])
        except json.JSONDecodeError:
            pass

    return {
        "act_id": row["act_id"],
        "title": row["title"],
        "active": bool(row["active"]),
        "notes": row["notes"],
        "color": row["color"] if "color" in row.keys() else None,
        "repo_path": row["repo_path"],
        "artifact_type": row["artifact_type"],
        "code_config": code_config,
    }


def create_act(*, title: str, notes: str = "", color: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """Create a new act."""
    act_id = _new_id("act")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position
        cursor = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM acts")
        position = cursor.fetchone()[0]

        conn.execute("""
            INSERT INTO acts (act_id, title, active, notes, color, position, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?, ?)
        """, (act_id, title, notes, color, position, now, now))

        # Create stage direction scene
        _ensure_stage_direction_scene_db(conn, act_id)

    acts, _ = list_acts()
    return acts, act_id


def update_act(
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
    color: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Update an act."""
    now = _now_iso()

    with _transaction() as conn:
        # Build update query dynamically
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if color is not None:
            updates.append("color = ?")
            params.append(color)

        params.append(act_id)

        conn.execute(f"""
            UPDATE acts SET {', '.join(updates)} WHERE act_id = ?
        """, params)

    return list_acts()


def set_active_act(act_id: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """Set the active act."""
    with _transaction() as conn:
        # Deactivate all
        conn.execute("UPDATE acts SET active = 0")

        # Activate the specified act
        if act_id:
            conn.execute("UPDATE acts SET active = 1 WHERE act_id = ?", (act_id,))

    return list_acts()


def delete_act(act_id: str) -> tuple[list[dict[str, Any]], str | None]:
    """Delete an act and all its scenes/beats."""
    with _transaction() as conn:
        conn.execute("DELETE FROM acts WHERE act_id = ?", (act_id,))

    return list_acts()


def assign_repo_to_act(*, act_id: str, repo_path: str | None, artifact_type: str | None = None) -> dict[str, Any] | None:
    """Assign a repository path to an act."""
    now = _now_iso()

    with _transaction() as conn:
        conn.execute("""
            UPDATE acts SET repo_path = ?, artifact_type = ?, updated_at = ?
            WHERE act_id = ?
        """, (repo_path, artifact_type, now, act_id))

    return get_act(act_id)


# =============================================================================
# Scenes Operations
# =============================================================================

def _ensure_stage_direction_scene_db(conn: sqlite3.Connection, act_id: str) -> str:
    """Ensure an act has a stage direction scene."""
    stage_direction_id = f"stage-direction-{act_id[:12]}"
    now = _now_iso()

    # Check if exists
    cursor = conn.execute(
        "SELECT scene_id FROM scenes WHERE scene_id = ?",
        (stage_direction_id,)
    )
    if cursor.fetchone():
        return stage_direction_id

    # Create it at position 0
    conn.execute("""
        INSERT INTO scenes
        (scene_id, act_id, title, intent, is_stage_direction, position, created_at, updated_at)
        VALUES (?, ?, 'Stage Direction', 'Default container for unassigned Beats', 1, 0, ?, ?)
    """, (stage_direction_id, act_id, now, now))

    return stage_direction_id


def list_scenes(act_id: str) -> list[dict[str, Any]]:
    """List all scenes for an act."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT scene_id, act_id, title, intent, status, time_horizon, notes, is_stage_direction
        FROM scenes
        WHERE act_id = ?
        ORDER BY position ASC
    """, (act_id,))

    return [
        {
            "scene_id": row["scene_id"],
            "act_id": row["act_id"],
            "title": row["title"],
            "intent": row["intent"],
            "status": row["status"],
            "time_horizon": row["time_horizon"],
            "notes": row["notes"],
            "is_stage_direction": bool(row["is_stage_direction"]),
        }
        for row in cursor
    ]


def create_scene(*, act_id: str, title: str, intent: str = "", status: str = "",
                 time_horizon: str = "", notes: str = "") -> tuple[list[dict[str, Any]], str]:
    """Create a new scene."""
    scene_id = _new_id("scene")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position for this act
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM scenes WHERE act_id = ?",
            (act_id,)
        )
        position = cursor.fetchone()[0]

        conn.execute("""
            INSERT INTO scenes
            (scene_id, act_id, title, intent, status, time_horizon, notes, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (scene_id, act_id, title, intent, status, time_horizon, notes, position, now, now))

    return list_scenes(act_id), scene_id


def update_scene(*, act_id: str, scene_id: str, title: str | None = None, intent: str | None = None,
                 status: str | None = None, time_horizon: str | None = None,
                 notes: str | None = None) -> list[dict[str, Any]]:
    """Update a scene."""
    now = _now_iso()

    with _transaction() as conn:
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if intent is not None:
            updates.append("intent = ?")
            params.append(intent)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if time_horizon is not None:
            updates.append("time_horizon = ?")
            params.append(time_horizon)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        params.append(scene_id)

        conn.execute(f"""
            UPDATE scenes SET {', '.join(updates)} WHERE scene_id = ?
        """, params)

    return list_scenes(act_id)


def delete_scene(act_id: str, scene_id: str) -> list[dict[str, Any]]:
    """Delete a scene and all its beats."""
    with _transaction() as conn:
        conn.execute("DELETE FROM scenes WHERE scene_id = ?", (scene_id,))

    return list_scenes(act_id)


# =============================================================================
# Beats Operations
# =============================================================================

def list_beats(act_id: str, scene_id: str) -> list[dict[str, Any]]:
    """List all beats for a scene."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule
        FROM beats
        WHERE scene_id = ?
        ORDER BY position ASC
    """, (scene_id,))

    return [
        {
            "beat_id": row["beat_id"],
            "scene_id": row["scene_id"],
            "title": row["title"],
            "stage": row["stage"],
            "notes": row["notes"],
            "link": row["link"],
            "calendar_event_id": row["calendar_event_id"],
            "recurrence_rule": row["recurrence_rule"],
        }
        for row in cursor
    ]


def get_beat(beat_id: str) -> dict[str, Any] | None:
    """Get a beat by ID."""
    conn = _get_connection()
    cursor = conn.execute("""
        SELECT beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule
        FROM beats WHERE beat_id = ?
    """, (beat_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "beat_id": row["beat_id"],
        "scene_id": row["scene_id"],
        "title": row["title"],
        "stage": row["stage"],
        "notes": row["notes"],
        "link": row["link"],
        "calendar_event_id": row["calendar_event_id"],
        "recurrence_rule": row["recurrence_rule"],
    }


def create_beat(*, act_id: str, scene_id: str, title: str, stage: str = "planning",
                notes: str = "", link: str | None = None, calendar_event_id: str | None = None,
                recurrence_rule: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """Create a new beat."""
    beat_id = _new_id("beat")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position for this scene
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM beats WHERE scene_id = ?",
            (scene_id,)
        )
        position = cursor.fetchone()[0]

        conn.execute("""
            INSERT INTO beats
            (beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule, position, now, now))

    return list_beats(act_id, scene_id), beat_id


def update_beat(*, act_id: str, scene_id: str, beat_id: str, title: str | None = None,
                stage: str | None = None, notes: str | None = None, link: str | None = None,
                calendar_event_id: str | None = None, recurrence_rule: str | None = None) -> list[dict[str, Any]]:
    """Update a beat."""
    now = _now_iso()

    with _transaction() as conn:
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if stage is not None:
            updates.append("stage = ?")
            params.append(stage)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        if link is not None:
            updates.append("link = ?")
            params.append(link if link else None)
        if calendar_event_id is not None:
            updates.append("calendar_event_id = ?")
            params.append(calendar_event_id if calendar_event_id else None)
        if recurrence_rule is not None:
            updates.append("recurrence_rule = ?")
            params.append(recurrence_rule if recurrence_rule else None)

        params.append(beat_id)

        conn.execute(f"""
            UPDATE beats SET {', '.join(updates)} WHERE beat_id = ?
        """, params)

    return list_beats(act_id, scene_id)


def delete_beat(act_id: str, scene_id: str, beat_id: str) -> list[dict[str, Any]]:
    """Delete a beat."""
    with _transaction() as conn:
        conn.execute("DELETE FROM beats WHERE beat_id = ?", (beat_id,))

    return list_beats(act_id, scene_id)


def move_beat(*, beat_id: str, source_act_id: str, source_scene_id: str,
              target_act_id: str, target_scene_id: str) -> dict[str, Any]:
    """Move a beat to a different scene."""
    now = _now_iso()

    with _transaction() as conn:
        # Verify beat exists
        cursor = conn.execute("SELECT beat_id FROM beats WHERE beat_id = ?", (beat_id,))
        if not cursor.fetchone():
            raise ValueError(f"Beat not found: {beat_id}")

        # Get max position in target scene
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM beats WHERE scene_id = ?",
            (target_scene_id,)
        )
        position = cursor.fetchone()[0]

        # Move the beat
        conn.execute("""
            UPDATE beats SET scene_id = ?, position = ?, updated_at = ?
            WHERE beat_id = ?
        """, (target_scene_id, position, now, beat_id))

    return {
        "beat_id": beat_id,
        "target_act_id": target_act_id,
        "target_scene_id": target_scene_id,
    }


def find_beat_location(beat_id: str) -> dict[str, str | None] | None:
    """Find the act and scene containing a beat.

    This is the CANONICAL source for beat location.
    """
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT b.beat_id, s.scene_id, s.title as scene_title, a.act_id, a.title as act_title
        FROM beats b
        JOIN scenes s ON b.scene_id = s.scene_id
        JOIN acts a ON s.act_id = a.act_id
        WHERE b.beat_id = ?
    """, (beat_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "act_id": row["act_id"],
        "act_title": row["act_title"],
        "scene_id": row["scene_id"],
        "scene_title": row["scene_title"],
    }


def find_beat_by_calendar_event(calendar_event_id: str) -> dict[str, Any] | None:
    """Find a beat by its calendar event ID."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT beat_id, scene_id, title, stage, notes, link, calendar_event_id, recurrence_rule
        FROM beats WHERE calendar_event_id = ?
    """, (calendar_event_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "beat_id": row["beat_id"],
        "scene_id": row["scene_id"],
        "title": row["title"],
        "stage": row["stage"],
        "notes": row["notes"],
        "link": row["link"],
        "calendar_event_id": row["calendar_event_id"],
        "recurrence_rule": row["recurrence_rule"],
    }


# =============================================================================
# Attachments Operations
# =============================================================================

def list_attachments(*, act_id: str | None = None, scene_id: str | None = None,
                     beat_id: str | None = None) -> list[dict[str, Any]]:
    """List attachments, optionally filtered by scope."""
    conn = _get_connection()

    query = "SELECT * FROM attachments WHERE 1=1"
    params: list[Any] = []

    if act_id:
        query += " AND act_id = ?"
        params.append(act_id)
    if scene_id:
        query += " AND scene_id = ?"
        params.append(scene_id)
    if beat_id:
        query += " AND beat_id = ?"
        params.append(beat_id)

    cursor = conn.execute(query, params)

    return [
        {
            "attachment_id": row["attachment_id"],
            "act_id": row["act_id"],
            "scene_id": row["scene_id"],
            "beat_id": row["beat_id"],
            "file_path": row["file_path"],
            "file_name": row["file_name"],
            "file_type": row["file_type"],
            "added_at": row["added_at"],
        }
        for row in cursor
    ]


def add_attachment(*, act_id: str | None = None, scene_id: str | None = None,
                   beat_id: str | None = None, file_path: str,
                   file_name: str | None = None) -> dict[str, Any]:
    """Add a file attachment."""
    attachment_id = _new_id("att")
    now = _now_iso()

    path = Path(file_path)
    if not file_name:
        file_name = path.name
    file_type = path.suffix.lstrip(".")

    with _transaction() as conn:
        conn.execute("""
            INSERT INTO attachments
            (attachment_id, act_id, scene_id, beat_id, file_path, file_name, file_type, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (attachment_id, act_id, scene_id, beat_id, file_path, file_name, file_type, now))

    return {
        "attachment_id": attachment_id,
        "act_id": act_id,
        "scene_id": scene_id,
        "beat_id": beat_id,
        "file_path": file_path,
        "file_name": file_name,
        "file_type": file_type,
        "added_at": now,
    }


def remove_attachment(attachment_id: str) -> bool:
    """Remove an attachment."""
    with _transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM attachments WHERE attachment_id = ?",
            (attachment_id,)
        )
        return cursor.rowcount > 0


# =============================================================================
# Special Operations
# =============================================================================

def ensure_your_story_act() -> tuple[list[dict[str, Any]], str]:
    """Ensure 'Your Story' Act exists."""
    YOUR_STORY_ACT_ID = "your-story"

    init_db()

    act = get_act(YOUR_STORY_ACT_ID)
    if act:
        acts, _ = list_acts()
        return acts, YOUR_STORY_ACT_ID

    # Create Your Story act
    now = _now_iso()
    with _transaction() as conn:
        conn.execute("""
            INSERT INTO acts (act_id, title, active, notes, position, created_at, updated_at)
            VALUES (?, 'Your Story', 0, 'The overarching narrative of your life. Unassigned Beats live here.', 0, ?, ?)
        """, (YOUR_STORY_ACT_ID, now, now))

        _ensure_stage_direction_scene_db(conn, YOUR_STORY_ACT_ID)

    acts, _ = list_acts()
    return acts, YOUR_STORY_ACT_ID
