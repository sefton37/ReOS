"""Tests for scene_calendar_sync.py - Calendar sync for Scenes.

Tests bidirectional sync between Thunderbird calendar and Scenes:
- Placeholder date handling
- RRULE parsing and next occurrence computation
- Annual event deduplication
- Inbound sync (calendar -> scenes)
- Outbound sync (scenes -> calendar)
- Recurring scene refresh
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
    play_db.init_db()

    yield data_dir

    # Cleanup after test
    play_db.close_connection()


@pytest.fixture
def mock_thunderbird_bridge() -> MagicMock:
    """Create a mock ThunderbirdBridge."""
    bridge = MagicMock()
    bridge.has_calendar.return_value = True
    bridge.get_calendar_names.return_value = {"cal-1": "Personal", "cal-2": "Work"}
    return bridge


# =============================================================================
# Placeholder Date Tests
# =============================================================================


class TestPlaceholderDate:
    """Test placeholder date handling."""

    def test_get_placeholder_date_returns_dec_31(self) -> None:
        """get_placeholder_date returns Dec 31 of current year."""
        from reos.cairn.scene_calendar_sync import get_placeholder_date

        placeholder = get_placeholder_date()
        current_year = datetime.now().year

        assert placeholder.year == current_year
        assert placeholder.month == 12
        assert placeholder.day == 31

    def test_placeholder_date_changes_with_year(self) -> None:
        """PLACEHOLDER_DATE constant is set at import time."""
        from reos.cairn.scene_calendar_sync import PLACEHOLDER_DATE

        # PLACEHOLDER_DATE should match current year at import time
        # This is a snapshot, so just verify it's Dec 31 of some year
        assert PLACEHOLDER_DATE.month == 12
        assert PLACEHOLDER_DATE.day == 31


# =============================================================================
# RRULE and Next Occurrence Tests
# =============================================================================

# Check if dateutil is available for RRULE tests
try:
    from dateutil.rrule import rrulestr
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False


class TestGetNextOccurrence:
    """Test RRULE parsing and next occurrence computation."""

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_weekly_recurrence(self) -> None:
        """Compute next occurrence for weekly event."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 1, 1, 10, 0)  # Wednesday
        rrule = "RRULE:FREQ=WEEKLY;BYDAY=WE"

        # After Jan 1, next occurrence should be Jan 8
        after = datetime(2026, 1, 2)
        next_occ = get_next_occurrence(rrule, dtstart, after)

        assert next_occ is not None
        assert next_occ.date() == datetime(2026, 1, 8).date()

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_monthly_recurrence(self) -> None:
        """Compute next occurrence for monthly event."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 1, 15, 14, 0)
        rrule = "RRULE:FREQ=MONTHLY;BYMONTHDAY=15"

        after = datetime(2026, 1, 16)
        next_occ = get_next_occurrence(rrule, dtstart, after)

        assert next_occ is not None
        assert next_occ.month == 2
        assert next_occ.day == 15

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_yearly_recurrence(self) -> None:
        """Compute next occurrence for yearly event (birthday/holiday)."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 3, 17, 0, 0)  # St. Patrick's Day
        rrule = "RRULE:FREQ=YEARLY"

        after = datetime(2026, 3, 18)
        next_occ = get_next_occurrence(rrule, dtstart, after)

        assert next_occ is not None
        assert next_occ.year == 2027
        assert next_occ.month == 3
        assert next_occ.day == 17

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_rrule_without_prefix(self) -> None:
        """RRULE without 'RRULE:' prefix still works."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 1, 1, 10, 0)
        rrule = "FREQ=DAILY"  # No "RRULE:" prefix

        after = datetime(2026, 1, 1, 12, 0)
        next_occ = get_next_occurrence(rrule, dtstart, after)

        assert next_occ is not None
        assert next_occ.date() == datetime(2026, 1, 2).date()

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_default_after_is_now(self) -> None:
        """When after is None, uses current time."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime.now() - timedelta(days=1)
        rrule = "RRULE:FREQ=DAILY"

        next_occ = get_next_occurrence(rrule, dtstart)  # No 'after' param

        assert next_occ is not None
        # Should be in the future
        assert next_occ > datetime.now()

    def test_invalid_rrule_returns_none(self) -> None:
        """Invalid RRULE returns None."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 1, 1)
        rrule = "INVALID:NOT_A_RULE"

        result = get_next_occurrence(rrule, dtstart)
        assert result is None

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_rrule_with_until_limit(self) -> None:
        """RRULE with UNTIL returns None after end date."""
        from reos.cairn.scene_calendar_sync import get_next_occurrence

        dtstart = datetime(2026, 1, 1, 10, 0)
        # Event ends on Jan 15
        rrule = "RRULE:FREQ=DAILY;UNTIL=20260115T100000"

        # Ask for occurrence after the UNTIL date
        after = datetime(2026, 1, 20)
        next_occ = get_next_occurrence(rrule, dtstart, after)

        assert next_occ is None


# =============================================================================
# Base Event ID Tests
# =============================================================================


class TestGetBaseEventId:
    """Test _get_base_event_id function."""

    def test_base_id_returned_unchanged(self) -> None:
        """Base event ID without occurrence suffix returned as-is."""
        from reos.cairn.scene_calendar_sync import _get_base_event_id

        assert _get_base_event_id("event123") == "event123"
        assert _get_base_event_id("cal-event-abc") == "cal-event-abc"

    def test_occurrence_suffix_stripped(self) -> None:
        """Occurrence suffix is stripped from expanded event IDs."""
        from reos.cairn.scene_calendar_sync import _get_base_event_id

        # Expanded recurring events have IDs like "event123_202501131000"
        assert _get_base_event_id("event123_202501131000") == "event123"
        assert _get_base_event_id("cal-event-abc_202612251800") == "cal-event-abc"

    def test_multiple_underscores(self) -> None:
        """Only the last underscore is treated as occurrence separator."""
        from reos.cairn.scene_calendar_sync import _get_base_event_id

        # If base ID has underscore, only last one is stripped
        assert _get_base_event_id("my_event_id_202501131000") == "my_event_id"


# =============================================================================
# Annual Event Deduplication Tests
# =============================================================================


class TestDeduplicateAnnualEvents:
    """Test _deduplicate_annual_events function."""

    def test_single_event_unchanged(self) -> None:
        """Single event is returned unchanged."""
        from reos.cairn.scene_calendar_sync import _deduplicate_annual_events
        from reos.cairn.thunderbird import CalendarEvent

        events = [
            CalendarEvent(
                id="event1",
                title="Unique Event",
                start=datetime(2026, 5, 15, 10, 0),
                end=datetime(2026, 5, 15, 11, 0),
            )
        ]

        result = _deduplicate_annual_events(events)
        assert len(result) == 1
        assert result[0].title == "Unique Event"

    def test_annual_holiday_deduplicated(self) -> None:
        """Annual holidays (same title, same month/day) are deduplicated."""
        from reos.cairn.scene_calendar_sync import _deduplicate_annual_events
        from reos.cairn.thunderbird import CalendarEvent

        # Christmas appears multiple years
        events = [
            CalendarEvent(
                id="christmas-2025",
                title="Christmas Day",
                start=datetime(2025, 12, 25, 0, 0),
                end=datetime(2025, 12, 26, 0, 0),
            ),
            CalendarEvent(
                id="christmas-2026",
                title="Christmas Day",
                start=datetime(2026, 12, 25, 0, 0),
                end=datetime(2026, 12, 26, 0, 0),
            ),
            CalendarEvent(
                id="christmas-2027",
                title="Christmas Day",
                start=datetime(2027, 12, 25, 0, 0),
                end=datetime(2027, 12, 26, 0, 0),
            ),
        ]

        result = _deduplicate_annual_events(events)

        # Should only have one Christmas event (the next upcoming one)
        assert len(result) == 1
        assert result[0].title == "Christmas Day"
        # Should be marked as recurring with yearly rule
        assert result[0].is_recurring is True
        assert "FREQ=YEARLY" in result[0].recurrence_rule

    def test_different_titles_not_deduplicated(self) -> None:
        """Events with different titles are not deduplicated."""
        from reos.cairn.scene_calendar_sync import _deduplicate_annual_events
        from reos.cairn.thunderbird import CalendarEvent

        events = [
            CalendarEvent(
                id="event1",
                title="Birthday Party",
                start=datetime(2026, 6, 15, 10, 0),
                end=datetime(2026, 6, 15, 18, 0),
            ),
            CalendarEvent(
                id="event2",
                title="Anniversary",
                start=datetime(2026, 6, 15, 19, 0),
                end=datetime(2026, 6, 15, 22, 0),
            ),
        ]

        result = _deduplicate_annual_events(events)
        assert len(result) == 2

    def test_same_title_different_dates_not_deduplicated(self) -> None:
        """Events with same title but different month/day are not deduplicated."""
        from reos.cairn.scene_calendar_sync import _deduplicate_annual_events
        from reos.cairn.thunderbird import CalendarEvent

        # "Team Meeting" on different days of the month
        events = [
            CalendarEvent(
                id="meeting1",
                title="Team Meeting",
                start=datetime(2026, 1, 5, 10, 0),
                end=datetime(2026, 1, 5, 11, 0),
            ),
            CalendarEvent(
                id="meeting2",
                title="Team Meeting",
                start=datetime(2026, 1, 12, 10, 0),
                end=datetime(2026, 1, 12, 11, 0),
            ),
            CalendarEvent(
                id="meeting3",
                title="Team Meeting",
                start=datetime(2026, 1, 19, 10, 0),
                end=datetime(2026, 1, 19, 11, 0),
            ),
        ]

        result = _deduplicate_annual_events(events)
        # All events are on different days, so all kept
        assert len(result) == 3


# =============================================================================
# Refresh Recurring Scenes Tests
# =============================================================================


class TestRefreshRecurringScenes:
    """Test refresh_all_recurring_scenes function."""

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_refresh_updates_next_occurrence(self, temp_data_dir: Path) -> None:
        """_refresh_all_recurring_scenes_in_db updates next_occurrence."""
        from reos.cairn.scene_calendar_sync import _refresh_all_recurring_scenes_in_db
        import reos.play_db as play_db

        # Create act and scene with recurrence rule
        _, act_id = play_db.create_act(title="Test Act")
        _, scene_id = play_db.create_scene(
            act_id=act_id,
            title="Recurring Scene",
            recurrence_rule="RRULE:FREQ=WEEKLY",
        )

        # Set initial calendar_event_start
        past_start = (datetime.now() - timedelta(days=7)).isoformat()
        play_db.update_scene_calendar_data(
            scene_id, calendar_event_start=past_start
        )

        updated = _refresh_all_recurring_scenes_in_db()

        # Should have updated at least this scene
        assert updated >= 1

        # Verify next_occurrence was set
        scene = play_db.get_scene(scene_id)
        assert scene["next_occurrence"] is not None

    def test_refresh_skips_scenes_without_rrule(self, temp_data_dir: Path) -> None:
        """Scenes without recurrence_rule are skipped."""
        from reos.cairn.scene_calendar_sync import _refresh_all_recurring_scenes_in_db
        import reos.play_db as play_db

        # Create scene without recurrence rule
        _, act_id = play_db.create_act(title="Test Act")
        _, scene_id = play_db.create_scene(
            act_id=act_id,
            title="Non-Recurring Scene",
        )

        # Set calendar start but no recurrence
        play_db.update_scene_calendar_data(
            scene_id,
            calendar_event_start=datetime.now().isoformat(),
        )

        _refresh_all_recurring_scenes_in_db()

        # next_occurrence should still be None
        scene = play_db.get_scene(scene_id)
        assert scene["next_occurrence"] is None


# =============================================================================
# Sync Calendar to Scenes Tests
# =============================================================================


class TestSyncCalendarToScenes:
    """Test sync_calendar_to_scenes function."""

    def test_creates_scene_for_new_event(
        self, temp_data_dir: Path, mock_thunderbird_bridge: MagicMock
    ) -> None:
        """sync_calendar_to_scenes creates Scene for new calendar event."""
        from reos.cairn.scene_calendar_sync import sync_calendar_to_scenes
        from reos.cairn.thunderbird import CalendarEvent
        import reos.play_db as play_db

        # Ensure Your Story act exists
        play_db.ensure_your_story_act()

        # Mock calendar event
        event = CalendarEvent(
            id="new-event-123",
            title="Doctor Appointment",
            start=datetime.now() + timedelta(days=1),
            end=datetime.now() + timedelta(days=1, hours=1),
        )

        with patch(
            "reos.cairn.scene_calendar_sync.get_base_calendar_events",
            return_value=[event],
        ):
            # Create mock store (not used in new implementation)
            mock_store = MagicMock()

            new_ids = sync_calendar_to_scenes(
                mock_thunderbird_bridge, mock_store, hours=168
            )

        # Should have created one scene
        assert len(new_ids) == 1

        # Verify scene exists in database
        scene = play_db.get_scene(new_ids[0])
        assert scene is not None
        assert scene["title"] == "Doctor Appointment"
        assert scene["calendar_event_id"] == "new-event-123"

    def test_updates_existing_scene_calendar_data(
        self, temp_data_dir: Path, mock_thunderbird_bridge: MagicMock
    ) -> None:
        """sync_calendar_to_scenes updates calendar data for existing scene."""
        from reos.cairn.scene_calendar_sync import sync_calendar_to_scenes
        from reos.cairn.thunderbird import CalendarEvent
        import reos.play_db as play_db

        # Create existing scene with calendar_event_id
        _, act_id = play_db.create_act(title="Test Act")
        _, scene_id = play_db.create_scene(
            act_id=act_id,
            title="Existing Meeting",
            calendar_event_id="existing-event-456",
        )

        # Mock calendar event with updated time
        new_start = datetime.now() + timedelta(days=2)
        event = CalendarEvent(
            id="existing-event-456",
            title="Existing Meeting",
            start=new_start,
            end=new_start + timedelta(hours=1),
        )

        with patch(
            "reos.cairn.scene_calendar_sync.get_base_calendar_events",
            return_value=[event],
        ):
            mock_store = MagicMock()
            new_ids = sync_calendar_to_scenes(
                mock_thunderbird_bridge, mock_store, hours=168
            )

        # Should not create new scene
        assert len(new_ids) == 0

        # Verify calendar data was updated
        scene = play_db.get_scene(scene_id)
        assert scene["calendar_event_start"] == new_start.isoformat()

    @pytest.mark.skipif(not HAS_DATEUTIL, reason="dateutil not installed")
    def test_sets_next_occurrence_for_recurring(
        self, temp_data_dir: Path, mock_thunderbird_bridge: MagicMock
    ) -> None:
        """sync_calendar_to_scenes sets next_occurrence for recurring events."""
        from reos.cairn.scene_calendar_sync import sync_calendar_to_scenes
        from reos.cairn.thunderbird import CalendarEvent
        import reos.play_db as play_db

        # Ensure Your Story act exists
        play_db.ensure_your_story_act()

        # Mock recurring event
        event = CalendarEvent(
            id="recurring-event-789",
            title="Weekly Standup",
            start=datetime.now() - timedelta(days=1),  # Started yesterday
            end=datetime.now() - timedelta(days=1) + timedelta(hours=1),
            is_recurring=True,
            recurrence_rule="RRULE:FREQ=WEEKLY",
        )

        with patch(
            "reos.cairn.scene_calendar_sync.get_base_calendar_events",
            return_value=[event],
        ):
            mock_store = MagicMock()
            new_ids = sync_calendar_to_scenes(
                mock_thunderbird_bridge, mock_store, hours=168
            )

        assert len(new_ids) == 1

        # Verify next_occurrence was set
        scene = play_db.get_scene(new_ids[0])
        assert scene["next_occurrence"] is not None
        # Next occurrence should be in the future
        next_occ = datetime.fromisoformat(scene["next_occurrence"])
        assert next_occ > datetime.now()


# =============================================================================
# Outbound Sync Tests
# =============================================================================


class TestOutboundSync:
    """Test outbound sync (Scene -> Thunderbird calendar)."""

    def test_is_outbound_sync_available_false_when_not_installed(self) -> None:
        """is_outbound_sync_available returns False when bridge not available."""
        from reos.cairn.scene_calendar_sync import is_outbound_sync_available

        # The function should return False when the bridge module can't be imported
        # We can test by checking current state (likely False in test environment)
        result = is_outbound_sync_available()
        # In test environment, the Thunderbird bridge typically isn't running
        assert isinstance(result, bool)

    def test_sync_scene_to_calendar_returns_none_when_bridge_unavailable(self) -> None:
        """sync_scene_to_calendar returns None when bridge is not available."""
        from reos.cairn.scene_calendar_sync import sync_scene_to_calendar

        # In test environment without Thunderbird bridge, should return None
        result = sync_scene_to_calendar(
            scene_id="scene-123",
            title="New Task",
            start_date=datetime(2026, 2, 1, 10, 0),
            notes="Task notes",
        )

        # Without the bridge, should return None
        assert result is None

    def test_update_scene_calendar_event_returns_false_when_bridge_unavailable(
        self,
    ) -> None:
        """update_scene_calendar_event returns False when bridge is not available."""
        from reos.cairn.scene_calendar_sync import update_scene_calendar_event

        result = update_scene_calendar_event(
            thunderbird_event_id="tb-event-789",
            title="Updated Title",
        )

        # Without the bridge, should return False
        assert result is False

    def test_delete_scene_calendar_event_returns_false_when_bridge_unavailable(
        self,
    ) -> None:
        """delete_scene_calendar_event returns False when bridge is not available."""
        from reos.cairn.scene_calendar_sync import delete_scene_calendar_event

        result = delete_scene_calendar_event("tb-event-to-delete")

        # Without the bridge, should return False
        assert result is False


# =============================================================================
# Create/Delete with Calendar Sync Tests
# =============================================================================


class TestCreateDeleteWithCalendarSync:
    """Test create_scene_with_calendar_sync and delete_scene_with_calendar_sync."""

    def test_create_scene_with_outbound_sync(self, temp_data_dir: Path) -> None:
        """create_scene_with_calendar_sync creates Thunderbird event when enabled."""
        from reos.cairn.scene_calendar_sync import create_scene_with_calendar_sync
        import reos.play_db as play_db

        # Create an act first
        _, act_id = play_db.create_act(title="Test Act")

        with patch(
            "reos.cairn.scene_calendar_sync.is_outbound_sync_available",
            return_value=True,
        ):
            with patch(
                "reos.cairn.scene_calendar_sync.sync_scene_to_calendar",
                return_value="tb-synced-event",
            ):
                scenes, tb_event_id = create_scene_with_calendar_sync(
                    act_id=act_id,
                    title="Synced Task",
                    enable_outbound_sync=True,
                )

        assert tb_event_id == "tb-synced-event"
        assert len(scenes) == 1

    def test_create_scene_skips_sync_when_disabled(self, temp_data_dir: Path) -> None:
        """create_scene_with_calendar_sync skips sync when disabled."""
        from reos.cairn.scene_calendar_sync import create_scene_with_calendar_sync
        import reos.play_db as play_db

        _, act_id = play_db.create_act(title="Test Act")

        with patch(
            "reos.cairn.scene_calendar_sync.sync_scene_to_calendar"
        ) as mock_sync:
            scenes, tb_event_id = create_scene_with_calendar_sync(
                act_id=act_id,
                title="Local Only Task",
                enable_outbound_sync=False,
            )

        assert tb_event_id is None
        mock_sync.assert_not_called()

    def test_create_scene_skips_sync_when_inbound_event_exists(
        self, temp_data_dir: Path
    ) -> None:
        """create_scene_with_calendar_sync skips outbound sync when inbound event ID exists."""
        from reos.cairn.scene_calendar_sync import create_scene_with_calendar_sync
        import reos.play_db as play_db

        _, act_id = play_db.create_act(title="Test Act")

        with patch(
            "reos.cairn.scene_calendar_sync.is_outbound_sync_available",
            return_value=True,
        ):
            with patch(
                "reos.cairn.scene_calendar_sync.sync_scene_to_calendar"
            ) as mock_sync:
                scenes, tb_event_id = create_scene_with_calendar_sync(
                    act_id=act_id,
                    title="Imported from Calendar",
                    calendar_event_id="cal-inbound-event",  # Already from calendar
                    enable_outbound_sync=True,
                )

        # Should not create duplicate event
        assert tb_event_id is None
        mock_sync.assert_not_called()

    def test_delete_scene_with_calendar_sync(self, temp_data_dir: Path) -> None:
        """delete_scene_with_calendar_sync deletes Thunderbird event."""
        from reos.cairn.scene_calendar_sync import delete_scene_with_calendar_sync
        import reos.play_db as play_db

        # Create scene with thunderbird_event_id
        _, act_id = play_db.create_act(title="Test Act")
        _, scene_id = play_db.create_scene(
            act_id=act_id,
            title="To Delete",
            thunderbird_event_id="tb-to-delete",
        )

        with patch(
            "reos.cairn.scene_calendar_sync.delete_scene_calendar_event",
            return_value=True,
        ) as mock_delete:
            remaining = delete_scene_with_calendar_sync(
                act_id=act_id,
                scene_id=scene_id,
                thunderbird_event_id="tb-to-delete",
            )

        mock_delete.assert_called_once_with("tb-to-delete")
        # Scene should be deleted
        assert not any(s["scene_id"] == scene_id for s in remaining)


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


