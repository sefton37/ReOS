"""Tests for play_db.py - SQLite storage for The Play.

Tests the database layer for Acts, Scenes, and Pages:
- Schema initialization and migrations (v6)
- Acts CRUD operations
- Scenes CRUD with calendar metadata
- update_scene_calendar_data function
- Calendar sync lookup functions
- Pages nested structure
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create isolated data directory for play_db."""
    data_dir = tmp_path / "reos-data"
    data_dir.mkdir()
    monkeypatch.setenv("REOS_DATA_DIR", str(data_dir))

    # Close any existing connection before test
    import reos.play_db as play_db

    play_db.close_connection()

    yield data_dir

    # Cleanup after test
    play_db.close_connection()


@pytest.fixture
def initialized_db(temp_data_dir: Path):
    """Initialize the database and return the module."""
    import reos.play_db as play_db

    play_db.init_db()
    return play_db


# =============================================================================
# Schema and Migration Tests
# =============================================================================


class TestSchemaInitialization:
    """Test schema creation and versioning."""

    def test_init_db_creates_schema(self, temp_data_dir: Path) -> None:
        """init_db creates all required tables."""
        import reos.play_db as play_db

        play_db.init_db()
        conn = play_db._get_connection()

        # Check tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor}

        assert "acts" in tables
        assert "scenes" in tables
        assert "attachments" in tables
        assert "pages" in tables
        assert "schema_version" in tables

    def test_init_db_sets_schema_version(self, temp_data_dir: Path) -> None:
        """init_db sets schema version to current."""
        import reos.play_db as play_db

        play_db.init_db()
        conn = play_db._get_connection()

        cursor = conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]

        assert version == play_db.SCHEMA_VERSION

    def test_init_db_idempotent(self, temp_data_dir: Path) -> None:
        """Calling init_db multiple times is safe."""
        import reos.play_db as play_db

        play_db.init_db()
        play_db.init_db()
        play_db.init_db()

        # Should not raise
        acts, _ = play_db.list_acts()
        assert isinstance(acts, list)


class TestSchemaMigrationV6:
    """Test v6 migration adds calendar metadata columns."""

    def test_scenes_has_calendar_columns(self, initialized_db) -> None:
        """scenes table has v6 calendar metadata columns."""
        conn = initialized_db._get_connection()

        cursor = conn.execute("PRAGMA table_info(scenes)")
        columns = {row[1] for row in cursor}

        # v6 columns
        assert "calendar_event_start" in columns
        assert "calendar_event_end" in columns
        assert "calendar_event_title" in columns
        assert "next_occurrence" in columns
        assert "calendar_name" in columns
        assert "category" in columns

    def test_next_occurrence_index_exists(self, initialized_db) -> None:
        """Index on next_occurrence exists for efficient queries."""
        conn = initialized_db._get_connection()

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%next_occurrence%'"
        )
        indexes = [row[0] for row in cursor]

        assert any("next_occurrence" in idx for idx in indexes)


# =============================================================================
# Acts CRUD Tests
# =============================================================================


