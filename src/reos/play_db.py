"""SQLite-based storage for The Play.

This module provides atomic, efficient storage for Play data (Acts, Scenes)
using SQLite instead of JSON files. The KB files (markdown) remain as files since
they are human-editable and can be large.

Migration: On first use, existing JSON data is automatically migrated to SQLite.

Architecture (v4):
- Acts: Major chapters/themes in your journey
- Scenes: Individual todo items/tasks (formerly called Beats)

The old 3-tier hierarchy (Acts → Scenes → Beats) is now 2-tier (Acts → Scenes).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
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
# v3: Added thunderbird_event_id column to beats table
# v4: Flatten hierarchy - remove old scenes tier, beats become scenes
SCHEMA_VERSION = 4


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


def close_connection() -> None:
    """Close the thread-local database connection.

    This is primarily used for testing to ensure clean state between tests.
    """
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None


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
    """Initialize the database schema.

    For fresh databases (v4+), creates the new 2-tier schema directly.
    For existing databases, runs migrations to get to v4.
    """
    # Check if we have an existing schema version
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    has_schema_version = cursor.fetchone() is not None

    if has_schema_version:
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if row is not None:
            current_version = row[0]
            if current_version < SCHEMA_VERSION:
                _run_schema_migrations(conn, current_version)
            return  # Schema already exists and is up to date

    # Fresh database - create v4 schema directly
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

        -- Scenes table (v4: the todo/task items, formerly called Beats)
        CREATE TABLE IF NOT EXISTS scenes (
            scene_id TEXT PRIMARY KEY,
            act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'planning',
            notes TEXT NOT NULL DEFAULT '',
            link TEXT,
            calendar_event_id TEXT,
            recurrence_rule TEXT,
            thunderbird_event_id TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_scenes_act_id ON scenes(act_id);
        CREATE INDEX IF NOT EXISTS idx_scenes_calendar_event ON scenes(calendar_event_id);
        CREATE INDEX IF NOT EXISTS idx_scenes_thunderbird_event ON scenes(thunderbird_event_id);

        -- Attachments table
        CREATE TABLE IF NOT EXISTS attachments (
            attachment_id TEXT PRIMARY KEY,
            act_id TEXT REFERENCES acts(act_id) ON DELETE CASCADE,
            scene_id TEXT REFERENCES scenes(scene_id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            added_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_act ON attachments(act_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_scene ON attachments(scene_id);
    """)

    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))


