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
# v5: Add pages table for nested knowledgebase pages
# v6: Add calendar metadata columns to scenes (consolidate from cairn_metadata)
# v7: Add blocks, block_properties, rich_text tables for Notion-style block editor
# v8: Add root_block_id to acts for block-based root content
# v9: Add disable_auto_complete column to scenes (auto-complete vs needs_attention on overdue)
# v10: Enforce recurring scenes cannot be 'complete' - cleanup existing data
# v11: Add block_relationships and block_embeddings tables for memory graph
SCHEMA_VERSION = 11


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
        except Exception as e:
            logger.debug("Error closing play_db connection (non-critical): %s", e)
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
            root_block_id TEXT,  -- v8: Root block for act's main content
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- Scenes table (v4: the todo/task items, formerly called Beats)
        -- v6: Added calendar metadata columns (calendar_event_start, etc.)
        -- v9: Added disable_auto_complete for overdue behavior control
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
            -- v6: Calendar metadata columns (consolidated from cairn_metadata)
            calendar_event_start TEXT,
            calendar_event_end TEXT,
            calendar_event_title TEXT,
            next_occurrence TEXT,
            calendar_name TEXT,
            category TEXT,
            -- v9: When true, overdue scenes go to need_attention instead of auto-completing
            disable_auto_complete INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_scenes_act_id ON scenes(act_id);
        CREATE INDEX IF NOT EXISTS idx_scenes_calendar_event ON scenes(calendar_event_id);
        CREATE INDEX IF NOT EXISTS idx_scenes_thunderbird_event ON scenes(thunderbird_event_id);
        CREATE INDEX IF NOT EXISTS idx_scenes_next_occurrence ON scenes(next_occurrence);
        -- Unique constraint on calendar_event_id to prevent duplicate syncs
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scenes_calendar_event_unique
            ON scenes(calendar_event_id) WHERE calendar_event_id IS NOT NULL;

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

        -- Pages table (v5: nested knowledgebase pages under Acts)
        CREATE TABLE IF NOT EXISTS pages (
            page_id TEXT PRIMARY KEY,
            act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
            parent_page_id TEXT REFERENCES pages(page_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            icon TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pages_act_id ON pages(act_id);
        CREATE INDEX IF NOT EXISTS idx_pages_parent ON pages(parent_page_id);

        -- Blocks table (v7: Notion-style block editor)
        CREATE TABLE IF NOT EXISTS blocks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            parent_id TEXT,
            act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
            page_id TEXT REFERENCES pages(page_id) ON DELETE CASCADE,
            scene_id TEXT REFERENCES scenes(scene_id) ON DELETE SET NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_blocks_parent ON blocks(parent_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_act ON blocks(act_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_page ON blocks(page_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_position ON blocks(parent_id, position);

        -- Block properties table (v7: key-value for type-specific data)
        CREATE TABLE IF NOT EXISTS block_properties (
            block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (block_id, key)
        );

        -- Rich text table (v7: inline formatted text spans)
        CREATE TABLE IF NOT EXISTS rich_text (
            id TEXT PRIMARY KEY,
            block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            bold INTEGER DEFAULT 0,
            italic INTEGER DEFAULT 0,
            strikethrough INTEGER DEFAULT 0,
            code INTEGER DEFAULT 0,
            underline INTEGER DEFAULT 0,
            color TEXT,
            background_color TEXT,
            link_url TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_rich_text_block ON rich_text(block_id);
        CREATE INDEX IF NOT EXISTS idx_rich_text_position ON rich_text(block_id, position);

        -- Block relationships table (v11: Memory graph for semantic connections)
        CREATE TABLE IF NOT EXISTS block_relationships (
            id TEXT PRIMARY KEY,
            source_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            target_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            relationship_type TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            weight REAL DEFAULT 1.0,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source_block_id, target_block_id, relationship_type),
            CHECK(source_block_id != target_block_id)
        );

        CREATE INDEX IF NOT EXISTS idx_block_rel_source ON block_relationships(source_block_id);
        CREATE INDEX IF NOT EXISTS idx_block_rel_target ON block_relationships(target_block_id);
        CREATE INDEX IF NOT EXISTS idx_block_rel_type ON block_relationships(relationship_type);

        -- Block embeddings table (v11: Vector embeddings for semantic search)
        CREATE TABLE IF NOT EXISTS block_embeddings (
            block_id TEXT PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_block_emb_hash ON block_embeddings(content_hash);
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

    # Migration v4 -> v5: Add pages table for nested knowledgebase pages
    if current_version < 5:
        logger.info("Running v5 migration: Add pages table")
        _migrate_v4_to_v5(conn)

    # Migration v5 -> v6: Add calendar metadata columns to scenes table
    if current_version < 6:
        logger.info("Running v6 migration: Add calendar metadata columns to scenes")
        _migrate_v5_to_v6(conn)

    # Migration v6 -> v7: Add blocks, block_properties, rich_text tables
    if current_version < 7:
        logger.info("Running v7 migration: Add block editor tables")
        _migrate_v6_to_v7(conn)

    # Migration v7 -> v8: Add root_block_id to acts table
    if current_version < 8:
        logger.info("Running v8 migration: Add root_block_id to acts")
        _migrate_v7_to_v8(conn)

    # Migration v8 -> v9: Add disable_auto_complete to scenes table
    if current_version < 9:
        logger.info("Running v9 migration: Add disable_auto_complete to scenes")
        _migrate_v8_to_v9(conn)

    # Migration v9 -> v10: Enforce recurring scenes cannot be 'complete'
    if current_version < 10:
        logger.info("Running v10 migration: Clean up recurring scenes in 'complete' stage")
        _migrate_v9_to_v10(conn)

    # Migration v10 -> v11: Add block_relationships and block_embeddings tables
    if current_version < 11:
        logger.info("Running v11 migration: Add memory graph tables")
        _migrate_v10_to_v11(conn)

    # Update schema version
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    logger.info(f"Schema migrated to v{SCHEMA_VERSION}")


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Migrate from v3 (3-tier) to v4 (2-tier) schema.

    Beats become Scenes, old Scenes tier is removed.
    """
    # Step 1: Check if beats table exists (might be fresh install)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='beats'")
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenes_calendar_event ON scenes(calendar_event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenes_thunderbird_event ON scenes(thunderbird_event_id)"
    )

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


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Migrate from v4 to v5 schema.

    Adds the pages table for nested knowledgebase pages.
    Also adds unique index on calendar_event_id to prevent duplicate syncs.
    """
    # Check if pages table already exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pages'")
    if not cursor.fetchone():
        # Create pages table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id TEXT PRIMARY KEY,
                act_id TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
                parent_page_id TEXT REFERENCES pages(page_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                icon TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_act_id ON pages(act_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_parent ON pages(parent_page_id)")
        logger.info("Created pages table")
    else:
        logger.info("Pages table already exists, skipping creation")

    # Add unique index on calendar_event_id to prevent duplicate syncs
    # This is safe to run even if the index already exists (IF NOT EXISTS)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scenes_calendar_event_unique
        ON scenes(calendar_event_id) WHERE calendar_event_id IS NOT NULL
    """)
    logger.info("Ensured unique index on calendar_event_id")

    logger.info("v5 migration complete")


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Migrate from v5 to v6 schema.

    Adds calendar metadata columns to scenes table to consolidate calendar data
    from cairn_metadata into play.db (single source of truth).

    New columns:
    - calendar_event_start: When the event is scheduled
    - calendar_event_end: End time of the event
    - calendar_event_title: Cached title from calendar
    - next_occurrence: For recurring events, the next occurrence
    - calendar_name: Human-readable calendar name
    - category: Classification (event, holiday, birthday)
    """
    # Get current columns
    cursor = conn.execute("PRAGMA table_info(scenes)")
    columns = [row[1] for row in cursor.fetchall()]

    # Add new columns if they don't exist
    new_columns = [
        ("calendar_event_start", "TEXT"),
        ("calendar_event_end", "TEXT"),
        ("calendar_event_title", "TEXT"),
        ("next_occurrence", "TEXT"),
        ("calendar_name", "TEXT"),
        ("category", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in columns:
            logger.info(f"Adding {col_name} column to scenes table")
            conn.execute(f"ALTER TABLE scenes ADD COLUMN {col_name} {col_type}")

    # Create index on next_occurrence for efficient querying
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scenes_next_occurrence
        ON scenes(next_occurrence)
    """)

    # Migrate calendar data from cairn_metadata if available
    _migrate_calendar_data_from_cairn(conn)

    logger.info("v6 migration complete")


def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Migrate from v6 to v7 schema.

    Adds blocks, block_properties, and rich_text tables for
    Notion-style block-based content editing.
    """
    # Create blocks table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            parent_id TEXT,
            act_id TEXT NOT NULL,
            page_id TEXT,
            scene_id TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (act_id) REFERENCES acts(act_id) ON DELETE CASCADE,
            FOREIGN KEY (page_id) REFERENCES pages(page_id) ON DELETE CASCADE,
            FOREIGN KEY (scene_id) REFERENCES scenes(scene_id) ON DELETE SET NULL
        )
    """)

    # Create block_properties table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS block_properties (
            block_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (block_id, key),
            FOREIGN KEY (block_id) REFERENCES blocks(id) ON DELETE CASCADE
        )
    """)

    # Create rich_text table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rich_text (
            id TEXT PRIMARY KEY,
            block_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            bold INTEGER DEFAULT 0,
            italic INTEGER DEFAULT 0,
            strikethrough INTEGER DEFAULT 0,
            code INTEGER DEFAULT 0,
            underline INTEGER DEFAULT 0,
            color TEXT,
            background_color TEXT,
            link_url TEXT,
            FOREIGN KEY (block_id) REFERENCES blocks(id) ON DELETE CASCADE
        )
    """)

    # Create indexes for efficient queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_parent ON blocks(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_act ON blocks(act_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_page ON blocks(page_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blocks_position ON blocks(parent_id, position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rich_text_block ON rich_text(block_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rich_text_position ON rich_text(block_id, position)"
    )

    logger.info("v7 migration complete")


def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Migrate from v7 to v8 schema.

    Adds root_block_id column to acts table for block-based root content.
    """
    # Get current columns
    cursor = conn.execute("PRAGMA table_info(acts)")
    columns = [row[1] for row in cursor.fetchall()]

    if "root_block_id" not in columns:
        logger.info("Adding root_block_id column to acts table")
        conn.execute("ALTER TABLE acts ADD COLUMN root_block_id TEXT")

    logger.info("v8 migration complete")


def _migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    """Migrate from v8 to v9 schema.

    Adds disable_auto_complete column to scenes table.
    When false (default): Non-recurring scenes auto-complete when overdue.
    When true: Overdue scenes go to need_attention instead of auto-completing.

    Also cleans up recurring scenes that were incorrectly set to 'complete'.
    Recurring scenes represent ongoing series and cannot be completed.
    """
    # Get current columns
    cursor = conn.execute("PRAGMA table_info(scenes)")
    columns = [row[1] for row in cursor.fetchall()]

    if "disable_auto_complete" not in columns:
        logger.info("Adding disable_auto_complete column to scenes table")
        conn.execute(
            "ALTER TABLE scenes ADD COLUMN disable_auto_complete INTEGER NOT NULL DEFAULT 0"
        )

    logger.info("v9 migration complete")


def _migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    """Migrate from v9 to v10 schema.

    Enforces that recurring scenes cannot be in 'complete' stage.
    Recurring scenes represent ongoing series and should never be marked complete.
    This cleans up any existing data that violates this rule.
    """
    # Clean up: Reset any recurring scenes that are in 'complete' stage to 'in_progress'
    cursor = conn.execute(
        """
        UPDATE scenes
        SET stage = 'in_progress', updated_at = ?
        WHERE recurrence_rule IS NOT NULL
          AND recurrence_rule != ''
          AND stage = 'complete'
    """,
        (_now_iso(),),
    )
    cleaned = cursor.rowcount
    if cleaned > 0:
        logger.info(f"Reset {cleaned} recurring scenes from 'complete' to 'in_progress'")
    else:
        logger.info("No recurring scenes needed cleanup")

    logger.info("v10 migration complete")


def _migrate_v10_to_v11(conn: sqlite3.Connection) -> None:
    """Migrate from v10 to v11 schema.

    Adds block_relationships and block_embeddings tables for the
    hybrid vector-graph memory system.

    - block_relationships: Typed edges between blocks (references, follows_from, etc.)
    - block_embeddings: Vector embeddings for semantic search
    """
    # Create block_relationships table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS block_relationships (
            id TEXT PRIMARY KEY,
            source_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            target_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
            relationship_type TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            weight REAL DEFAULT 1.0,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(source_block_id, target_block_id, relationship_type),
            CHECK(source_block_id != target_block_id)
        )
    """)

    # Create indexes for efficient graph traversal
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_block_rel_source ON block_relationships(source_block_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_block_rel_target ON block_relationships(target_block_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_block_rel_type ON block_relationships(relationship_type)"
    )

    # Create block_embeddings table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS block_embeddings (
            block_id TEXT PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Create index for staleness detection
    conn.execute("CREATE INDEX IF NOT EXISTS idx_block_emb_hash ON block_embeddings(content_hash)")

    logger.info("v11 migration complete")


def _migrate_calendar_data_from_cairn(conn: sqlite3.Connection) -> None:
    """Migrate calendar data from cairn_metadata.scene_calendar_links to scenes table.

    This is a one-time migration that copies existing calendar metadata from the
    CAIRN store into play.db for consolidation.
    """
    import os
    from pathlib import Path

    from .settings import settings

    # Find cairn.db path
    base = Path(os.environ.get("REOS_DATA_DIR", settings.data_dir))
    cairn_db_path = base / "play" / ".cairn" / "cairn.db"

    if not cairn_db_path.exists():
        logger.info("No cairn.db found, skipping calendar data migration")
        return

    try:
        # Open cairn.db read-only
        cairn_conn = sqlite3.connect(str(cairn_db_path))
        cairn_conn.row_factory = sqlite3.Row

        # Check if scene_calendar_links table exists
        cursor = cairn_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_calendar_links'"
        )
        if not cursor.fetchone():
            logger.info("No scene_calendar_links table in cairn.db, skipping migration")
            cairn_conn.close()
            return

        # Read all calendar links from cairn
        rows = cairn_conn.execute("""
            SELECT scene_id, calendar_event_id, calendar_event_title,
                   calendar_event_start, calendar_event_end,
                   recurrence_rule, next_occurrence, calendar_name, category
            FROM scene_calendar_links
        """).fetchall()

        cairn_conn.close()

        # Update scenes in play.db with calendar data
        migrated = 0
        for row in rows:
            scene_id = row["scene_id"]
            # Check if scene exists in play.db
            exists = conn.execute("SELECT 1 FROM scenes WHERE scene_id = ?", (scene_id,)).fetchone()

            if exists:
                conn.execute(
                    """
                    UPDATE scenes SET
                        calendar_event_start = COALESCE(calendar_event_start, ?),
                        calendar_event_end = COALESCE(calendar_event_end, ?),
                        calendar_event_title = COALESCE(calendar_event_title, ?),
                        next_occurrence = COALESCE(next_occurrence, ?),
                        calendar_name = COALESCE(calendar_name, ?),
                        category = COALESCE(category, ?)
                    WHERE scene_id = ?
                """,
                    (
                        row["calendar_event_start"],
                        row["calendar_event_end"],
                        row["calendar_event_title"],
                        row["next_occurrence"],
                        row["calendar_name"] if "calendar_name" in row.keys() else None,
                        row["category"] if "category" in row.keys() else None,
                        scene_id,
                    ),
                )
                migrated += 1

        logger.info(f"Migrated calendar data for {migrated} scenes from cairn.db")

    except Exception as e:
        logger.warning(f"Failed to migrate calendar data from cairn.db: {e}")


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

            conn.execute(
                """
                INSERT OR IGNORE INTO acts
                (act_id, title, active, notes, repo_path, artifact_type, code_config, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
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
                ),
            )

            # Load scenes for this act (old JSON had a nested "beats" array per scene)
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

                        # Old JSON had nested "beats" per scene; each becomes a scene row
                        old_items = old_scene.get("beats", [])
                        for old_item in old_items:
                            if not isinstance(old_item, dict):
                                continue

                            item_id = old_item.get("beat_id", "")
                            if not item_id:
                                continue

                            # Migrate legacy status values to stage
                            stage = old_item.get("stage") or old_item.get("status", "planning")
                            if stage in ("pending", "todo"):
                                stage = "planning"
                            elif stage in ("blocked", "waiting"):
                                stage = "awaiting_data"
                            elif stage in ("completed", "done"):
                                stage = "complete"

                            # Insert as scene (old beat_id becomes scene_id)
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO scenes
                                (scene_id, act_id, title, stage, notes, link, calendar_event_id,
                                 recurrence_rule, thunderbird_event_id, position, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    item_id,
                                    act_id,
                                    old_item.get("title", "Untitled"),
                                    stage,
                                    old_item.get("notes", ""),
                                    old_item.get("link"),
                                    old_item.get("calendar_event_id"),
                                    old_item.get("recurrence_rule"),
                                    old_item.get("thunderbird_event_id"),
                                    scene_position,
                                    now,
                                    now,
                                ),
                            )
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

                            conn.execute(
                                """
                                INSERT OR IGNORE INTO attachments
                                (attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    att.get("attachment_id", _new_id("att")),
                                    att.get("act_id"),
                                    scene_id,
                                    att.get("file_path", ""),
                                    att.get("file_name", ""),
                                    att.get("file_type", ""),
                                    att.get("added_at", now),
                                ),
                            )
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
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config, color, root_block_id
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
            "root_block_id": row["root_block_id"],
        }
        acts.append(act)

        if row["active"]:
            active_act_id = row["act_id"]

    return acts, active_act_id


def get_act(act_id: str) -> dict[str, Any] | None:
    """Get a single act by ID."""
    conn = _get_connection()
    cursor = conn.execute(
        """
        SELECT act_id, title, active, notes, repo_path, artifact_type, code_config, color, root_block_id
        FROM acts WHERE act_id = ?
    """,
        (act_id,),
    )

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
        "root_block_id": row["root_block_id"],
    }


def create_act(
    *, title: str, notes: str = "", color: str | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Create a new act."""
    act_id = _new_id("act")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position
        cursor = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM acts")
        position = cursor.fetchone()[0]

        conn.execute(
            """
            INSERT INTO acts (act_id, title, active, notes, color, position, created_at, updated_at)
            VALUES (?, ?, 0, ?, ?, ?, ?, ?)
        """,
            (act_id, title, notes, color, position, now, now),
        )

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

        conn.execute(
            f"""
            UPDATE acts SET {", ".join(updates)} WHERE act_id = ?
        """,
            params,
        )

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


def assign_repo_to_act(
    *,
    act_id: str,
    repo_path: str | None,
    artifact_type: str | None = None,
    code_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Assign a repository path to an act, enabling Code Mode.

    Args:
        act_id: The Act to modify.
        repo_path: Absolute path to git repository, or None to disable Code Mode.
        artifact_type: Language/type hint (e.g., "python", "typescript").
        code_config: Per-Act code configuration.

    Returns:
        Updated acts list and active_id.
    """
    now = _now_iso()

    with _transaction() as conn:
        updates = ["repo_path = ?", "updated_at = ?"]
        params: list[Any] = [repo_path, now]

        if artifact_type is not None:
            updates.append("artifact_type = ?")
            params.append(artifact_type)

        if code_config is not None:
            updates.append("code_config = ?")
            params.append(json.dumps(code_config))

        params.append(act_id)
        conn.execute(
            f"""
            UPDATE acts SET {", ".join(updates)} WHERE act_id = ?
        """,
            params,
        )

    return list_acts()


def configure_code_mode(
    *,
    act_id: str,
    code_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Update Code Mode configuration for an Act.

    Args:
        act_id: The Act to modify.
        code_config: Code configuration dict (test_command, build_command, etc.).

    Returns:
        Updated acts list and active_id.

    Raises:
        ValueError: If the act has no repo_path assigned.
    """
    # Check if act has repo_path
    act = get_act(act_id)
    if not act or not act.get("repo_path"):
        raise ValueError("Cannot configure Code Mode: no repo_path assigned to this Act")

    now = _now_iso()

    with _transaction() as conn:
        conn.execute(
            """
            UPDATE acts SET code_config = ?, updated_at = ?
            WHERE act_id = ?
        """,
            (json.dumps(code_config), now, act_id),
        )

    return list_acts()


# =============================================================================
# Scenes Operations (formerly Beats)
# =============================================================================


def list_scenes(act_id: str) -> list[dict[str, Any]]:
    """List all scenes for an act."""
    conn = _get_connection()

    cursor = conn.execute(
        """
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id,
               calendar_event_start, calendar_event_end, calendar_event_title,
               next_occurrence, calendar_name, category, disable_auto_complete
        FROM scenes
        WHERE act_id = ?
        ORDER BY position ASC
    """,
        (act_id,),
    )

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
            "calendar_event_start": row["calendar_event_start"],
            "calendar_event_end": row["calendar_event_end"],
            "calendar_event_title": row["calendar_event_title"],
            "next_occurrence": row["next_occurrence"],
            "calendar_name": row["calendar_name"],
            "category": row["category"],
            "disable_auto_complete": bool(row["disable_auto_complete"]),
        }
        for row in cursor
    ]


def list_all_scenes() -> list[dict[str, Any]]:
    """List all scenes across all acts with act information.

    Returns scenes with act_title, act_color, and calendar metadata for Kanban board display.
    """
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT s.scene_id, s.act_id, s.title, s.stage, s.notes, s.link,
               s.calendar_event_id, s.recurrence_rule, s.thunderbird_event_id,
               s.calendar_event_start, s.calendar_event_end, s.calendar_event_title,
               s.next_occurrence, s.calendar_name, s.category, s.disable_auto_complete,
               a.title as act_title, a.color as act_color
        FROM scenes s
        JOIN acts a ON s.act_id = a.act_id
        ORDER BY a.position ASC, s.position ASC
    """)

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
            "calendar_event_start": row["calendar_event_start"],
            "calendar_event_end": row["calendar_event_end"],
            "calendar_event_title": row["calendar_event_title"],
            "next_occurrence": row["next_occurrence"],
            "calendar_name": row["calendar_name"],
            "category": row["category"],
            "disable_auto_complete": bool(row["disable_auto_complete"]),
            "act_title": row["act_title"],
            "act_color": row["act_color"],
        }
        for row in cursor
    ]


def get_scene(scene_id: str) -> dict[str, Any] | None:
    """Get a scene by ID."""
    conn = _get_connection()
    cursor = conn.execute(
        """
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id,
               calendar_event_start, calendar_event_end, calendar_event_title,
               next_occurrence, calendar_name, category, disable_auto_complete
        FROM scenes WHERE scene_id = ?
    """,
        (scene_id,),
    )

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
        "calendar_event_start": row["calendar_event_start"],
        "calendar_event_end": row["calendar_event_end"],
        "calendar_event_title": row["calendar_event_title"],
        "next_occurrence": row["next_occurrence"],
        "calendar_name": row["calendar_name"],
        "category": row["category"],
        "disable_auto_complete": bool(row["disable_auto_complete"]),
    }


def create_scene(
    *,
    act_id: str,
    title: str,
    stage: str = "planning",
    notes: str = "",
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
    disable_auto_complete: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Create a new scene."""
    scene_id = _new_id("scene")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position for this act
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM scenes WHERE act_id = ?", (act_id,)
        )
        position = cursor.fetchone()[0]

        conn.execute(
            """
            INSERT INTO scenes
            (scene_id, act_id, title, stage, notes, link, calendar_event_id, recurrence_rule,
             thunderbird_event_id, disable_auto_complete, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                scene_id,
                act_id,
                title,
                stage,
                notes,
                link,
                calendar_event_id,
                recurrence_rule,
                thunderbird_event_id,
                1 if disable_auto_complete else 0,
                position,
                now,
                now,
            ),
        )

    return list_scenes(act_id), scene_id


def update_scene(
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
    disable_auto_complete: bool | None = None,
) -> list[dict[str, Any]]:
    """Update a scene.

    Note: Recurring scenes cannot be set to 'complete' stage. They represent
    ongoing series, not one-time tasks. If stage='complete' is requested for
    a recurring scene, it will be ignored.
    """
    now = _now_iso()

    with _transaction() as conn:
        # Check if this is a recurring scene when trying to set stage to complete
        if stage == "complete":
            cursor = conn.execute(
                "SELECT recurrence_rule FROM scenes WHERE scene_id = ?", (scene_id,)
            )
            row = cursor.fetchone()
            if row and row["recurrence_rule"]:
                # Recurring scenes cannot be completed - ignore the stage change
                logger.warning(
                    f"Attempted to set recurring scene {scene_id} to 'complete'. "
                    "Recurring scenes cannot be completed. Ignoring stage change."
                )
                stage = None  # Don't update the stage

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
        if disable_auto_complete is not None:
            updates.append("disable_auto_complete = ?")
            params.append(1 if disable_auto_complete else 0)

        params.append(scene_id)

        conn.execute(
            f"""
            UPDATE scenes SET {", ".join(updates)} WHERE scene_id = ?
        """,
            params,
        )

    return list_scenes(act_id)


def delete_scene(act_id: str, scene_id: str) -> list[dict[str, Any]]:
    """Delete a scene."""
    with _transaction() as conn:
        conn.execute("DELETE FROM scenes WHERE scene_id = ?", (scene_id,))

    return list_scenes(act_id)


def update_scene_calendar_data(
    scene_id: str,
    *,
    calendar_event_start: str | None = None,
    calendar_event_end: str | None = None,
    calendar_event_title: str | None = None,
    next_occurrence: str | None = None,
    calendar_name: str | None = None,
    category: str | None = None,
) -> bool:
    """Update calendar metadata for a scene.

    This is the single write target for calendar sync operations.
    Only updates fields that are explicitly passed (not None).

    Args:
        scene_id: The scene to update.
        calendar_event_start: Event start time (ISO format).
        calendar_event_end: Event end time (ISO format).
        calendar_event_title: Cached event title.
        next_occurrence: Next occurrence for recurring events (ISO format).
        calendar_name: Human-readable calendar name.
        category: Classification (event, holiday, birthday).

    Returns:
        True if updated, False if scene not found.
    """
    now = _now_iso()

    with _transaction() as conn:
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if calendar_event_start is not None:
            updates.append("calendar_event_start = ?")
            params.append(calendar_event_start if calendar_event_start else None)
        if calendar_event_end is not None:
            updates.append("calendar_event_end = ?")
            params.append(calendar_event_end if calendar_event_end else None)
        if calendar_event_title is not None:
            updates.append("calendar_event_title = ?")
            params.append(calendar_event_title if calendar_event_title else None)
        if next_occurrence is not None:
            updates.append("next_occurrence = ?")
            params.append(next_occurrence if next_occurrence else None)
        if calendar_name is not None:
            updates.append("calendar_name = ?")
            params.append(calendar_name if calendar_name else None)
        if category is not None:
            updates.append("category = ?")
            params.append(category if category else None)

        params.append(scene_id)

        cursor = conn.execute(
            f"""
            UPDATE scenes SET {", ".join(updates)} WHERE scene_id = ?
        """,
            params,
        )

        return cursor.rowcount > 0


def move_scene(*, scene_id: str, source_act_id: str, target_act_id: str) -> dict[str, Any]:
    """Move a scene to a different act."""
    now = _now_iso()

    with _transaction() as conn:
        # Verify scene exists
        cursor = conn.execute("SELECT scene_id FROM scenes WHERE scene_id = ?", (scene_id,))
        if not cursor.fetchone():
            raise ValueError(f"Scene not found: {scene_id}")

        # Get max position in target act
        cursor = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM scenes WHERE act_id = ?", (target_act_id,)
        )
        position = cursor.fetchone()[0]

        # Move the scene
        conn.execute(
            """
            UPDATE scenes SET act_id = ?, position = ?, updated_at = ?
            WHERE scene_id = ?
        """,
            (target_act_id, position, now, scene_id),
        )

    return {
        "scene_id": scene_id,
        "target_act_id": target_act_id,
    }


def find_scene_location(scene_id: str) -> dict[str, str | None] | None:
    """Find the act containing a scene.

    This is the CANONICAL source for scene location.
    """
    conn = _get_connection()

    cursor = conn.execute(
        """
        SELECT s.scene_id, a.act_id, a.title as act_title
        FROM scenes s
        JOIN acts a ON s.act_id = a.act_id
        WHERE s.scene_id = ?
    """,
        (scene_id,),
    )

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

    cursor = conn.execute(
        """
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes WHERE calendar_event_id = ?
    """,
        (calendar_event_id,),
    )

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

    cursor = conn.execute(
        """
        SELECT scene_id, act_id, title, stage, notes, link, calendar_event_id,
               recurrence_rule, thunderbird_event_id
        FROM scenes WHERE thunderbird_event_id = ?
    """,
        (thunderbird_event_id,),
    )

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


def get_scenes_with_upcoming_events(hours: int = 168) -> list[dict[str, Any]]:
    """Get scenes with calendar events in the next N hours.

    This returns scenes that have calendar_event_start set within the
    specified time window. For recurring events, uses next_occurrence
    if available.

    Args:
        hours: Look ahead this many hours (default 168 = 7 days).

    Returns:
        List of scene dicts with calendar data, sorted by effective time.
    """
    from datetime import datetime, timedelta

    conn = _get_connection()
    now = datetime.now()
    cutoff = (now + timedelta(hours=hours)).isoformat()
    now_iso = now.isoformat()

    # Get scenes where either:
    # 1. next_occurrence is within the window (for recurring events), or
    # 2. calendar_event_start is within the window (for one-time events)
    cursor = conn.execute(
        """
        SELECT
            scene_id, act_id, title, stage, notes, link,
            calendar_event_id, calendar_event_start, calendar_event_end,
            calendar_event_title, recurrence_rule, next_occurrence,
            calendar_name, category
        FROM scenes
        WHERE calendar_event_start IS NOT NULL
          AND (
              (next_occurrence IS NOT NULL AND next_occurrence >= ? AND next_occurrence <= ?)
              OR (next_occurrence IS NULL AND calendar_event_start >= ? AND calendar_event_start <= ?)
          )
        ORDER BY COALESCE(next_occurrence, calendar_event_start) ASC
    """,
        (now_iso, cutoff, now_iso, cutoff),
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "scene_id": row["scene_id"],
                "act_id": row["act_id"],
                "title": row["title"],
                "stage": row["stage"],
                "notes": row["notes"],
                "link": row["link"],
                "calendar_event_id": row["calendar_event_id"],
                "start": row["calendar_event_start"],
                "end": row["calendar_event_end"],
                "calendar_event_title": row["calendar_event_title"],
                "recurrence_rule": row["recurrence_rule"],
                "next_occurrence": row["next_occurrence"],
                "calendar_name": row["calendar_name"],
                "category": row["category"],
            }
        )

    return results


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
        cursor = conn.execute(
            """
            UPDATE scenes SET thunderbird_event_id = ?, updated_at = ?
            WHERE scene_id = ?
        """,
            (thunderbird_event_id, now, scene_id),
        )

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
# Attachments Operations
# =============================================================================


def list_attachments(
    *, act_id: str | None = None, scene_id: str | None = None, beat_id: str | None = None
) -> list[dict[str, Any]]:
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


def add_attachment(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> dict[str, Any]:
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
        conn.execute(
            """
            INSERT INTO attachments
            (attachment_id, act_id, scene_id, file_path, file_name, file_type, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (attachment_id, act_id, scene_id, file_path, file_name, file_type, now),
        )

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
        cursor = conn.execute("DELETE FROM attachments WHERE attachment_id = ?", (attachment_id,))
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
        conn.execute(
            """
            INSERT INTO acts (act_id, title, active, notes, position, created_at, updated_at)
            VALUES (?, 'Your Story', 0, 'The overarching narrative of your life.', 0, ?, ?)
        """,
            (YOUR_STORY_ACT_ID, now, now),
        )

    acts, _ = list_acts()
    return acts, YOUR_STORY_ACT_ID


# =============================================================================
# Page Operations (Nested Knowledgebase Pages)
# =============================================================================


def list_pages(act_id: str, parent_page_id: str | None = None) -> list[dict[str, Any]]:
    """List pages for an act, optionally filtered by parent.

    Args:
        act_id: The act ID to list pages for.
        parent_page_id: If provided, only list children of this page.
                       If None, lists root pages (pages with no parent).
    """
    init_db()
    conn = _get_connection()

    if parent_page_id is None:
        cursor = conn.execute(
            """
            SELECT page_id, act_id, parent_page_id, title, icon, position, created_at, updated_at
            FROM pages WHERE act_id = ? AND parent_page_id IS NULL
            ORDER BY position ASC, created_at ASC
        """,
            (act_id,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT page_id, act_id, parent_page_id, title, icon, position, created_at, updated_at
            FROM pages WHERE act_id = ? AND parent_page_id = ?
            ORDER BY position ASC, created_at ASC
        """,
            (act_id, parent_page_id),
        )

    return [
        {
            "page_id": row["page_id"],
            "act_id": row["act_id"],
            "parent_page_id": row["parent_page_id"],
            "title": row["title"],
            "icon": row["icon"],
            "position": row["position"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in cursor
    ]


def get_page_tree(act_id: str) -> list[dict[str, Any]]:
    """Get the full page tree for an act.

    Returns a nested structure with children arrays.
    """
    init_db()
    conn = _get_connection()

    # Get all pages for this act
    cursor = conn.execute(
        """
        SELECT page_id, act_id, parent_page_id, title, icon, position, created_at, updated_at
        FROM pages WHERE act_id = ?
        ORDER BY position ASC, created_at ASC
    """,
        (act_id,),
    )

    all_pages = [
        {
            "page_id": row["page_id"],
            "act_id": row["act_id"],
            "parent_page_id": row["parent_page_id"],
            "title": row["title"],
            "icon": row["icon"],
            "position": row["position"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "children": [],
        }
        for row in cursor
    ]

    # Build tree structure
    pages_by_id: dict[str, dict[str, Any]] = {p["page_id"]: p for p in all_pages}
    root_pages: list[dict[str, Any]] = []

    for page in all_pages:
        parent_id = page["parent_page_id"]
        if parent_id is None:
            root_pages.append(page)
        elif parent_id in pages_by_id:
            pages_by_id[parent_id]["children"].append(page)

    return root_pages


def get_page(page_id: str) -> dict[str, Any] | None:
    """Get a page by ID."""
    conn = _get_connection()
    cursor = conn.execute(
        """
        SELECT page_id, act_id, parent_page_id, title, icon, position, created_at, updated_at
        FROM pages WHERE page_id = ?
    """,
        (page_id,),
    )

    row = cursor.fetchone()
    if not row:
        return None

    return {
        "page_id": row["page_id"],
        "act_id": row["act_id"],
        "parent_page_id": row["parent_page_id"],
        "title": row["title"],
        "icon": row["icon"],
        "position": row["position"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_page(
    *, act_id: str, title: str, parent_page_id: str | None = None, icon: str | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Create a new page."""
    page_id = _new_id("page")
    now = _now_iso()

    with _transaction() as conn:
        # Get max position for this parent
        if parent_page_id is None:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM pages WHERE act_id = ? AND parent_page_id IS NULL",
                (act_id,),
            )
        else:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM pages WHERE act_id = ? AND parent_page_id = ?",
                (act_id, parent_page_id),
            )
        position = cursor.fetchone()[0]

        conn.execute(
            """
            INSERT INTO pages
            (page_id, act_id, parent_page_id, title, icon, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (page_id, act_id, parent_page_id, title, icon, position, now, now),
        )

    return list_pages(act_id, parent_page_id), page_id


def update_page(
    *, page_id: str, title: str | None = None, icon: str | None = None
) -> dict[str, Any] | None:
    """Update a page's metadata."""
    now = _now_iso()

    with _transaction() as conn:
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if icon is not None:
            updates.append("icon = ?")
            params.append(icon if icon else None)

        params.append(page_id)

        conn.execute(
            f"""
            UPDATE pages SET {", ".join(updates)} WHERE page_id = ?
        """,
            params,
        )

    return get_page(page_id)


def delete_page(page_id: str) -> bool:
    """Delete a page and all its descendants.

    Due to CASCADE, child pages are automatically deleted.
    """
    with _transaction() as conn:
        cursor = conn.execute("DELETE FROM pages WHERE page_id = ?", (page_id,))
        return cursor.rowcount > 0


def move_page(
    *, page_id: str, new_parent_id: str | None = None, new_position: int | None = None
) -> dict[str, Any] | None:
    """Move a page to a new parent or position.

    Args:
        page_id: The page to move.
        new_parent_id: New parent page ID, or None for root level.
        new_position: New position within the parent, or None to append at end.
    """
    now = _now_iso()

    page = get_page(page_id)
    if not page:
        return None

    act_id = page["act_id"]

    with _transaction() as conn:
        if new_position is None:
            # Get max position for the new parent
            if new_parent_id is None:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM pages WHERE act_id = ? AND parent_page_id IS NULL",
                    (act_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM pages WHERE act_id = ? AND parent_page_id = ?",
                    (act_id, new_parent_id),
                )
            new_position = cursor.fetchone()[0]

        conn.execute(
            """
            UPDATE pages SET parent_page_id = ?, position = ?, updated_at = ?
            WHERE page_id = ?
        """,
            (new_parent_id, new_position, now, page_id),
        )

    return get_page(page_id)


def read_page_content(act_id: str, page_id: str) -> str:
    """Read page content from the filesystem.

    Page content is stored at kb/acts/{act_id}/pages/{page_id}.md
    """
    from .play_fs import play_root

    content_path = play_root() / "kb" / "acts" / act_id / "pages" / f"{page_id}.md"

    if content_path.exists():
        return content_path.read_text(encoding="utf-8", errors="replace")

    # Return empty string if file doesn't exist
    return ""


def write_page_content(act_id: str, page_id: str, text: str) -> None:
    """Write page content to the filesystem.

    Page content is stored at kb/acts/{act_id}/pages/{page_id}.md
    """
    from .play_fs import play_root

    pages_dir = play_root() / "kb" / "acts" / act_id / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    content_path = pages_dir / f"{page_id}.md"
    content_path.write_text(text, encoding="utf-8")


# =============================================================================
# Act Block Integration (v8)
# =============================================================================


def set_act_root_block(act_id: str, root_block_id: str | None) -> bool:
    """Set the root block ID for an act.

    Args:
        act_id: The act ID.
        root_block_id: The block ID to set as root, or None to clear.

    Returns:
        True if updated, False if act not found.
    """
    now = _now_iso()

    with _transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE acts SET root_block_id = ?, updated_at = ?
            WHERE act_id = ?
        """,
            (root_block_id, now, act_id),
        )

        return cursor.rowcount > 0


def get_act_root_block(act_id: str) -> dict[str, Any] | None:
    """Get the root block for an act.

    Returns the block data if the act has a root block, None otherwise.
    This imports from blocks_db to avoid circular imports.
    """
    act = get_act(act_id)
    if not act or not act.get("root_block_id"):
        return None

    # Import here to avoid circular imports
    from .play.blocks_db import get_block

    block = get_block(act["root_block_id"])
    if block:
        return block.to_dict()
    return None


def create_act_with_root_block(
    *,
    title: str,
    notes: str = "",
    color: str | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Create a new act with an auto-created root page block.

    This is the recommended way to create acts for the block-based system.
    The root block serves as the main content container for the act.

    Args:
        title: Act title.
        notes: Act notes.
        color: Act color.

    Returns:
        Tuple of (acts list, act_id, root_block_id).
    """
    # Import here to avoid circular imports
    from .play.blocks_db import create_block

    # Create the act first
    acts, act_id = create_act(title=title, notes=notes, color=color)

    # Create a root "page" block for the act
    root_block = create_block(
        type="page",
        act_id=act_id,
        properties={"title": title},
    )

    # Link the root block to the act
    set_act_root_block(act_id, root_block.id)

    # Refresh acts list
    acts, _ = list_acts()

    return acts, act_id, root_block.id


def get_unchecked_todos(act_id: str) -> list[dict[str, Any]]:
    """Get all unchecked to-do blocks in an act.

    Searches for blocks of type 'to_do' that have checked=false.

    Args:
        act_id: The act ID.

    Returns:
        List of unchecked to-do block data with their text content.
    """
    init_db()
    conn = _get_connection()

    # Find all to_do blocks in this act that are not checked
    cursor = conn.execute(
        """
        SELECT b.id, b.page_id, b.parent_id, b.position, b.created_at, b.updated_at
        FROM blocks b
        LEFT JOIN block_properties bp ON b.id = bp.block_id AND bp.key = 'checked'
        WHERE b.act_id = ?
          AND b.type = 'to_do'
          AND (bp.value IS NULL OR bp.value = 'false' OR bp.value = '0')
        ORDER BY b.created_at
    """,
        (act_id,),
    )

    todos = []
    for row in cursor:
        block_id = row["id"]

        # Get the text content from rich_text
        rt_cursor = conn.execute(
            """
            SELECT content FROM rich_text WHERE block_id = ? ORDER BY position
        """,
            (block_id,),
        )
        text = " ".join(rt_row["content"] for rt_row in rt_cursor)

        todos.append(
            {
                "block_id": block_id,
                "page_id": row["page_id"],
                "parent_id": row["parent_id"],
                "text": text,
                "created_at": row["created_at"],
            }
        )

    return todos


def cleanup_recurring_scenes_stage() -> int:
    """Clean up recurring scenes that are incorrectly set to 'complete'.

    Recurring scenes represent ongoing series and cannot be completed.
    This function resets any such scenes to 'in_progress'.

    Returns:
        Number of scenes that were cleaned up.
    """
    init_db()

    with _transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE scenes
            SET stage = 'in_progress', updated_at = ?
            WHERE recurrence_rule IS NOT NULL
              AND recurrence_rule != ''
              AND stage = 'complete'
        """,
            (_now_iso(),),
        )
        cleaned = cursor.rowcount

    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} recurring scenes from 'complete' to 'in_progress'")

    return cleaned


def search_blocks_in_act(act_id: str, query: str) -> list[dict[str, Any]]:
    """Search for blocks containing text in an act.

    Performs a simple LIKE search on rich_text content.

    Args:
        act_id: The act ID.
        query: Text to search for.

    Returns:
        List of matching blocks with their text content.
    """
    init_db()
    conn = _get_connection()

    # Search in rich_text content
    cursor = conn.execute(
        """
        SELECT DISTINCT b.id, b.type, b.page_id, b.parent_id, b.position, b.created_at
        FROM blocks b
        JOIN rich_text rt ON b.id = rt.block_id
        WHERE b.act_id = ?
          AND rt.content LIKE ?
        ORDER BY b.created_at
    """,
        (act_id, f"%{query}%"),
    )

    results = []
    for row in cursor:
        block_id = row["id"]

        # Get full text content
        rt_cursor = conn.execute(
            """
            SELECT content FROM rich_text WHERE block_id = ? ORDER BY position
        """,
            (block_id,),
        )
        text = " ".join(rt_row["content"] for rt_row in rt_cursor)

        results.append(
            {
                "block_id": block_id,
                "type": row["type"],
                "page_id": row["page_id"],
                "parent_id": row["parent_id"],
                "text": text,
                "created_at": row["created_at"],
            }
        )

    return results