class TestActsCRUD:
    """Test Acts create, read, update, delete operations."""

    def test_create_act(self, initialized_db) -> None:
        """create_act creates a new act."""
        acts, act_id = initialized_db.create_act(title="Test Act", notes="Test notes")

        assert act_id.startswith("act-")
        assert len(acts) == 1
        assert acts[0]["title"] == "Test Act"
        assert acts[0]["notes"] == "Test notes"
        assert acts[0]["active"] is False

    def test_create_act_with_color(self, initialized_db) -> None:
        """create_act supports color parameter."""
        acts, act_id = initialized_db.create_act(
            title="Colored Act", color="#ff5500"
        )

        assert acts[0]["color"] == "#ff5500"

    def test_get_act(self, initialized_db) -> None:
        """get_act returns single act by ID."""
        _, act_id = initialized_db.create_act(title="Test Act")

        act = initialized_db.get_act(act_id)

        assert act is not None
        assert act["act_id"] == act_id
        assert act["title"] == "Test Act"

    def test_get_act_nonexistent(self, initialized_db) -> None:
        """get_act returns None for nonexistent ID."""
        act = initialized_db.get_act("nonexistent-id")
        assert act is None

    def test_update_act(self, initialized_db) -> None:
        """update_act modifies act fields."""
        _, act_id = initialized_db.create_act(title="Original Title")

        acts, _ = initialized_db.update_act(
            act_id=act_id, title="Updated Title", notes="New notes"
        )

        updated = next(a for a in acts if a["act_id"] == act_id)
        assert updated["title"] == "Updated Title"
        assert updated["notes"] == "New notes"

    def test_set_active_act(self, initialized_db) -> None:
        """set_active_act activates specified act."""
        _, act1_id = initialized_db.create_act(title="Act 1")
        _, act2_id = initialized_db.create_act(title="Act 2")

        acts, active_id = initialized_db.set_active_act(act1_id)

        assert active_id == act1_id
        act1 = next(a for a in acts if a["act_id"] == act1_id)
        act2 = next(a for a in acts if a["act_id"] == act2_id)
        assert act1["active"] is True
        assert act2["active"] is False

    def test_set_active_act_deactivates_others(self, initialized_db) -> None:
        """set_active_act deactivates previously active act."""
        _, act1_id = initialized_db.create_act(title="Act 1")
        _, act2_id = initialized_db.create_act(title="Act 2")

        initialized_db.set_active_act(act1_id)
        acts, active_id = initialized_db.set_active_act(act2_id)

        assert active_id == act2_id
        act1 = next(a for a in acts if a["act_id"] == act1_id)
        assert act1["active"] is False

    def test_delete_act(self, initialized_db) -> None:
        """delete_act removes act."""
        _, act_id = initialized_db.create_act(title="To Delete")

        acts, _ = initialized_db.delete_act(act_id)

        assert not any(a["act_id"] == act_id for a in acts)

    def test_delete_act_cascades_to_scenes(self, initialized_db) -> None:
        """Deleting act also deletes its scenes (CASCADE)."""
        _, act_id = initialized_db.create_act(title="Act with Scenes")
        initialized_db.create_scene(act_id=act_id, title="Scene 1")
        initialized_db.create_scene(act_id=act_id, title="Scene 2")

        initialized_db.delete_act(act_id)

        # Scenes should be gone
        scenes = initialized_db.list_scenes(act_id)
        assert len(scenes) == 0


# =============================================================================
# Scenes CRUD Tests
# =============================================================================


