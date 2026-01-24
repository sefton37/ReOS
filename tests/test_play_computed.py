"""Tests for play_computed.py - computed fields for Play scenes.

Tests all computed field logic:
- _is_placeholder_date: Dec 31 current year detection
- is_unscheduled: No calendar event detection
- is_overdue: Past date detection (with 1-hour grace)
- compute_effective_stage: Kanban column mapping
- enrich_scene_for_display: Adding computed fields to scenes
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from reos.play_computed import (
    _is_placeholder_date,
    compute_effective_stage,
    enrich_scene_for_display,
    is_overdue,
    is_unscheduled,
)


# =============================================================================
# _is_placeholder_date Tests
# =============================================================================


class TestIsPlaceholderDate:
    """Test _is_placeholder_date function."""

    def test_current_year_dec_31_is_placeholder(self) -> None:
        """Dec 31 of current year is the placeholder date."""
        current_year = datetime.now().year
        placeholder_date = datetime(current_year, 12, 31, 12, 0, 0)
        assert _is_placeholder_date(placeholder_date) is True

    def test_current_year_dec_31_any_time_is_placeholder(self) -> None:
        """Dec 31 is placeholder regardless of time of day."""
        current_year = datetime.now().year
        # Midnight
        assert _is_placeholder_date(datetime(current_year, 12, 31, 0, 0, 0)) is True
        # End of day
        assert _is_placeholder_date(datetime(current_year, 12, 31, 23, 59, 59)) is True

    def test_other_dates_not_placeholder(self) -> None:
        """Other dates are not placeholders."""
        current_year = datetime.now().year
        # Dec 30
        assert _is_placeholder_date(datetime(current_year, 12, 30, 12, 0, 0)) is False
        # Jan 1
        assert _is_placeholder_date(datetime(current_year, 1, 1, 12, 0, 0)) is False
        # Random date
        assert _is_placeholder_date(datetime(current_year, 6, 15, 12, 0, 0)) is False

    def test_previous_year_dec_31_not_placeholder(self) -> None:
        """Dec 31 of previous year is NOT a placeholder."""
        current_year = datetime.now().year
        past_placeholder = datetime(current_year - 1, 12, 31, 12, 0, 0)
        assert _is_placeholder_date(past_placeholder) is False

    def test_future_year_dec_31_not_placeholder(self) -> None:
        """Dec 31 of future year is NOT a placeholder."""
        current_year = datetime.now().year
        future_placeholder = datetime(current_year + 1, 12, 31, 12, 0, 0)
        assert _is_placeholder_date(future_placeholder) is False


# =============================================================================
# is_unscheduled Tests
# =============================================================================


class TestIsUnscheduled:
    """Test is_unscheduled function."""

    def test_no_calendar_event_is_unscheduled(self) -> None:
        """Scene with no calendar data is unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
        }
        assert is_unscheduled(scene) is True

    def test_no_calendar_event_no_thunderbird_is_unscheduled(self) -> None:
        """Scene with no calendar_event_start AND no thunderbird_event_id is unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": None,
            "thunderbird_event_id": None,
        }
        assert is_unscheduled(scene) is True

    def test_with_calendar_event_not_unscheduled(self) -> None:
        """Scene with calendar_event_start is NOT unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": "2026-01-15T10:00:00",
        }
        assert is_unscheduled(scene) is False

    def test_with_calendar_event_datetime_not_unscheduled(self) -> None:
        """Scene with calendar_event_start as datetime is NOT unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": datetime(2026, 1, 15, 10, 0, 0),
        }
        assert is_unscheduled(scene) is False

    def test_placeholder_date_is_unscheduled(self) -> None:
        """Scene scheduled for placeholder date (Dec 31 current year) is unscheduled."""
        current_year = datetime.now().year
        placeholder_iso = f"{current_year}-12-31T12:00:00"
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": placeholder_iso,
        }
        assert is_unscheduled(scene) is True

    def test_thunderbird_event_not_unscheduled(self) -> None:
        """Scene with thunderbird_event_id is NOT unscheduled (outbound sync)."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "thunderbird_event_id": "tb-event-123",
        }
        assert is_unscheduled(scene) is False

    def test_next_occurrence_takes_precedence(self) -> None:
        """next_occurrence is used over calendar_event_start for recurring events."""
        # Base event is in past, but next occurrence is in future
        scene: dict = {
            "scene_id": "test-1",
            "title": "Recurring Event",
            "stage": "planning",
            "calendar_event_start": "2024-01-01T10:00:00",  # Past
            "next_occurrence": "2026-06-15T10:00:00",  # Future
        }
        # next_occurrence is valid future date, so NOT unscheduled
        assert is_unscheduled(scene) is False

    def test_next_occurrence_placeholder_is_unscheduled(self) -> None:
        """If next_occurrence is placeholder date, scene is unscheduled."""
        current_year = datetime.now().year
        scene: dict = {
            "scene_id": "test-1",
            "title": "Recurring Event",
            "stage": "planning",
            "next_occurrence": f"{current_year}-12-31T12:00:00",
        }
        assert is_unscheduled(scene) is True

    def test_invalid_date_format_is_unscheduled(self) -> None:
        """Invalid date format is treated as unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": "not-a-date",
        }
        assert is_unscheduled(scene) is True

    def test_iso_format_with_timezone_z(self) -> None:
        """ISO format with Z timezone suffix works correctly."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": "2026-01-15T10:00:00Z",
        }
        assert is_unscheduled(scene) is False

    def test_iso_format_with_timezone_offset(self) -> None:
        """ISO format with timezone offset works correctly."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": "2026-01-15T10:00:00+05:00",
        }
        assert is_unscheduled(scene) is False

    def test_invalid_date_type_is_unscheduled(self) -> None:
        """Invalid date type (not str or datetime) is unscheduled."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": 12345,  # Integer, not valid
        }
        assert is_unscheduled(scene) is True