def _run_schema_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Run schema migrations from current_version to SCHEMA_VERSION."""
    if current_version >= SCHEMA_VERSION:
        return

    logger.info(f"Running schema migrations from v{current_version} to v{SCHEMA_VERSION}")

    # Migration v1 -> v2: Add color column to acts table
    if current_version < 2:
        cursor = conn.execute("PRAGMA table_info(acts)")
        columns = [row[1] for row in cursor.fetchall()]
        if "color" not in columns:
            logger.info("Adding color column to acts table")
            conn.execute("ALTER TABLE acts ADD COLUMN color TEXT")

    # Migration v2 -> v3: Add thunderbird_event_id column to beats table
    if current_version < 3 and current_version > 0:
        cursor = conn.execute("PRAGMA table_info(beats)")
        columns = [row[1] for row in cursor.fetchall()]
        if "thunderbird_event_id" not in columns:
            logger.info("Adding thunderbird_event_id column to beats table")
            conn.execute("ALTER TABLE beats ADD COLUMN thunderbird_event_id TEXT")

    # Migration v3 -> v4: Flatten hierarchy (beats become scenes)
    if current_version < 4:
        logger.info("Running v4 migration: Flatten hierarchy (beats → scenes)")
        _migrate_v3_to_v4(conn)

    # Update schema version
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    logger.info(f"Schema migrated to v{SCHEMA_VERSION}")


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Migrate from v3 (3-tier) to v4 (2-tier) schema.

    Beats become Scenes, old Scenes tier is removed.
    """
    # Step 1: Check if beats table exists (might be fresh install)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='beats'"
    )
    if not cursor.fetchone():
        logger.info("No beats table found, nothing to migrate")
        return

    # Step 2: Add act_id column to beats table
    cursor = conn.execute("PRAGMA table_info(beats)")
    columns = [row[1] for row in cursor.fetchall()]
    if "act_id" not in columns:
        logger.info("Adding act_id column to beats table")
        conn.execute("ALTER TABLE beats ADD COLUMN act_id TEXT")

    # Step 3: Backfill act_id from parent scene
    logger.info("Backfilling act_id from parent scenes")
    conn.execute("""
        UPDATE beats
        SET act_id = (SELECT act_id FROM scenes WHERE scenes.scene_id = beats.scene_id)
        WHERE act_id IS NULL
    """)

    # Step 4: Create new scenes table with v4 structure
    logger.info("Creating new scenes table structure")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scenes_new (
            scene_id TEXT PRIMARY KEY,
            act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'planning',
            notes TEXT NOT NULL DEFAULT '',
            link TEXT,
            calendar_event_id TEXT,
            recurrence_rule TEXT,
            thunderbird_event_id TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Step 5: Copy beats → scenes_new (using beat_id as scene_id)
    logger.info("Copying beats to new scenes table")
    conn.execute("""
        INSERT INTO scenes_new (scene_id, act_id, title, stage, notes, link,
            calendar_event_id, recurrence_rule, thunderbird_event_id, position, created_at, updated_at)
        SELECT beat_id, act_id, title, stage, notes, link,
            calendar_event_id, recurrence_rule, thunderbird_event_id, position, created_at, updated_at
        FROM beats
        WHERE act_id IS NOT NULL
    """)

    # Step 6: Update attachments - migrate beat_id references to scene_id
    logger.info("Migrating attachment references")
    # First check if beat_id column exists in attachments
    cursor = conn.execute("PRAGMA table_info(attachments)")
    att_columns = [row[1] for row in cursor.fetchall()]
    if "beat_id" in att_columns:
        conn.execute("""
            UPDATE attachments SET scene_id = beat_id WHERE beat_id IS NOT NULL
        """)

    # Step 7: Drop old tables and rename new
    logger.info("Dropping old tables and renaming")
    conn.execute("DROP TABLE IF EXISTS beats")
    conn.execute("DROP TABLE IF EXISTS scenes")
    conn.execute("ALTER TABLE scenes_new RENAME TO scenes")

    # Step 8: Create indexes on new scenes table
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scenes_act_id ON scenes(act_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scenes_calendar_event ON scenes(calendar_event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scenes_thunderbird_event ON scenes(thunderbird_event_id)")

    # Step 9: Clean up attachments table - remove beat_id column if it exists
    # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
    if "beat_id" in att_columns:
        logger.info("Cleaning up attachments table")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attachments_new (
                attachment_id TEXT PRIMARY KEY,
                act_id TEXT REFERENCES acts(act_id) ON DELETE CASCADE,
                scene_id TEXT REFERENCES scenes(scene_id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO attachments_new (attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at)
            SELECT attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at
            FROM attachments
        """)
        conn.execute("DROP TABLE attachments")
        conn.execute("ALTER TABLE attachments_new RENAME TO attachments")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attachments_act ON attachments(act_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attachments_scene ON attachments(scene_id)")

    logger.info("v4 migration complete")


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
    """Migrate existing JSON data to SQLite.

    This handles fresh JSON imports into the v4 schema.
    """
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

    logger.info("Migrating Play data from JSON to SQLite (v4 schema)...")

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

            # Load scenes for this act (these contain beats in old structure)
            scenes_json = play_root / "acts" / act_id / "scenes.json"
            if scenes_json.exists():
                try:
                    with open(scenes_json, encoding="utf-8") as f:
                        scenes_data = json.load(f)

                    scenes_list = scenes_data.get("scenes", [])
                    scene_position = 0

                    for old_scene in scenes_list:
                        if not isinstance(old_scene, dict):
                            continue

                        # Load beats from this old scene and convert to new scenes
                        beats_list = old_scene.get("beats", [])
                        for beat in beats_list:
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

                            # Insert as new scene (beat_id becomes scene_id)
                            conn.execute("""
                                INSERT OR IGNORE INTO scenes
                                (scene_id, act_id, title, stage, notes, link, calendar_event_id,
                                 recurrence_rule, thunderbird_event_id, position, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                beat_id,  # beat_id becomes scene_id
                                act_id,
                                beat.get("title", "Untitled"),
                                stage,
                                beat.get("notes", ""),
                                beat.get("link"),
                                beat.get("calendar_event_id"),
                                beat.get("recurrence_rule"),
                                beat.get("thunderbird_event_id"),
                                scene_position,
                                now,
                                now,
                            ))
                            scene_position += 1

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

                            # Map beat_id to scene_id
                            scene_id = att.get("beat_id") or att.get("scene_id")

                            conn.execute("""
                                INSERT OR IGNORE INTO attachments
                                (attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                att.get("attachment_id", _new_id("att")),
                                att.get("act_id"),
                                scene_id,
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
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config, color
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
            "color": row["color"],
        }
        acts.append(act)

        if row["active"]:
            active_act_id = row["act_id"]

    return acts, active_act_id


def get_act(act_id: str) -> dict[str, Any] | None:
    """Get a single act by ID."""
    conn = _get_connection()
    cursor = conn.execute("""
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config, color
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
        "color": row["color"],
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
    """Delete an act and all its scenes."""
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
# Scenes Operations (formerly Beats)
# =============================================================================

def list_scenes(act_id: str) -> list[dict[str, Any]]:
    """List all scenes for an act."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes
        WHERE act_id = ?
        ORDER BY position ASC
    """, (act_id,))

    return [
        {
            "scene_id": row["scene_id"],
            "act_id": row["act_id"],
            "title": row["title"],
            "stage": row["stage"],
            "notes": row["notes"],
            "link": row["link"],
            "calendar_event_id": row["calendar_event_id"],
            "recurrence_rule": row["recurrence_rule"],
            "thunderbird_event_id": row["thunderbird_event_id"],
        }
        for row in cursor
    ]


def get_scene(scene_id: str) -> dict[str, Any] | None:
    """Get a scene by ID."""
    conn = _get_connection()
    cursor = conn.execute("""
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes WHERE scene_id = ?
    """, (scene_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "scene_id": row["scene_id"],
        "act_id": row["act_id"],
        "title": row["title"],
        "stage": row["stage"],
        "notes": row["notes"],
        "link": row["link"],
        "calendar_event_id": row["calendar_event_id"],
        "recurrence_rule": row["recurrence_rule"],
        "thunderbird_event_id": row["thunderbird_event_id"],
    }


def create_scene(*, act_id: str, title: str, stage: str = "planning",
                 notes: str = "", link: str | None = None, calendar_event_id: str | None = None,
                 recurrence_rule: str | None = None,
                 thunderbird_event_id: str | None = None) -> tuple[list[dict[str, Any]], str]:
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
            (scene_id, act_id, title, stage, notes, link, calendar_event_id, recurrence_rule,
             thunderbird_event_id, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (scene_id, act_id, title, stage, notes, link, calendar_event_id, recurrence_rule,
              thunderbird_event_id, position, now, now))

    return list_scenes(act_id), scene_id


def update_scene(*, act_id: str, scene_id: str, title: str | None = None,
                 stage: str | None = None, notes: str | None = None, link: str | None = None,
                 calendar_event_id: str | None = None, recurrence_rule: str | None = None,
                 thunderbird_event_id: str | None = None) -> list[dict[str, Any]]:
    """Update a scene."""
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
        if thunderbird_event_id is not None:
            updates.append("thunderbird_event_id = ?")
            params.append(thunderbird_event_id if thunderbird_event_id else None)

        params.append(scene_id)

        conn.execute(f"""
            UPDATE scenes SET {', '.join(updates)} WHERE scene_id = ?
        """, params)

    return list_scenes(act_id)


def delete_scene(act_id: str, scene_id: str) -> list[dict[str, Any]]:
    """Delete a scene."""
    with _transaction() as conn:
        conn.execute("DELETE FROM scenes WHERE scene_id = ?", (scene_id,))

    return list_scenes(act_id)


def move_scene(*, scene_id: str, source_act_id: str,
               target_act_id: str) -> dict[str, Any]:
    """Move a scene to a different act."""
    now = _now_iso()

    with _transaction() as conn:
        # Verify scene exists
        cursor = conn.execute("SELECT scene_id FROM scenes WHERE scene_id = ?", (scene_id,))
        if not cursor.fetchone():
            raise ValueError(f"Scene not found: {scene_id}")

        # Get max position in target act
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM scenes WHERE act_id = ?",
            (target_act_id,)
        )
        position = cursor.fetchone()[0]

        # Move the scene
        conn.execute("""
            UPDATE scenes SET act_id = ?, position = ?, updated_at = ?
            WHERE scene_id = ?
        """, (target_act_id, position, now, scene_id))

    return {
        "scene_id": scene_id,
        "target_act_id": target_act_id,
    }


def find_scene_location(scene_id: str) -> dict[str, str | None] | None:
    """Find the act containing a scene.

    This is the CANONICAL source for scene location.
    """
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT s.scene_id, a.act_id, a.title as act_title
        FROM scenes s
        JOIN acts a ON s.act_id = a.act_id
        WHERE s.scene_id = ?
    """, (scene_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "act_id": row["act_id"],
        "act_title": row["act_title"],
        "scene_id": row["scene_id"],
    }


def find_scene_by_calendar_event(calendar_event_id: str) -> dict[str, Any] | None:
    """Find a scene by its calendar event ID (inbound sync)."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes WHERE calendar_event_id = ?
    """, (calendar_event_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "scene_id": row["scene_id"],
        "act_id": row["act_id"],
        "title": row["title"],
        "stage": row["stage"],
        "notes": row["notes"],
        "link": row["link"],
        "calendar_event_id": row["calendar_event_id"],
        "recurrence_rule": row["recurrence_rule"],
        "thunderbird_event_id": row["thunderbird_event_id"],
    }


def find_scene_by_thunderbird_event(thunderbird_event_id: str) -> dict[str, Any] | None:
    """Find a scene by its Thunderbird event ID (outbound sync)."""
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes WHERE thunderbird_event_id = ?
    """, (thunderbird_event_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "scene_id": row["scene_id"],
        "act_id": row["act_id"],
        "title": row["title"],
        "stage": row["stage"],
        "notes": row["notes"],
        "link": row["link"],
        "calendar_event_id": row["calendar_event_id"],
        "recurrence_rule": row["recurrence_rule"],
        "thunderbird_event_id": row["thunderbird_event_id"],
    }


def set_scene_thunderbird_event_id(scene_id: str, thunderbird_event_id: str | None) -> bool:
    """Set the Thunderbird event ID for a Scene (outbound sync).

    Args:
        scene_id: The Scene ID to update.
        thunderbird_event_id: The Thunderbird event ID, or None to clear.

    Returns:
        True if updated, False if scene not found.
    """
    now = _now_iso()

    with _transaction() as conn:
        cursor = conn.execute("""
            UPDATE scenes SET thunderbird_event_id = ?, updated_at = ?
            WHERE scene_id = ?
        """, (thunderbird_event_id, now, scene_id))

        return cursor.rowcount > 0


def clear_scene_thunderbird_event_id(scene_id: str) -> bool:
    """Clear the Thunderbird event ID for a Scene.

    Args:
        scene_id: The Scene ID to update.

    Returns:
        True if updated, False if scene not found.
    """
    return set_scene_thunderbird_event_id(scene_id, None)


# =============================================================================
# Backward Compatibility Aliases (Beat → Scene)
# =============================================================================
# These aliases allow existing code to continue working during migration.

def list_beats(act_id: str, scene_id: str | None = None) -> list[dict[str, Any]]:
    """Legacy alias for list_scenes. The scene_id parameter is ignored."""
    return list_scenes(act_id)


def get_beat(beat_id: str) -> dict[str, Any] | None:
    """Legacy alias for get_scene."""
    scene = get_scene(beat_id)
    if scene:
        # Map scene fields to beat fields for compatibility
        return {
            "beat_id": scene["scene_id"],
            "scene_id": scene["act_id"],  # Old beats had scene_id reference
            "title": scene["title"],
            "stage": scene["stage"],
            "notes": scene["notes"],
            "link": scene["link"],
            "calendar_event_id": scene["calendar_event_id"],
            "recurrence_rule": scene["recurrence_rule"],
            "thunderbird_event_id": scene["thunderbird_event_id"],
        }
    return None


def create_beat(*, act_id: str, scene_id: str | None = None, title: str, stage: str = "planning",
                notes: str = "", link: str | None = None, calendar_event_id: str | None = None,
                recurrence_rule: str | None = None,
                thunderbird_event_id: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """Legacy alias for create_scene. The scene_id parameter is ignored."""
    scenes, new_id = create_scene(
        act_id=act_id, title=title, stage=stage, notes=notes, link=link,
        calendar_event_id=calendar_event_id, recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id
    )
    # Return in beat format
    return [
        {
            "beat_id": s["scene_id"],
            "title": s["title"],
            "stage": s["stage"],
            "notes": s["notes"],
            "link": s["link"],
            "calendar_event_id": s["calendar_event_id"],
            "recurrence_rule": s["recurrence_rule"],
            "thunderbird_event_id": s["thunderbird_event_id"],
        }
        for s in scenes
    ], new_id


def update_beat(*, act_id: str, scene_id: str | None = None, beat_id: str,
                title: str | None = None, stage: str | None = None,
                notes: str | None = None, link: str | None = None,
                calendar_event_id: str | None = None, recurrence_rule: str | None = None,
                thunderbird_event_id: str | None = None) -> list[dict[str, Any]]:
    """Legacy alias for update_scene."""
    scenes = update_scene(
        act_id=act_id, scene_id=beat_id, title=title, stage=stage, notes=notes,
        link=link, calendar_event_id=calendar_event_id, recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id
    )
    return [
        {
            "beat_id": s["scene_id"],
            "title": s["title"],
            "stage": s["stage"],
            "notes": s["notes"],
            "link": s["link"],
            "calendar_event_id": s["calendar_event_id"],
            "recurrence_rule": s["recurrence_rule"],
            "thunderbird_event_id": s["thunderbird_event_id"],
        }
        for s in scenes
    ]


def delete_beat(act_id: str, scene_id_param: str, beat_id: str) -> list[dict[str, Any]]:
    """Legacy alias for delete_scene."""
    scenes = delete_scene(act_id, beat_id)
    return [
        {
            "beat_id": s["scene_id"],
            "title": s["title"],
            "stage": s["stage"],
            "notes": s["notes"],
            "link": s["link"],
            "calendar_event_id": s["calendar_event_id"],
            "recurrence_rule": s["recurrence_rule"],
            "thunderbird_event_id": s["thunderbird_event_id"],
        }
        for s in scenes
    ]


def find_beat_location(beat_id: str) -> dict[str, str | None] | None:
    """Legacy alias for find_scene_location."""
    location = find_scene_location(beat_id)
    if location:
        # Add scene_id for backward compat (though it's not meaningful in v4)
        location["scene_id"] = None
        location["scene_title"] = None
    return location


def find_beat_by_calendar_event(calendar_event_id: str) -> dict[str, Any] | None:
    """Legacy alias for find_scene_by_calendar_event."""
    scene = find_scene_by_calendar_event(calendar_event_id)
    if scene:
        return {
            "beat_id": scene["scene_id"],
            "scene_id": scene["act_id"],
            "title": scene["title"],
            "stage": scene["stage"],
            "notes": scene["notes"],
            "link": scene["link"],
            "calendar_event_id": scene["calendar_event_id"],
            "recurrence_rule": scene["recurrence_rule"],
            "thunderbird_event_id": scene["thunderbird_event_id"],
        }
    return None


def find_beat_by_thunderbird_event(thunderbird_event_id: str) -> dict[str, Any] | None:
    """Legacy alias for find_scene_by_thunderbird_event."""
    scene = find_scene_by_thunderbird_event(thunderbird_event_id)
    if scene:
        return {
            "beat_id": scene["scene_id"],
            "scene_id": scene["act_id"],
            "title": scene["title"],
            "stage": scene["stage"],
            "notes": scene["notes"],
            "link": scene["link"],
            "calendar_event_id": scene["calendar_event_id"],
            "recurrence_rule": scene["recurrence_rule"],
            "thunderbird_event_id": scene["thunderbird_event_id"],
        }
    return None


def set_beat_thunderbird_event_id(beat_id: str, thunderbird_event_id: str | None) -> bool:
    """Legacy alias for set_scene_thunderbird_event_id."""
    return set_scene_thunderbird_event_id(beat_id, thunderbird_event_id)


def clear_beat_thunderbird_event_id(beat_id: str) -> bool:
    """Legacy alias for clear_scene_thunderbird_event_id."""
    return clear_scene_thunderbird_event_id(beat_id)


# =============================================================================
# Attachments Operations
# =============================================================================

def list_attachments(*, act_id: str | None = None, scene_id: str | None = None,
                     beat_id: str | None = None) -> list[dict[str, Any]]:
    """List attachments, optionally filtered by scope.

    For backward compatibility, beat_id is treated as scene_id.
    """
    conn = _get_connection()

    # Treat beat_id as scene_id for backward compat
    if beat_id and not scene_id:
        scene_id = beat_id

    query = "SELECT * FROM attachments WHERE 1=1"
    params: list[Any] = []

    if act_id:
        query += " AND act_id = ?"
        params.append(act_id)
    if scene_id:
        query += " AND scene_id = ?"
        params.append(scene_id)

    cursor = conn.execute(query, params)

    return [
        {
            "attachment_id": row["attachment_id"],
            "act_id": row["act_id"],
            "scene_id": row["scene_id"],
            "beat_id": row["scene_id"],  # backward compat
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
    """Add a file attachment.

    For backward compatibility, beat_id is treated as scene_id.
    """
    attachment_id = _new_id("att")
    now = _now_iso()

    # Treat beat_id as scene_id for backward compat
    if beat_id and not scene_id:
        scene_id = beat_id

    path = Path(file_path)
    if not file_name:
        file_name = path.name
    file_type = path.suffix.lstrip(".")

    with _transaction() as conn:
        conn.execute("""
            INSERT INTO attachments
            (attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (attachment_id, act_id, scene_id, file_path, file_name, file_type, now))

    return {
        "attachment_id": attachment_id,
        "act_id": act_id,
        "scene_id": scene_id,
        "beat_id": scene_id,  # backward compat
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
            VALUES (?, 'Your Story', 0, 'The overarching narrative of your life.', 0, ?, ?)
        """, (YOUR_STORY_ACT_ID, now, now))

    acts, _ = list_acts()
    return acts, YOUR_STORY_ACT_ID