class TestScenesCRUD:
    """Test Scenes create, read, update, delete operations."""

    def test_create_scene(self, initialized_db) -> None:
        """create_scene creates a new scene."""
        _, act_id = initialized_db.create_act(title="Test Act")

        scenes, scene_id = initialized_db.create_scene(
            act_id=act_id, title="Test Scene"
        )

        assert scene_id.startswith("scene-")
        assert len(scenes) == 1
        assert scenes[0]["title"] == "Test Scene"
        assert scenes[0]["stage"] == "planning"

    def test_create_scene_with_all_fields(self, initialized_db) -> None:
        """create_scene accepts all optional fields."""
        _, act_id = initialized_db.create_act(title="Test Act")

        scenes, scene_id = initialized_db.create_scene(
            act_id=act_id,
            title="Full Scene",
            stage="in_progress",
            notes="Some notes",
            link="https://example.com",
            calendar_event_id="cal-123",
            recurrence_rule="RRULE:FREQ=WEEKLY",
            thunderbird_event_id="tb-456",
        )

        scene = scenes[0]
        assert scene["stage"] == "in_progress"
        assert scene["notes"] == "Some notes"
        assert scene["link"] == "https://example.com"
        assert scene["calendar_event_id"] == "cal-123"
        assert scene["recurrence_rule"] == "RRULE:FREQ=WEEKLY"
        assert scene["thunderbird_event_id"] == "tb-456"

    def test_get_scene(self, initialized_db) -> None:
        """get_scene returns single scene by ID."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        scene = initialized_db.get_scene(scene_id)

        assert scene is not None
        assert scene["scene_id"] == scene_id
        assert scene["title"] == "Test Scene"

    def test_get_scene_includes_calendar_metadata(self, initialized_db) -> None:
        """get_scene returns all calendar metadata fields."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        scene = initialized_db.get_scene(scene_id)

        # v6 calendar metadata fields should be present (even if None)
        assert "calendar_event_start" in scene
        assert "calendar_event_end" in scene
        assert "calendar_event_title" in scene
        assert "next_occurrence" in scene
        assert "calendar_name" in scene
        assert "category" in scene

    def test_list_scenes(self, initialized_db) -> None:
        """list_scenes returns all scenes for an act."""
        _, act_id = initialized_db.create_act(title="Test Act")
        initialized_db.create_scene(act_id=act_id, title="Scene 1")
        initialized_db.create_scene(act_id=act_id, title="Scene 2")
        initialized_db.create_scene(act_id=act_id, title="Scene 3")

        scenes = initialized_db.list_scenes(act_id)

        assert len(scenes) == 3
        titles = {s["title"] for s in scenes}
        assert titles == {"Scene 1", "Scene 2", "Scene 3"}

    def test_list_all_scenes(self, initialized_db) -> None:
        """list_all_scenes returns scenes across all acts with act info."""
        _, act1_id = initialized_db.create_act(title="Act 1", color="#ff0000")
        _, act2_id = initialized_db.create_act(title="Act 2", color="#00ff00")
        initialized_db.create_scene(act_id=act1_id, title="Scene A")
        initialized_db.create_scene(act_id=act2_id, title="Scene B")

        all_scenes = initialized_db.list_all_scenes()

        assert len(all_scenes) == 2
        # Should include act_title and act_color
        scene_a = next(s for s in all_scenes if s["title"] == "Scene A")
        assert scene_a["act_title"] == "Act 1"
        assert scene_a["act_color"] == "#ff0000"

    def test_update_scene(self, initialized_db) -> None:
        """update_scene modifies scene fields."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Original")

        initialized_db.update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title="Updated",
            stage="complete",
            notes="New notes",
        )

        scene = initialized_db.get_scene(scene_id)
        assert scene["title"] == "Updated"
        assert scene["stage"] == "complete"
        assert scene["notes"] == "New notes"

    def test_delete_scene(self, initialized_db) -> None:
        """delete_scene removes scene."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="To Delete")

        scenes = initialized_db.delete_scene(act_id, scene_id)

        assert not any(s["scene_id"] == scene_id for s in scenes)


# =============================================================================
# update_scene_calendar_data Tests
# =============================================================================


class TestUpdateSceneCalendarData:
    """Test update_scene_calendar_data function - single write target for calendar sync."""

    def test_update_creates_calendar_record(self, initialized_db) -> None:
        """update_scene_calendar_data sets calendar fields on scene."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        result = initialized_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start="2026-01-15T10:00:00Z",
            calendar_event_end="2026-01-15T11:00:00Z",
            calendar_event_title="Meeting",
        )

        assert result is True

        scene = initialized_db.get_scene(scene_id)
        assert scene["calendar_event_start"] == "2026-01-15T10:00:00Z"
        assert scene["calendar_event_end"] == "2026-01-15T11:00:00Z"
        assert scene["calendar_event_title"] == "Meeting"

    def test_update_modifies_existing_data(self, initialized_db) -> None:
        """update_scene_calendar_data can modify existing calendar data."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        # Set initial data
        initialized_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start="2026-01-15T10:00:00Z",
            calendar_name="Personal",
        )

        # Update
        initialized_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start="2026-01-16T10:00:00Z",
            calendar_name="Work",
        )

        scene = initialized_db.get_scene(scene_id)
        assert scene["calendar_event_start"] == "2026-01-16T10:00:00Z"
        assert scene["calendar_name"] == "Work"

    def test_update_with_empty_string_clears_field(self, initialized_db) -> None:
        """Empty string clears the field (sets to NULL)."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        # Set initial data
        initialized_db.update_scene_calendar_data(
            scene_id, calendar_name="Personal"
        )

        # Clear with empty string
        initialized_db.update_scene_calendar_data(
            scene_id, calendar_name=""
        )

        scene = initialized_db.get_scene(scene_id)
        assert scene["calendar_name"] is None

    def test_update_nonexistent_scene_returns_false(self, initialized_db) -> None:
        """update_scene_calendar_data returns False for nonexistent scene."""
        result = initialized_db.update_scene_calendar_data(
            "nonexistent-id",
            calendar_event_start="2026-01-15T10:00:00Z",
        )

        assert result is False

    def test_update_next_occurrence_for_recurring(self, initialized_db) -> None:
        """next_occurrence can be set for recurring events."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(
            act_id=act_id,
            title="Recurring Scene",
            recurrence_rule="RRULE:FREQ=WEEKLY",
        )

        initialized_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start="2026-01-01T10:00:00Z",
            next_occurrence="2026-01-22T10:00:00Z",
        )

        scene = initialized_db.get_scene(scene_id)
        assert scene["next_occurrence"] == "2026-01-22T10:00:00Z"

    def test_update_category_field(self, initialized_db) -> None:
        """category field can be set (event, holiday, birthday)."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Birthday")

        initialized_db.update_scene_calendar_data(
            scene_id, category="birthday"
        )

        scene = initialized_db.get_scene(scene_id)
        assert scene["category"] == "birthday"

    def test_partial_update_preserves_other_fields(self, initialized_db) -> None:
        """Partial update doesn't affect fields not specified."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        # Set multiple fields
        initialized_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start="2026-01-15T10:00:00Z",
            calendar_name="Personal",
            category="event",
        )

        # Update only one field
        initialized_db.update_scene_calendar_data(
            scene_id, calendar_name="Work"
        )

        scene = initialized_db.get_scene(scene_id)
        # calendar_event_start and category should be preserved
        assert scene["calendar_event_start"] == "2026-01-15T10:00:00Z"
        assert scene["category"] == "event"
        # calendar_name should be updated
        assert scene["calendar_name"] == "Work"