# =============================================================================
# is_overdue Tests
# =============================================================================


class TestIsOverdue:
    """Test is_overdue function."""

    def test_complete_scene_never_overdue(self) -> None:
        """Completed scenes are never overdue."""
        past_date = (datetime.now() - timedelta(days=7)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "complete",
            "calendar_event_start": past_date,
        }
        assert is_overdue(scene) is False

    def test_past_date_is_overdue(self) -> None:
        """Scene with date in past (more than 1 hour ago) is overdue."""
        past_date = (datetime.now() - timedelta(days=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": past_date,
        }
        assert is_overdue(scene) is True

    def test_future_date_not_overdue(self) -> None:
        """Scene with future date is NOT overdue."""
        future_date = (datetime.now() + timedelta(days=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": future_date,
        }
        assert is_overdue(scene) is False

    def test_within_one_hour_not_overdue(self) -> None:
        """Scene with date within 1 hour (grace period) is NOT overdue."""
        # 30 minutes ago - within 1-hour grace period
        recent_date = (datetime.now() - timedelta(minutes=30)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": recent_date,
        }
        assert is_overdue(scene) is False

    def test_just_under_one_hour_ago_not_overdue(self) -> None:
        """Scene with date just under 1 hour ago is NOT overdue (boundary condition)."""
        # 59 minutes ago - just under the 1-hour threshold
        just_under_hour = (datetime.now() - timedelta(minutes=59)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": just_under_hour,
        }
        # Under 1 hour = NOT overdue
        assert is_overdue(scene) is False

    def test_more_than_one_hour_ago_is_overdue(self) -> None:
        """Scene with date more than 1 hour ago is overdue."""
        past_date = (datetime.now() - timedelta(hours=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": past_date,
        }
        assert is_overdue(scene) is True

    def test_no_date_not_overdue(self) -> None:
        """Scene with no date cannot be overdue."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
        }
        assert is_overdue(scene) is False

    def test_next_occurrence_used_for_recurring(self) -> None:
        """next_occurrence is used for recurring events."""
        # Base event in past, but next_occurrence in future
        scene: dict = {
            "scene_id": "test-1",
            "title": "Recurring Event",
            "stage": "in_progress",
            "calendar_event_start": (datetime.now() - timedelta(days=30)).isoformat(),
            "next_occurrence": (datetime.now() + timedelta(days=1)).isoformat(),
        }
        # next_occurrence is in future, so NOT overdue
        assert is_overdue(scene) is False

    def test_next_occurrence_past_is_overdue(self) -> None:
        """next_occurrence in past makes recurring scene overdue."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Recurring Event",
            "stage": "in_progress",
            "next_occurrence": (datetime.now() - timedelta(days=2)).isoformat(),
        }
        assert is_overdue(scene) is True

    def test_datetime_object_works(self) -> None:
        """datetime object (not just string) works for dates."""
        past_date = datetime.now() - timedelta(days=2)
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": past_date,
        }
        assert is_overdue(scene) is True

    def test_invalid_date_string_not_overdue(self) -> None:
        """Invalid date string is NOT overdue (can't determine)."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": "invalid-date",
        }
        assert is_overdue(scene) is False

    def test_invalid_date_type_not_overdue(self) -> None:
        """Invalid date type (not str/datetime) is NOT overdue."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": 12345,
        }
        assert is_overdue(scene) is False

    def test_with_timezone_z_suffix(self) -> None:
        """Timezone Z suffix is handled correctly."""
        past_date = (datetime.now() - timedelta(days=2)).isoformat() + "Z"
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": past_date,
        }
        assert is_overdue(scene) is True


# =============================================================================
# compute_effective_stage Tests
# =============================================================================


