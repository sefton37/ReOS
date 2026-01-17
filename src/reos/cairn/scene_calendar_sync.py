"""Scene-Calendar Sync for CAIRN.

Bidirectional sync between Thunderbird calendar and Scenes:
- Inbound: Syncs calendar events from Thunderbird to Scenes
- Outbound: Syncs Scenes to Thunderbird calendar events

ONE Scene per calendar event (recurring events are NOT expanded).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.cairn.store import CairnStore
    from reos.cairn.thunderbird import ThunderbirdBridge

logger = logging.getLogger(__name__)

# Placeholder date for Scenes without a specific date (Dec 31, 2099)
PLACEHOLDER_DATE = datetime(2099, 12, 31, 12, 0, 0)


def get_next_occurrence(rrule_str: str, dtstart: datetime, after: datetime | None = None) -> datetime | None:
    """Get the next occurrence of a recurring event.

    Args:
        rrule_str: The RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO").
        dtstart: The original start datetime of the event.
        after: Find next occurrence after this time (default: now).

    Returns:
        The next occurrence datetime, or None if no more occurrences.
    """
    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        logger.debug("dateutil not available, cannot compute next occurrence")
        return None

    if after is None:
        after = datetime.now()

    try:
        # Strip "RRULE:" prefix if present
        rule_text = rrule_str
        if rule_text.startswith("RRULE:"):
            rule_text = rule_text[6:]

        # Handle timezone issues: UNTIL with Z suffix needs conversion
        if "UNTIL=" in rule_text and "Z" in rule_text:
            import re
            match = re.search(r"UNTIL=(\d{8}T\d{6})Z", rule_text)
            if match:
                until_str = match.group(1)
                from datetime import timezone
                until_utc = datetime.strptime(until_str, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                until_local = until_utc.astimezone().replace(tzinfo=None)
                rule_text = rule_text.replace(
                    f"UNTIL={until_str}Z",
                    f"UNTIL={until_local.strftime('%Y%m%dT%H%M%S')}"
                )

        # Create rrule with the event's original start as dtstart
        rule = rrulestr(rule_text, dtstart=dtstart)

        # Get next occurrence after the specified time
        next_dt = rule.after(after, inc=False)
        return next_dt

    except Exception as e:
        logger.debug("Failed to compute next occurrence: %s", e)
        return None


def _get_base_event_id(event_id: str) -> str:
    """Extract the base event ID from an occurrence ID.

    Expanded recurring events have IDs like "event123_202501131000".
    This extracts "event123".

    Args:
        event_id: The event ID (may be base or occurrence).

    Returns:
        The base event ID.
    """
    if "_" in event_id:
        return event_id.rsplit("_", 1)[0]
    return event_id


def refresh_all_recurring_scenes(store: "CairnStore") -> int:
    """Refresh next_occurrence for ALL recurring scenes in the database.

    This ensures that even if the calendar query misses an event,
    the next_occurrence values stay current.

    Args:
        store: CairnStore instance.

    Returns:
        Number of scenes updated.
    """
    updated = 0
    recurring_scenes = store.get_all_recurring_scenes()

    for scene_info in recurring_scenes:
        rrule = scene_info.get("recurrence_rule")
        start_str = scene_info.get("calendar_event_start")

        if not rrule or not start_str:
            continue

        try:
            if isinstance(start_str, str):
                start = datetime.fromisoformat(start_str)
            else:
                start = start_str

            next_occ = get_next_occurrence(rrule, start)
            if next_occ:
                store.update_scene_next_occurrence(
                    scene_id=scene_info["scene_id"],
                    next_occurrence=next_occ,
                )
                updated += 1
        except Exception as e:
            logger.debug("Failed to refresh next_occurrence for scene %s: %s",
                        scene_info.get("scene_id"), e)

    return updated


def sync_calendar_to_scenes(
    thunderbird: "ThunderbirdBridge",
    store: "CairnStore",
    hours: int = 168,
) -> list[str]:
    """Sync calendar events to Scenes in The Play.

    For each calendar event (NOT expanded recurring events):
    1. Check if a Scene already exists for this event
    2. If not, create a Scene in "Your Story" Act
    3. Link the Scene to the calendar event
    4. For recurring events, compute and store next occurrence

    Also refreshes next_occurrence for ALL recurring scenes to ensure
    they stay current even if the calendar query misses them.

    Args:
        thunderbird: ThunderbirdBridge instance.
        store: CairnStore instance.
        hours: Hours to look ahead for events (default: 168 = 1 week).

    Returns:
        List of newly created Scene IDs.
    """
    from reos.play_fs import (
        YOUR_STORY_ACT_ID,
        create_scene,
        ensure_your_story_act,
        find_scene_location,
    )

    # First, refresh next_occurrence for ALL recurring scenes
    # This ensures stale values get updated even if calendar query misses them
    refreshed = refresh_all_recurring_scenes(store)
    if refreshed > 0:
        logger.debug("Refreshed next_occurrence for %d recurring scenes", refreshed)

    # Ensure Your Story Act exists
    ensure_your_story_act()

    new_scene_ids: list[str] = []

    # Get base (non-expanded) calendar events
    base_events = get_base_calendar_events(thunderbird, hours)

    for event in base_events:
        base_event_id = _get_base_event_id(event.id)

        # Check if a Scene already exists for this event
        existing = store.get_scene_id_for_calendar_event(base_event_id)
        if existing:
            # Update next occurrence for recurring events
            if event.recurrence_rule:
                next_occ = get_next_occurrence(event.recurrence_rule, event.start)
                if next_occ:
                    # Get canonical location from play_fs (source of truth) instead of stale cache
                    scene_location = find_scene_location(existing["scene_id"])
                    canonical_act_id = scene_location["act_id"] if scene_location else YOUR_STORY_ACT_ID
                    store.update_scene_calendar_link(
                        scene_id=existing["scene_id"],
                        calendar_event_id=base_event_id,
                        recurrence_rule=event.recurrence_rule,
                        next_occurrence=next_occ,
                        act_id=canonical_act_id,
                    )
            continue

        # Create a new Scene for this event
        try:
            stage = "in_progress" if event.start <= datetime.now() else "planning"
            scenes, scene_id = create_scene(
                act_id=YOUR_STORY_ACT_ID,
                title=event.title,
                stage=stage,
                notes=event.description or "",
                calendar_event_id=base_event_id,
                recurrence_rule=event.recurrence_rule,
            )

            if scene_id:
                new_scene_ids.append(scene_id)

                # Compute next occurrence for recurring events
                next_occ = None
                if event.recurrence_rule:
                    next_occ = get_next_occurrence(event.recurrence_rule, event.start)

                # Link the scene to the calendar event with full metadata
                store.link_scene_to_calendar_event_full(
                    scene_id=scene_id,
                    calendar_event_id=base_event_id,
                    calendar_event_title=event.title,
                    calendar_event_start=event.start,
                    calendar_event_end=event.end,
                    recurrence_rule=event.recurrence_rule,
                    next_occurrence=next_occ,
                    act_id=YOUR_STORY_ACT_ID,
                )

                logger.debug(
                    "Created Scene '%s' for calendar event '%s'",
                    event.title,
                    base_event_id,
                )

        except Exception as e:
            logger.warning("Failed to create Scene for event '%s': %s", event.title, e)

    return new_scene_ids


def get_base_calendar_events(
    thunderbird: "ThunderbirdBridge",
    hours: int = 168,
) -> list:
    """Get base (non-expanded) calendar events from Thunderbird.

    This returns ONE event per recurring series (not expanded occurrences).
    For non-recurring events within the time window, returns as-is.
    For recurring events, returns the base event regardless of occurrence timing.

    Args:
        thunderbird: ThunderbirdBridge instance.
        hours: Hours to look ahead.

    Returns:
        List of CalendarEvent objects.
    """
    if not thunderbird.has_calendar():
        return []

    from reos.cairn.thunderbird import CalendarEvent

    now = datetime.now()
    end = now + timedelta(hours=hours)
    start_us = int(now.timestamp() * 1_000_000)
    end_us = int(end.timestamp() * 1_000_000)

    try:
        conn = thunderbird._open_calendar_db()
        if conn is None:
            return []

        events = []
        seen_ids = set()

        # 1. Get non-recurring events in the time window
        rows = conn.execute(
            """
            SELECT e.id, e.title, e.event_start, e.event_end, e.event_stamp, e.flags
            FROM cal_events e
            LEFT JOIN cal_recurrence r ON e.id = r.item_id AND e.cal_id = r.cal_id
            WHERE e.event_start <= ? AND e.event_end >= ?
              AND (r.icalString IS NULL OR r.icalString NOT LIKE 'RRULE:%')
            ORDER BY e.event_start
            """,
            (end_us, start_us),
        ).fetchall()

        for row in rows:
            event = thunderbird._parse_event(row)
            if event and event.id not in seen_ids:
                events.append(event)
                seen_ids.add(event.id)

        # 2. Get ALL recurring events (not filtered by time - we want the base event)
        # Filter to only those that have an occurrence within our window
        recurring_rows = conn.execute(
            """
            SELECT DISTINCT e.id, e.title, e.event_start, e.event_end,
                   e.event_stamp, e.flags, r.icalString as rrule
            FROM cal_events e
            JOIN cal_recurrence r ON e.id = r.item_id AND e.cal_id = r.cal_id
            WHERE r.icalString LIKE 'RRULE:%'
            """,
        ).fetchall()

        conn.close()

        for row in recurring_rows:
            base_id = row["id"]
            if base_id in seen_ids:
                continue

            base_event = thunderbird._parse_event(row)
            if base_event:
                # Only include if there's an occurrence within our window
                rrule_str = row["rrule"]
                base_event = CalendarEvent(
                    id=base_event.id,
                    title=base_event.title,
                    start=base_event.start,
                    end=base_event.end,
                    location=base_event.location,
                    description=base_event.description,
                    status=base_event.status,
                    all_day=base_event.all_day,
                    is_recurring=True,
                    recurrence_rule=rrule_str,
                    recurrence_frequency=base_event.recurrence_frequency,
                )

                # Check if there's an occurrence within our time window
                next_occ = get_next_occurrence(rrule_str, base_event.start, after=now - timedelta(hours=1))
                if next_occ and next_occ <= end:
                    events.append(base_event)
                    seen_ids.add(base_id)

        # Sort by next occurrence (for recurring) or start time
        def sort_key(e):
            if e.is_recurring and e.recurrence_rule:
                next_occ = get_next_occurrence(e.recurrence_rule, e.start)
                return next_occ if next_occ else e.start
            return e.start

        events.sort(key=sort_key)
        return events

    except Exception as e:
        logger.warning("Failed to get base calendar events: %s", e)
        return []


# =============================================================================
# Outbound Sync: Scene -> Thunderbird Calendar
# =============================================================================


def sync_scene_to_calendar(
    scene_id: str,
    title: str,
    start_date: datetime | None = None,
    notes: str | None = None,
) -> str | None:
    """Create a Thunderbird calendar event for a Scene.

    This is called when a new Scene is created and outbound sync is enabled.
    Uses a placeholder date (Dec 31, 2099) if no date is specified.

    Args:
        scene_id: The Scene ID (for logging).
        title: Scene title (used as event title).
        start_date: Event date (default: placeholder date).
        notes: Scene notes (used as event description).

    Returns:
        The Thunderbird event ID if created, None otherwise.
    """
    try:
        from reos.cairn.thunderbird_bridge import create_calendar_event_for_beat
    except ImportError:
        logger.debug("Thunderbird bridge not available")
        return None

    event_id = create_calendar_event_for_beat(
        title=title,
        start_date=start_date,
        notes=notes,
    )

    if event_id:
        logger.debug("Created Thunderbird event %s for Scene %s", event_id, scene_id)

    return event_id


def update_scene_calendar_event(
    thunderbird_event_id: str,
    title: str | None = None,
    start_date: datetime | None = None,
    notes: str | None = None,
) -> bool:
    """Update the Thunderbird calendar event for a Scene.

    Args:
        thunderbird_event_id: The Thunderbird event ID to update.
        title: New title (optional).
        start_date: New date (optional).
        notes: New notes/description (optional).

    Returns:
        True if updated, False otherwise.
    """
    try:
        from reos.cairn.thunderbird_bridge import update_calendar_event_for_beat
    except ImportError:
        logger.debug("Thunderbird bridge not available")
        return False

    return update_calendar_event_for_beat(
        event_id=thunderbird_event_id,
        title=title,
        start_date=start_date,
        notes=notes,
    )


def delete_scene_calendar_event(thunderbird_event_id: str) -> bool:
    """Delete the Thunderbird calendar event for a Scene.

    Args:
        thunderbird_event_id: The Thunderbird event ID to delete.

    Returns:
        True if deleted (or already gone), False otherwise.
    """
    try:
        from reos.cairn.thunderbird_bridge import delete_calendar_event_for_beat
    except ImportError:
        logger.debug("Thunderbird bridge not available")
        return False

    return delete_calendar_event_for_beat(event_id=thunderbird_event_id)


def is_outbound_sync_available() -> bool:
    """Check if outbound sync to Thunderbird is available.

    Returns:
        True if the Talking Rock Bridge add-on is running.
    """
    try:
        from reos.cairn.thunderbird_bridge import is_bridge_available
        return is_bridge_available()
    except ImportError:
        return False


def create_scene_with_calendar_sync(
    act_id: str,
    title: str,
    stage: str = "",
    notes: str = "",
    start_date: datetime | None = None,
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    enable_outbound_sync: bool = True,
) -> tuple[list, str | None]:
    """Create a Scene with optional outbound calendar sync.

    If outbound sync is enabled and the Talking Rock Bridge is available,
    creates a corresponding Thunderbird calendar event.

    Args:
        act_id: The Act ID.
        title: Scene title.
        stage: SceneStage value.
        notes: Scene notes.
        start_date: Optional date for the Scene's calendar event.
        link: Optional external link.
        calendar_event_id: Inbound sync - existing calendar event ID.
        recurrence_rule: RRULE string if recurring.
        enable_outbound_sync: Whether to create a Thunderbird event.

    Returns:
        Tuple of (list of Scenes, thunderbird_event_id or None).
    """
    from reos.play_fs import create_scene

    thunderbird_event_id = None

    # Only do outbound sync if:
    # 1. Enabled
    # 2. No inbound calendar_event_id (don't duplicate events)
    # 3. Bridge is available
    if enable_outbound_sync and not calendar_event_id and is_outbound_sync_available():
        thunderbird_event_id = sync_scene_to_calendar(
            scene_id="pending",  # We don't have the ID yet
            title=title,
            start_date=start_date,
            notes=notes,
        )

    scenes, scene_id = create_scene(
        act_id=act_id,
        title=title,
        stage=stage,
        notes=notes,
        link=link,
        calendar_event_id=calendar_event_id,
        recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id,
    )

    return scenes, thunderbird_event_id


def delete_scene_with_calendar_sync(
    act_id: str,
    scene_id: str,
    thunderbird_event_id: str | None = None,
) -> list:
    """Delete a Scene and its corresponding Thunderbird calendar event.

    Args:
        act_id: The Act ID.
        scene_id: The Scene ID to delete.
        thunderbird_event_id: The Thunderbird event ID to delete (if any).

    Returns:
        List of remaining Scenes in the act.
    """
    from reos.play_fs import delete_scene

    # Delete the Thunderbird event first (if exists)
    if thunderbird_event_id:
        delete_scene_calendar_event(thunderbird_event_id)

    return delete_scene(act_id=act_id, scene_id=scene_id)


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================

# Keep old function names for backward compatibility
refresh_all_recurring_beats = refresh_all_recurring_scenes
sync_calendar_to_beats = sync_calendar_to_scenes
sync_beat_to_calendar = sync_scene_to_calendar
update_beat_calendar_event = update_scene_calendar_event
delete_beat_calendar_event = delete_scene_calendar_event
create_beat_with_calendar_sync = create_scene_with_calendar_sync
delete_beat_with_calendar_sync = delete_scene_with_calendar_sync