# =============================================================================
# Calendar Sync Lookup Tests
# =============================================================================


class TestCalendarSyncLookups:
    """Test functions for finding scenes by calendar/thunderbird IDs."""

    def test_find_scene_by_calendar_event(self, initialized_db) -> None:
        """find_scene_by_calendar_event returns scene with matching ID."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(
            act_id=act_id,
            title="Calendar Scene",
            calendar_event_id="cal-event-123",
        )

        found = initialized_db.find_scene_by_calendar_event("cal-event-123")

        assert found is not None
        assert found["scene_id"] == scene_id
        assert found["calendar_event_id"] == "cal-event-123"

    def test_find_scene_by_calendar_event_not_found(self, initialized_db) -> None:
        """find_scene_by_calendar_event returns None if not found."""
        found = initialized_db.find_scene_by_calendar_event("nonexistent")
        assert found is None

    def test_find_scene_by_thunderbird_event(self, initialized_db) -> None:
        """find_scene_by_thunderbird_event returns scene with matching ID."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(
            act_id=act_id,
            title="Thunderbird Scene",
            thunderbird_event_id="tb-event-456",
        )

        found = initialized_db.find_scene_by_thunderbird_event("tb-event-456")

        assert found is not None
        assert found["scene_id"] == scene_id
        assert found["thunderbird_event_id"] == "tb-event-456"

    def test_set_scene_thunderbird_event_id(self, initialized_db) -> None:
        """set_scene_thunderbird_event_id updates thunderbird ID."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        result = initialized_db.set_scene_thunderbird_event_id(scene_id, "tb-789")

        assert result is True
        scene = initialized_db.get_scene(scene_id)
        assert scene["thunderbird_event_id"] == "tb-789"

    def test_clear_scene_thunderbird_event_id(self, initialized_db) -> None:
        """clear_scene_thunderbird_event_id removes thunderbird ID."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(
            act_id=act_id,
            title="Test Scene",
            thunderbird_event_id="tb-to-clear",
        )

        result = initialized_db.clear_scene_thunderbird_event_id(scene_id)

        assert result is True
        scene = initialized_db.get_scene(scene_id)
        assert scene["thunderbird_event_id"] is None

    def test_find_scene_location(self, initialized_db) -> None:
        """find_scene_location returns act info for scene."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        location = initialized_db.find_scene_location(scene_id)

        assert location is not None
        assert location["act_id"] == act_id
        assert location["act_title"] == "Test Act"
        assert location["scene_id"] == scene_id


# =============================================================================
# Scene Movement Tests
# =============================================================================


class TestSceneMovement:
    """Test moving scenes between acts."""

    def test_move_scene(self, initialized_db) -> None:
        """move_scene moves scene to different act."""
        _, act1_id = initialized_db.create_act(title="Act 1")
        _, act2_id = initialized_db.create_act(title="Act 2")
        _, scene_id = initialized_db.create_scene(act_id=act1_id, title="Mobile Scene")

        result = initialized_db.move_scene(
            scene_id=scene_id,
            source_act_id=act1_id,
            target_act_id=act2_id,
        )

        assert result["scene_id"] == scene_id
        assert result["target_act_id"] == act2_id

        # Verify scene is in new act
        scene = initialized_db.get_scene(scene_id)
        assert scene["act_id"] == act2_id

        # Verify scene is NOT in old act
        act1_scenes = initialized_db.list_scenes(act1_id)
        assert not any(s["scene_id"] == scene_id for s in act1_scenes)

    def test_move_nonexistent_scene_raises(self, initialized_db) -> None:
        """move_scene raises for nonexistent scene."""
        _, act1_id = initialized_db.create_act(title="Act 1")
        _, act2_id = initialized_db.create_act(title="Act 2")

        with pytest.raises(ValueError, match="Scene not found"):
            initialized_db.move_scene(
                scene_id="nonexistent",
                source_act_id=act1_id,
                target_act_id=act2_id,
            )


# =============================================================================
# Pages CRUD Tests
# =============================================================================


class TestPagesCRUD:
    """Test Pages create, read, update, delete operations."""

    def test_create_page(self, initialized_db) -> None:
        """create_page creates a new page."""
        _, act_id = initialized_db.create_act(title="Test Act")

        pages, page_id = initialized_db.create_page(act_id=act_id, title="Test Page")

        assert page_id.startswith("page-")
        assert len(pages) == 1
        assert pages[0]["title"] == "Test Page"
        assert pages[0]["parent_page_id"] is None

    def test_create_nested_page(self, initialized_db) -> None:
        """create_page with parent_page_id creates nested page."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, parent_id = initialized_db.create_page(act_id=act_id, title="Parent")

        pages, child_id = initialized_db.create_page(
            act_id=act_id, title="Child", parent_page_id=parent_id
        )

        assert len(pages) == 1
        assert pages[0]["parent_page_id"] == parent_id

    def test_list_pages_root_only(self, initialized_db) -> None:
        """list_pages with no parent returns only root pages."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, root1_id = initialized_db.create_page(act_id=act_id, title="Root 1")
        _, root2_id = initialized_db.create_page(act_id=act_id, title="Root 2")
        initialized_db.create_page(act_id=act_id, title="Child", parent_page_id=root1_id)

        root_pages = initialized_db.list_pages(act_id, parent_page_id=None)

        assert len(root_pages) == 2
        titles = {p["title"] for p in root_pages}
        assert titles == {"Root 1", "Root 2"}

    def test_list_pages_children(self, initialized_db) -> None:
        """list_pages with parent_page_id returns only children."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, parent_id = initialized_db.create_page(act_id=act_id, title="Parent")
        initialized_db.create_page(act_id=act_id, title="Child 1", parent_page_id=parent_id)
        initialized_db.create_page(act_id=act_id, title="Child 2", parent_page_id=parent_id)
        initialized_db.create_page(act_id=act_id, title="Root Sibling")

        children = initialized_db.list_pages(act_id, parent_page_id=parent_id)

        assert len(children) == 2
        titles = {p["title"] for p in children}
        assert titles == {"Child 1", "Child 2"}

    def test_get_page_tree(self, initialized_db) -> None:
        """get_page_tree returns nested structure."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, root_id = initialized_db.create_page(act_id=act_id, title="Root")
        initialized_db.create_page(act_id=act_id, title="Child 1", parent_page_id=root_id)
        initialized_db.create_page(act_id=act_id, title="Child 2", parent_page_id=root_id)

        tree = initialized_db.get_page_tree(act_id)

        assert len(tree) == 1
        root = tree[0]
        assert root["title"] == "Root"
        assert len(root["children"]) == 2

    def test_update_page(self, initialized_db) -> None:
        """update_page modifies page fields."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, page_id = initialized_db.create_page(act_id=act_id, title="Original")

        updated = initialized_db.update_page(page_id=page_id, title="Updated", icon="star")

        assert updated is not None
        assert updated["title"] == "Updated"
        assert updated["icon"] == "star"

    def test_delete_page(self, initialized_db) -> None:
        """delete_page removes page."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, page_id = initialized_db.create_page(act_id=act_id, title="To Delete")

        result = initialized_db.delete_page(page_id)

        assert result is True
        page = initialized_db.get_page(page_id)
        assert page is None

    def test_delete_page_cascades_to_children(self, initialized_db) -> None:
        """Deleting parent page cascades to children."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, parent_id = initialized_db.create_page(act_id=act_id, title="Parent")
        _, child_id = initialized_db.create_page(
            act_id=act_id, title="Child", parent_page_id=parent_id
        )

        initialized_db.delete_page(parent_id)

        # Child should also be deleted
        child = initialized_db.get_page(child_id)
        assert child is None

    def test_move_page(self, initialized_db) -> None:
        """move_page changes page's parent."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, parent1_id = initialized_db.create_page(act_id=act_id, title="Parent 1")
        _, parent2_id = initialized_db.create_page(act_id=act_id, title="Parent 2")
        _, child_id = initialized_db.create_page(
            act_id=act_id, title="Child", parent_page_id=parent1_id
        )

        moved = initialized_db.move_page(page_id=child_id, new_parent_id=parent2_id)

        assert moved is not None
        assert moved["parent_page_id"] == parent2_id




# =============================================================================
# Attachments Tests
# =============================================================================


class TestAttachments:
    """Test attachment operations."""

    def test_add_attachment(self, initialized_db) -> None:
        """add_attachment creates attachment record."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")

        att = initialized_db.add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            file_path="/path/to/file.pdf",
        )

        assert att["attachment_id"].startswith("att-")
        assert att["file_name"] == "file.pdf"
        assert att["file_type"] == "pdf"

    def test_list_attachments(self, initialized_db) -> None:
        """list_attachments returns attachments for scope."""
        _, act_id = initialized_db.create_act(title="Test Act")
        _, scene_id = initialized_db.create_scene(act_id=act_id, title="Test Scene")
        initialized_db.add_attachment(act_id=act_id, scene_id=scene_id, file_path="/a.pdf")
        initialized_db.add_attachment(act_id=act_id, scene_id=scene_id, file_path="/b.txt")

        attachments = initialized_db.list_attachments(scene_id=scene_id)

        assert len(attachments) == 2

    def test_remove_attachment(self, initialized_db) -> None:
        """remove_attachment deletes attachment."""
        _, act_id = initialized_db.create_act(title="Test Act")
        att = initialized_db.add_attachment(act_id=act_id, file_path="/file.pdf")

        result = initialized_db.remove_attachment(att["attachment_id"])

        assert result is True
        attachments = initialized_db.list_attachments(act_id=act_id)
        assert len(attachments) == 0


