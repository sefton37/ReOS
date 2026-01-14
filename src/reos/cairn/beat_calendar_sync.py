"""Beat-Calendar Sync for CAIRN.

Syncs calendar events from Thunderbird to Beats in The Play.
ONE Beat per calendar event (recurring events are NOT expanded).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.cairn.store import CairnStore
    from reos.cairn.thunderbird import ThunderbirdBridge

logger = logging.getLogger(__name__)


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


def refresh_all_recurring_beats(store: "CairnStore") -> int:
    """Refresh next_occurrence for ALL recurring beats in the database.

    This ensures that even if the calendar query misses an event,
    the next_occurrence values stay current.

    Args:
        store: CairnStore instance.

    Returns:
        Number of beats updated.
    """
    updated = 0
    recurring_beats = store.get_all_recurring_beats()

    for beat_info in recurring_beats:
        rrule = beat_info.get("recurrence_rule")
        start_str = beat_info.get("calendar_event_start")

        if not rrule or not start_str:
            continue

        try:
            if isinstance(start_str, str):
                start = datetime.fromisoformat(start_str)
            else:
                start = start_str

            next_occ = get_next_occurrence(rrule, start)
            if next_occ:
                store.update_beat_next_occurrence(
                    beat_id=beat_info["beat_id"],
                    next_occurrence=next_occ,
                )
                updated += 1
        except Exception as e:
            logger.debug("Failed to refresh next_occurrence for beat %s: %s",
                        beat_info.get("beat_id"), e)

    return updated


def sync_calendar_to_beats(
    thunderbird: "ThunderbirdBridge",
    store: "CairnStore",
    hours: int = 168,
) -> list[str]:
    """Sync calendar events to Beats in The Play.

    For each calendar event (NOT expanded recurring events):
    1. Check if a Beat already exists for this event
    2. If not, create a Beat in "Your Story" -> "Stage Direction"
    3. Link the Beat to the calendar event
    4. For recurring events, compute and store next occurrence

    Also refreshes next_occurrence for ALL recurring beats to ensure
    they stay current even if the calendar query misses them.

    Args:
        thunderbird: ThunderbirdBridge instance.
        store: CairnStore instance.
        hours: Hours to look ahead for events (default: 168 = 1 week).

    Returns:
        List of newly created Beat IDs.
    """
    from reos.play_fs import (
        YOUR_STORY_ACT_ID,
        _get_stage_direction_scene_id,
        create_beat,
        ensure_your_story_act,
    )

    # First, refresh next_occurrence for ALL recurring beats
    # This ensures stale values get updated even if calendar query misses them
    refreshed = refresh_all_recurring_beats(store)
    if refreshed > 0:
        logger.debug("Refreshed next_occurrence for %d recurring beats", refreshed)

    # Ensure Your Story Act and Stage Direction scene exist
    ensure_your_story_act()
    stage_direction_id = _get_stage_direction_scene_id(YOUR_STORY_ACT_ID)

    new_beat_ids: list[str] = []

    # Get base (non-expanded) calendar events
    base_events = get_base_calendar_events(thunderbird, hours)

    for event in base_events:
        base_event_id = _get_base_event_id(event.id)

        # Check if a Beat already exists for this event
        existing = store.get_beat_id_for_calendar_event(base_event_id)
        if existing:
            # Update next occurrence for recurring events
            if event.recurrence_rule:
                next_occ = get_next_occurrence(event.recurrence_rule, event.start)
                if next_occ:
                    store.update_beat_calendar_link(
                        beat_id=existing["beat_id"],
                        calendar_event_id=base_event_id,
                        recurrence_rule=event.recurrence_rule,
                        next_occurrence=next_occ,
                        act_id=existing.get("act_id") or YOUR_STORY_ACT_ID,
                        scene_id=existing.get("scene_id") or stage_direction_id,
                    )
            continue

        # Create a new Beat for this event
        try:
            stage = "in_progress" if event.start <= datetime.now() else "planning"
            beats = create_beat(
                act_id=YOUR_STORY_ACT_ID,
                scene_id=stage_direction_id,
                title=event.title,
                stage=stage,
                notes=event.description or "",
                calendar_event_id=base_event_id,
                recurrence_rule=event.recurrence_rule,
            )

            if beats:
                new_beat = beats[-1]  # Newly created beat is last
                new_beat_ids.append(new_beat.beat_id)

                # Compute next occurrence for recurring events
                next_occ = None
                if event.recurrence_rule:
                    next_occ = get_next_occurrence(event.recurrence_rule, event.start)

                # Link the beat to the calendar event with full metadata
                store.link_beat_to_calendar_event_full(
                    beat_id=new_beat.beat_id,
                    calendar_event_id=base_event_id,
                    calendar_event_title=event.title,
                    calendar_event_start=event.start,
                    calendar_event_end=event.end,
                    recurrence_rule=event.recurrence_rule,
                    next_occurrence=next_occ,
                    act_id=YOUR_STORY_ACT_ID,
                    scene_id=stage_direction_id,
                )

                logger.debug(
                    "Created Beat '%s' for calendar event '%s'",
                    new_beat.title,
                    base_event_id,
                )

        except Exception as e:
            logger.warning("Failed to create Beat for event '%s': %s", event.title, e)

    return new_beat_ids


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