class TestComputeEffectiveStage:
    """Test compute_effective_stage function."""

    def test_complete_stays_complete(self) -> None:
        """Completed items always stay in 'complete' column."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "complete",
            # Even with old overdue date
            "calendar_event_start": (datetime.now() - timedelta(days=30)).isoformat(),
        }
        assert compute_effective_stage(scene) == "complete"

    def test_unscheduled_goes_to_planning(self) -> None:
        """Unscheduled items go to 'planning' column."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",  # Original stage doesn't matter
            # No calendar data = unscheduled
        }
        assert compute_effective_stage(scene) == "planning"

    def test_overdue_goes_to_need_attention(self) -> None:
        """Overdue items go to 'need_attention' column."""
        past_date = (datetime.now() - timedelta(days=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": past_date,
        }
        assert compute_effective_stage(scene) == "need_attention"

    def test_planning_with_date_becomes_in_progress(self) -> None:
        """'planning' stage with scheduled date becomes 'in_progress'."""
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
            "calendar_event_start": future_date,
        }
        assert compute_effective_stage(scene) == "in_progress"

    def test_awaiting_data_preserved(self) -> None:
        """'awaiting_data' stage is preserved when scheduled."""
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "awaiting_data",
            "calendar_event_start": future_date,
        }
        assert compute_effective_stage(scene) == "awaiting_data"

    def test_in_progress_preserved(self) -> None:
        """'in_progress' stage is preserved when scheduled."""
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": future_date,
        }
        assert compute_effective_stage(scene) == "in_progress"

    def test_no_stage_defaults_to_planning(self) -> None:
        """Missing stage defaults to 'planning'."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
        }
        # No date = unscheduled = planning
        assert compute_effective_stage(scene) == "planning"

    def test_empty_stage_becomes_in_progress_when_scheduled(self) -> None:
        """Empty string stage becomes 'in_progress' when scheduled."""
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "",
            "calendar_event_start": future_date,
        }
        assert compute_effective_stage(scene) == "in_progress"

    def test_priority_order_complete_first(self) -> None:
        """Complete always wins regardless of other conditions."""
        # Even if it looks "unscheduled" and "overdue"
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "complete",
            # No calendar data (would be "unscheduled" if not complete)
        }
        assert compute_effective_stage(scene) == "complete"

    def test_priority_order_unscheduled_before_overdue(self) -> None:
        """Unscheduled check happens before overdue check."""
        # A scene without calendar data can't be overdue
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            # No calendar data
        }
        assert compute_effective_stage(scene) == "planning"


# =============================================================================
# enrich_scene_for_display Tests
# =============================================================================


class TestEnrichSceneForDisplay:
    """Test enrich_scene_for_display function."""

    def test_adds_all_computed_fields(self) -> None:
        """Adds is_unscheduled, is_overdue, effective_stage fields."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
        }
        enriched = enrich_scene_for_display(scene)

        assert "is_unscheduled" in enriched
        assert "is_overdue" in enriched
        assert "effective_stage" in enriched

    def test_does_not_mutate_original(self) -> None:
        """Original scene dict is NOT mutated."""
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "planning",
        }
        original_keys = set(scene.keys())

        enriched = enrich_scene_for_display(scene)

        # Original unchanged
        assert set(scene.keys()) == original_keys
        assert "is_unscheduled" not in scene
        # Enriched has new fields
        assert "is_unscheduled" in enriched

    def test_handles_minimal_scene_dict(self) -> None:
        """Handles scene dict with only required fields."""
        scene: dict = {
            "scene_id": "test-1",
        }
        enriched = enrich_scene_for_display(scene)

        # Should not raise, should add computed fields
        assert enriched["is_unscheduled"] is True
        assert enriched["is_overdue"] is False
        assert enriched["effective_stage"] == "planning"

    def test_preserves_original_fields(self) -> None:
        """All original fields are preserved in enriched dict."""
        scene: dict = {
            "scene_id": "test-1",
            "act_id": "act-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "notes": "Some notes",
            "link": "https://example.com",
            "calendar_event_id": "cal-123",
            "calendar_event_start": (datetime.now() + timedelta(days=1)).isoformat(),
        }
        enriched = enrich_scene_for_display(scene)

        # All original fields preserved
        for key in scene:
            assert key in enriched
            assert enriched[key] == scene[key]

    def test_computed_values_correct_for_scheduled_scene(self) -> None:
        """Computed values are correct for a scheduled, non-overdue scene."""
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": future_date,
        }
        enriched = enrich_scene_for_display(scene)

        assert enriched["is_unscheduled"] is False
        assert enriched["is_overdue"] is False
        assert enriched["effective_stage"] == "in_progress"

    def test_computed_values_correct_for_overdue_scene(self) -> None:
        """Computed values are correct for an overdue scene."""
        past_date = (datetime.now() - timedelta(days=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "in_progress",
            "calendar_event_start": past_date,
        }
        enriched = enrich_scene_for_display(scene)

        assert enriched["is_unscheduled"] is False
        assert enriched["is_overdue"] is True
        assert enriched["effective_stage"] == "need_attention"

    def test_computed_values_correct_for_complete_scene(self) -> None:
        """Completed scene has correct computed values."""
        past_date = (datetime.now() - timedelta(days=2)).isoformat()
        scene: dict = {
            "scene_id": "test-1",
            "title": "Test Scene",
            "stage": "complete",
            "calendar_event_start": past_date,
        }
        enriched = enrich_scene_for_display(scene)

        # Complete is never unscheduled or overdue for display purposes
        assert enriched["is_unscheduled"] is False
        assert enriched["is_overdue"] is False
        assert enriched["effective_stage"] == "complete"
