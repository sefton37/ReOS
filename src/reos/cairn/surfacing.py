"""CAIRN surfacing algorithms.

Surfaces items that need attention based on priority, time, and context.
Designed to be helpful without being coercive or guilt-inducing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from reos.cairn.models import (
    CairnMetadata,
    KanbanState,
    SurfaceContext,
    SurfacedItem,
)

if TYPE_CHECKING:
    from reos.cairn.store import CairnStore
    from reos.cairn.thunderbird import ThunderbirdBridge
    from reos.play.play_fs import PlayStore


class CairnSurfacer:
    """Surfaces items that need attention.

    The surfacing algorithm is designed around these principles:
    - Surface the next thing, not everything
    - Priority is user-driven; we surface when decisions are needed
    - Context matters (time of day, available time, energy)
    - Never guilt-trip ("you haven't touched this in 30 days")
    - Instead: "X is waiting when you're ready"
    """

    def __init__(
        self,
        cairn_store: CairnStore,
        play_store: PlayStore | None = None,
        thunderbird: ThunderbirdBridge | None = None,
    ):
        """Initialize the surfacer.

        Args:
            cairn_store: CAIRN SQLite store for metadata.
            play_store: Optional Play store for entity details.
            thunderbird: Optional Thunderbird bridge for calendar.
        """
        self.store = cairn_store
        self.play = play_store
        self.thunderbird = thunderbird

    def surface_next(
        self, context: SurfaceContext | None = None
    ) -> list[SurfacedItem]:
        """Surface the next thing(s) that need attention.

        This is the main entry point for "what should I work on?"

        Args:
            context: Optional context for personalization.

        Returns:
            List of surfaced items, ordered by urgency.
        """
        if context is None:
            context = SurfaceContext()

        candidates: list[SurfacedItem] = []

        # 1. Overdue items (highest priority)
        candidates.extend(self._get_overdue_items())

        # 2. Due today
        candidates.extend(self._get_due_today())

        # 3. Calendar events in next 2 hours
        if self.thunderbird:
            candidates.extend(self._get_upcoming_events(hours=2))

        # 4. Active items by priority
        candidates.extend(self._get_active_by_priority())

        # 5. Items needing priority decision (max 3)
        candidates.extend(self._get_needs_priority(limit=3))

        # 6. Stale items (gentle nudge)
        if context.include_stale:
            candidates.extend(self._get_stale_items(days=7, limit=2))

        # Dedupe and rank
        return self._rank_and_dedupe(candidates, max_items=context.max_items)

    def surface_today(
        self, context: SurfaceContext | None = None
    ) -> list[SurfacedItem]:
        """Surface everything relevant for today.

        Includes calendar events and due items.

        Args:
            context: Optional context.

        Returns:
            List of today's items.
        """
        candidates: list[SurfacedItem] = []

        # Calendar events for today
        if self.thunderbird:
            candidates.extend(self._get_today_events())

        # Items due today
        candidates.extend(self._get_due_today())

        # Overdue items
        candidates.extend(self._get_overdue_items())

        return self._rank_and_dedupe(candidates, max_items=20)

    def surface_stale(
        self, days: int = 7, limit: int = 10
    ) -> list[SurfacedItem]:
        """Surface items that haven't been touched in a while.

        Phrased gently: "These are waiting when you're ready"

        Args:
            days: How many days defines "stale".
            limit: Maximum items to return.

        Returns:
            List of stale items.
        """
        return self._get_stale_items(days=days, limit=limit)

    def surface_needs_priority(self, limit: int = 10) -> list[SurfacedItem]:
        """Surface items that need a priority decision.

        Args:
            limit: Maximum items to return.

        Returns:
            List of items needing priority.
        """
        return self._get_needs_priority(limit=limit)

    def surface_waiting(
        self, min_days: int | None = None, limit: int = 10
    ) -> list[SurfacedItem]:
        """Surface items in WAITING state.

        Args:
            min_days: Only show items waiting at least this long.
            limit: Maximum items to return.

        Returns:
            List of waiting items.
        """
        items = self.store.get_waiting_items(max_days=min_days)
        now = datetime.now()

        surfaced = []
        for item in items[:limit]:
            waiting_days = None
            if item.waiting_since:
                waiting_days = (now - item.waiting_since).days

            reason = f"Waiting on {item.waiting_on or 'something'}"
            if waiting_days:
                reason += f" ({waiting_days} days)"

            surfaced.append(
                SurfacedItem(
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    title=self._get_entity_title(item.entity_type, item.entity_id),
                    reason=reason,
                    urgency="medium" if (waiting_days or 0) > 7 else "low",
                    metadata=item,
                    waiting_days=waiting_days,
                )
            )

        return surfaced

    def surface_for_contact(
        self, contact_id: str, limit: int = 10
    ) -> list[SurfacedItem]:
        """Surface everything related to a specific contact.

        Args:
            contact_id: Thunderbird contact ID.
            limit: Maximum items to return.

        Returns:
            List of items linked to the contact.
        """
        links = self.store.get_contact_links(contact_id=contact_id)

        surfaced = []
        for link in links[:limit]:
            metadata = self.store.get_metadata(link.entity_type, link.entity_id)

            surfaced.append(
                SurfacedItem(
                    entity_type=link.entity_type,
                    entity_id=link.entity_id,
                    title=self._get_entity_title(link.entity_type, link.entity_id),
                    reason=f"Related ({link.relationship.value})",
                    urgency="low",
                    metadata=metadata,
                    linked_contacts=[contact_id],
                )
            )

        return surfaced

    # =========================================================================
    # Internal surfacing methods
    # =========================================================================

    def _get_overdue_items(self) -> list[SurfacedItem]:
        """Get items past their due date."""
        items = self.store.list_metadata(is_overdue=True)
        now = datetime.now()

        surfaced = []
        for item in items:
            if item.due_date:
                days_overdue = (now - item.due_date).days
                surfaced.append(
                    SurfacedItem(
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        title=self._get_entity_title(item.entity_type, item.entity_id),
                        reason=f"Overdue by {days_overdue} day(s)",
                        urgency="critical",
                        metadata=item,
                        due_in_days=-days_overdue,
                    )
                )

        return surfaced

    def _get_due_today(self) -> list[SurfacedItem]:
        """Get items due today."""
        today = datetime.now().date()
        items = self.store.list_metadata()

        surfaced = []
        for item in items:
            if item.due_date and item.due_date.date() == today:
                surfaced.append(
                    SurfacedItem(
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        title=self._get_entity_title(item.entity_type, item.entity_id),
                        reason="Due today",
                        urgency="high",
                        metadata=item,
                        due_in_days=0,
                    )
                )

        return surfaced

    def _get_upcoming_events(self, hours: int = 2) -> list[SurfacedItem]:
        """Get calendar events in the next N hours."""
        if not self.thunderbird:
            return []

        events = self.thunderbird.get_upcoming_events(hours=hours)

        surfaced = []
        for event in events:
            time_until = event.start - datetime.now()
            minutes = int(time_until.total_seconds() / 60)

            if minutes < 0:
                reason = "Now"
                urgency = "critical"
            elif minutes < 30:
                reason = f"In {minutes} minutes"
                urgency = "high"
            else:
                reason = f"In {minutes // 60}h {minutes % 60}m"
                urgency = "medium"

            surfaced.append(
                SurfacedItem(
                    entity_type="calendar_event",
                    entity_id=event.id,
                    title=event.title,
                    reason=reason,
                    urgency=urgency,
                )
            )

        return surfaced

    def _get_today_events(self) -> list[SurfacedItem]:
        """Get all calendar events for today."""
        if not self.thunderbird:
            return []

        events = self.thunderbird.get_today_events()

        surfaced = []
        for event in events:
            surfaced.append(
                SurfacedItem(
                    entity_type="calendar_event",
                    entity_id=event.id,
                    title=event.title,
                    reason=f"{event.start.strftime('%H:%M')} - {event.end.strftime('%H:%M')}",
                    urgency="medium",
                )
            )

        return surfaced

    def _get_active_by_priority(self) -> list[SurfacedItem]:
        """Get active items ordered by priority."""
        items = self.store.list_metadata(kanban_state=KanbanState.ACTIVE)

        # Sort by priority (higher = more important, None = last)
        items.sort(key=lambda x: (x.priority is None, -(x.priority or 0)))

        surfaced = []
        for item in items:
            priority_str = f"P{item.priority}" if item.priority else "No priority"
            surfaced.append(
                SurfacedItem(
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    title=self._get_entity_title(item.entity_type, item.entity_id),
                    reason=f"Active ({priority_str})",
                    urgency="medium" if item.priority and item.priority >= 4 else "low",
                    metadata=item,
                )
            )

        return surfaced

    def _get_needs_priority(self, limit: int = 10) -> list[SurfacedItem]:
        """Get items that need a priority decision."""
        items = self.store.get_items_needing_priority()

        surfaced = []
        for item in items[:limit]:
            surfaced.append(
                SurfacedItem(
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    title=self._get_entity_title(item.entity_type, item.entity_id),
                    reason="Needs priority decision",
                    urgency="low",
                    metadata=item,
                )
            )

        return surfaced

    def _get_stale_items(self, days: int = 7, limit: int = 10) -> list[SurfacedItem]:
        """Get items not touched in a while.

        Phrased gently to avoid guilt-tripping.
        """
        items = self.store.list_metadata(is_stale=True)
        now = datetime.now()

        surfaced = []
        for item in items[:limit]:
            stale_days = None
            if item.last_touched:
                stale_days = (now - item.last_touched).days

            # Gentle phrasing - never guilt-trip
            reason = "Waiting when you're ready"
            if stale_days and stale_days > 30:
                reason = "Patiently waiting"

            surfaced.append(
                SurfacedItem(
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    title=self._get_entity_title(item.entity_type, item.entity_id),
                    reason=reason,
                    urgency="low",
                    metadata=item,
                    stale_days=stale_days,
                )
            )

        return surfaced

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_entity_title(self, entity_type: str, entity_id: str) -> str:
        """Get the title of a Play entity.

        Args:
            entity_type: Type of entity (act, scene, beat).
            entity_id: ID of the entity.

        Returns:
            Entity title, or ID if not found.
        """
        if not self.play:
            return entity_id

        try:
            if entity_type == "act":
                act = self.play.get_act(entity_id)
                return act.title if act else entity_id
            elif entity_type == "scene":
                scene = self.play.get_scene(entity_id)
                return scene.title if scene else entity_id
            elif entity_type == "beat":
                beat = self.play.get_beat(entity_id)
                return beat.content[:50] if beat else entity_id
        except Exception:
            pass

        return entity_id

    def _rank_and_dedupe(
        self, candidates: list[SurfacedItem], max_items: int = 5
    ) -> list[SurfacedItem]:
        """Rank and deduplicate surfaced items.

        Args:
            candidates: List of candidate items.
            max_items: Maximum items to return.

        Returns:
            Ranked and deduped list.
        """
        # Dedupe by (entity_type, entity_id)
        seen: set[tuple[str, str]] = set()
        deduped: list[SurfacedItem] = []

        for item in candidates:
            key = (item.entity_type, item.entity_id)
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        # Rank by urgency
        urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        deduped.sort(key=lambda x: urgency_order.get(x.urgency, 4))

        return deduped[:max_items]


def create_surface_context(
    current_act_id: str | None = None,
    time_available: int | None = None,
    energy_level: str | None = None,
) -> SurfaceContext:
    """Create a surface context with time awareness.

    Args:
        current_act_id: Focus on a specific Act.
        time_available: Minutes available for work.
        energy_level: "high", "medium", or "low".

    Returns:
        Configured SurfaceContext.
    """
    now = datetime.now()
    hour = now.hour

    return SurfaceContext(
        current_time=now,
        is_morning=6 <= hour < 12,
        is_evening=18 <= hour < 22,
        is_weekend=now.weekday() >= 5,
        energy_level=energy_level,
        time_available=time_available,
        current_act_id=current_act_id,
    )
