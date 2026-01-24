"""Computed fields for Play scenes.

This module provides backend computation of derived fields like effective_stage,
ensuring the UI receives ready-to-display data rather than computing it itself.

The effective_stage logic mirrors playKanbanBoard.ts:42-144 exactly:
- complete -> 'complete'
- unscheduled -> 'planning'
- overdue -> 'need_attention'
- planning + scheduled -> 'in_progress'
- else -> raw stage
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _is_placeholder_date(date: datetime) -> bool:
    """Check if a date is the placeholder date (December 31 of current year).

    The placeholder is used for manually created scenes that haven't been scheduled.
    """
    current_year = datetime.now().year
    return date.month == 12 and date.day == 31 and date.year == current_year


def is_unscheduled(scene: dict[str, Any]) -> bool:
    """Determine if a scene is "unscheduled" (belongs in Planning column).

    A scene is unscheduled if:
    1. It has no calendar_event_start AND no thunderbird_event_id, OR
    2. Its calendar_event_start is the placeholder date (Dec 31 of current year)

    Args:
        scene: Scene dict with calendar fields.

    Returns:
        True if unscheduled, False otherwise.
    """
    # Use next_occurrence for recurring events, otherwise calendar_event_start
    event_date = scene.get("next_occurrence") or scene.get("calendar_event_start")

    # No calendar event at all
    if not event_date and not scene.get("thunderbird_event_id"):
        return True

    # Check if scheduled for placeholder date (Dec 31 of current year)
    if event_date:
        try:
            if isinstance(event_date, str):
                # Handle ISO format with timezone
                date_str = event_date.replace("Z", "+00:00")
                date = datetime.fromisoformat(date_str)
                if date.tzinfo is not None:
                    date = date.replace(tzinfo=None)
            elif isinstance(event_date, datetime):
                date = event_date
            else:
                return True  # Invalid date type

            if _is_placeholder_date(date):
                return True
        except (ValueError, TypeError):
            # Invalid date, treat as unscheduled
            return True

    return False


def is_overdue(scene: dict[str, Any]) -> bool:
    """Determine if a scene is overdue (date has passed but not complete).

    A scene is overdue if:
    1. It has a calendar date (next_occurrence or calendar_event_start)
    2. That date is in the past (more than 1 hour ago to allow for in-progress meetings)
    3. The scene is NOT marked as complete

    Args:
        scene: Scene dict with stage and calendar fields.

    Returns:
        True if overdue, False otherwise.
    """
    # Already complete - not overdue
    if scene.get("stage") == "complete":
        return False

    # Use next_occurrence for recurring events, otherwise calendar_event_start
    event_date = scene.get("next_occurrence") or scene.get("calendar_event_start")

    if not event_date:
        return False  # No date, can't be overdue

    try:
        if isinstance(event_date, str):
            # Handle ISO format with timezone
            date_str = event_date.replace("Z", "+00:00")
            date = datetime.fromisoformat(date_str)
            if date.tzinfo is not None:
                date = date.replace(tzinfo=None)
        elif isinstance(event_date, datetime):
            date = event_date
        else:
            return False  # Invalid date type

        now = datetime.now()
        # Consider overdue if more than 1 hour in the past
        one_hour_ago = now - timedelta(hours=1)
        return date < one_hour_ago
    except (ValueError, TypeError):
        return False


def compute_effective_stage(scene: dict[str, Any]) -> str:
    """Get the effective Kanban column for a scene.

    Priority order:
    1. Completed items -> 'complete'
    2. Unscheduled items -> 'planning'
    3. Overdue items (date passed, not complete) -> 'need_attention'
    4. Scheduled items use their actual stage, but 'planning' becomes 'in_progress'

    Args:
        scene: Scene dict with stage and calendar fields.

    Returns:
        The effective stage string: 'planning', 'in_progress', 'awaiting_data',
        'need_attention', or 'complete'.
    """
    raw_stage = scene.get("stage", "planning")

    # Completed items stay in Complete regardless of scheduling
    if raw_stage == "complete":
        return "complete"

    # Unscheduled items always go to Planning
    if is_unscheduled(scene):
        return "planning"

    # Overdue items (date passed but not complete) go to Need Attention
    if is_overdue(scene):
        return "need_attention"

    # For scheduled items, 'planning' stage becomes 'in_progress' since they have a date
    # (Planning column is only for unscheduled items)
    if raw_stage == "planning":
        return "in_progress"

    # For other scheduled items, use actual stage
    return raw_stage or "in_progress"


def enrich_scene_for_display(scene: dict[str, Any]) -> dict[str, Any]:
    """Enrich a scene dict with computed fields for UI display.

    Adds:
    - effective_stage: The Kanban column this scene should appear in
    - is_unscheduled: Whether the scene has no calendar event
    - is_overdue: Whether the scene's date has passed

    Args:
        scene: Scene dict from the database.

    Returns:
        Enriched scene dict with computed fields added.
    """
    enriched = dict(scene)  # Copy to avoid mutating original

    enriched["is_unscheduled"] = is_unscheduled(scene)
    enriched["is_overdue"] = is_overdue(scene)
    enriched["effective_stage"] = compute_effective_stage(scene)

    return enriched