# =============================================================================
# Code Mode Tests
# =============================================================================


class TestCodeMode:
    """Test Code Mode (repo assignment) operations."""

    def test_assign_repo_to_act(self, initialized_db) -> None:
        """assign_repo_to_act sets repo_path on act."""
        _, act_id = initialized_db.create_act(title="Code Project")

        initialized_db.assign_repo_to_act(
            act_id=act_id,
            repo_path="/home/user/project",
            artifact_type="python",
        )

        act = initialized_db.get_act(act_id)
        assert act["repo_path"] == "/home/user/project"
        assert act["artifact_type"] == "python"

    def test_configure_code_mode(self, initialized_db) -> None:
        """configure_code_mode sets code_config."""
        _, act_id = initialized_db.create_act(title="Code Project")
        initialized_db.assign_repo_to_act(act_id=act_id, repo_path="/home/user/project")

        initialized_db.configure_code_mode(
            act_id=act_id,
            code_config={"test_command": "pytest", "build_command": "make"},
        )

        act = initialized_db.get_act(act_id)
        assert act["code_config"]["test_command"] == "pytest"

    def test_configure_code_mode_requires_repo(self, initialized_db) -> None:
        """configure_code_mode raises if no repo_path."""
        _, act_id = initialized_db.create_act(title="No Repo Act")

        with pytest.raises(ValueError, match="no repo_path"):
            initialized_db.configure_code_mode(
                act_id=act_id, code_config={"test_command": "pytest"}
            )
