"""CAIRN surfacing algorithms.

Surfaces items that need attention based on priority, time, and context.
Designed to be helpful without being coercive or guilt-inducing.

Enhanced with optional coherence verification from the CAIRN Coherence Kernel.
When enabled, items are scored against the user's identity model from The Play.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from reos.cairn.models import (
    CairnMetadata,
    KanbanState,
    SurfaceContext,
    SurfacedItem,
)
from reos.play_fs import find_scene_location

if TYPE_CHECKING:
    from reos.cairn.store import CairnStore
    from reos.cairn.thunderbird import ThunderbirdBridge
    from reos.play.play_fs import PlayStore
    from reos.providers import LLMProvider


class CairnSurfacer:
    """Surfaces items that need attention.

    The surfacing algorithm is designed around these principles:
    - Surface the next thing, not everything
    - Priority is user-driven; we surface when decisions are needed
    - Context matters (time of day, available time, energy)
    - Never guilt-trip ("you haven't touched this in 30 days")
    - Instead: "X is waiting when you're ready"

    Optional coherence verification:
    - When llm is provided, items can be scored against user identity
    - Use enable_coherence=True in surface_next() to activate
    - Items with low coherence scores may be filtered or reranked
    """

    def __init__(
        self,
        cairn_store: CairnStore,
        play_store: PlayStore | None = None,
        thunderbird: ThunderbirdBridge | None = None,
        llm: "LLMProvider | None" = None,
        play_path: Path | None = None,
    ):
        """Initialize the surfacer.

        Args:
            cairn_store: CAIRN SQLite store for metadata.
            play_store: Optional Play store for entity details.
            thunderbird: Optional Thunderbird bridge for calendar.
            llm: Optional LLM provider for coherence verification.
            play_path: Path to The Play root (for identity extraction).
        """
        self.store = cairn_store
        self.play = play_store
        self.thunderbird = thunderbird
        self.llm = llm
        self.play_path = play_path
        self._identity_model = None  # Cached identity model
        self._identity_model_time = None  # When it was built

    def surface_next(
        self,
        context: SurfaceContext | None = None,
        enable_coherence: bool = False,
        coherence_threshold: float = -0.5,
    ) -> list[SurfacedItem]:
        """Surface the next thing(s) that need attention.

        This is the main entry point for "what should I work on?"

        Args:
            context: Optional context for personalization.
            enable_coherence: If True and LLM available, score items against identity.
            coherence_threshold: Items below this score may be filtered (default -0.5).

        Returns:
            List of surfaced items, ordered by urgency (and coherence if enabled).
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

        # Optional: Score candidates for coherence with user identity
        if enable_coherence and self.llm:
            candidates = self._score_coherence(candidates, coherence_threshold)

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

    def surface_attention(
        self, hours: int = 168, limit: int = 10
    ) -> list[SurfacedItem]:
        """Surface items that need attention - Scenes with upcoming calendar events.

        This is designed for the "What Needs My Attention" section at app startup.
        It shows Scenes linked to calendar events (not raw calendar events).
        For recurring events, shows the next occurrence.

        Args:
            hours: Look ahead this many hours for events (default 168 = 7 days).
            limit: Maximum items to return.

        Returns:
            List of items needing attention, primarily Scenes with calendar links.
        """
        candidates: list[SurfacedItem] = []

        # 1. Sync calendar events to Scenes (creates Scenes for new events)
        if self.thunderbird:
            try:
                from reos.cairn.scene_calendar_sync import sync_calendar_to_scenes
                new_scene_ids = sync_calendar_to_scenes(self.thunderbird, self.store, hours)
                if new_scene_ids:
                    logger.debug("Created %d new Scenes from calendar events", len(new_scene_ids))
            except Exception as e:
                logger.warning("Failed to sync calendar to scenes: %s", e)

        # 2. Get Scenes with upcoming calendar events from play_db (canonical source)
        from reos.play_db import get_scenes_with_upcoming_events
        scenes_with_events = get_scenes_with_upcoming_events(hours=hours)

        for scene_info in scenes_with_events:
            # Determine the effective time (next occurrence for recurring, else start)
            effective_time_str = scene_info.get("next_occurrence") or scene_info.get("start")
            if effective_time_str:
                if isinstance(effective_time_str, str):
                    effective_time = datetime.fromisoformat(effective_time_str)
                else:
                    effective_time = effective_time_str
            else:
                continue  # Skip if no time info

            time_until = effective_time - datetime.now()
            minutes = int(time_until.total_seconds() / 60)

            if minutes < 0:
                reason = "Happening now"
                urgency = "critical"
            elif minutes < 60:
                reason = f"In {minutes} minutes"
                urgency = "high"
            elif minutes < 120:
                hours_until = minutes // 60
                mins_remainder = minutes % 60
                reason = f"In {hours_until}h {mins_remainder}m"
                urgency = "high"
            else:
                # Format as "Jan 14, Wednesday at 9:30 AM"
                event_date = effective_time.strftime("%b %d, %A")  # "Jan 14, Wednesday"
                event_time = effective_time.strftime("%I:%M %p").lstrip("0")  # "9:30 AM"
                reason = f"{event_date} at {event_time}"
                urgency = "medium"

            # Check if recurring
            is_recurring = scene_info.get("recurrence_rule") is not None
            recurrence_freq = None
            if is_recurring and scene_info.get("recurrence_rule"):
                rrule = scene_info["recurrence_rule"]
                if "FREQ=" in rrule:
                    recurrence_freq = rrule.split("FREQ=")[1].split(";")[0]

            # Parse calendar times
            cal_start = None
            cal_end = None
            if scene_info.get("start"):
                cal_start = datetime.fromisoformat(scene_info["start"]) if isinstance(scene_info["start"], str) else scene_info["start"]
            if scene_info.get("end"):
                cal_end = datetime.fromisoformat(scene_info["end"]) if isinstance(scene_info["end"], str) else scene_info["end"]

            # Parse next occurrence
            next_occ = None
            if scene_info.get("next_occurrence"):
                next_occ = datetime.fromisoformat(scene_info["next_occurrence"]) if isinstance(scene_info["next_occurrence"], str) else scene_info["next_occurrence"]

            # Get scene location from CANONICAL source (play_fs), not stale CAIRN cache
            scene_location = find_scene_location(scene_info["scene_id"])
            act_id = scene_location["act_id"] if scene_location else None

            candidates.append(
                SurfacedItem(
                    entity_type="scene",
                    entity_id=scene_info["scene_id"],
                    title=scene_info.get("title", "Untitled"),
                    reason=reason,
                    urgency=urgency,
                    calendar_start=cal_start,
                    calendar_end=cal_end,
                    is_recurring=is_recurring,
                    recurrence_frequency=recurrence_freq,
                    next_occurrence=next_occ,
                    act_id=act_id,
                )
            )

        # 3. Add any overdue items (secondary)
        candidates.extend(self._get_overdue_items()[:3])

        # 4. Items due today
        candidates.extend(self._get_due_today()[:3])

        return self._rank_and_dedupe(candidates, max_items=limit)

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
    # Coherence Verification
    # =========================================================================

    def _get_identity_model(self):
        """Get or build the identity model.

        Caches the identity model for 5 minutes to avoid rebuilding
        on every surfacing call.
        """
        from reos.cairn.identity import build_identity_model

        now = datetime.now()

        # Check if cache is still valid (5 minute TTL)
        if (
            self._identity_model is not None
            and self._identity_model_time is not None
            and (now - self._identity_model_time).seconds < 300
        ):
            return self._identity_model

        # Build fresh identity model
        try:
            self._identity_model = build_identity_model(store=self.store)
            self._identity_model_time = now
            logger.debug("Built identity model with %d facets", len(self._identity_model.facets))
        except Exception as e:
            logger.warning("Failed to build identity model: %s", e)
            self._identity_model = None

        return self._identity_model

    def _score_coherence(
        self,
        candidates: list[SurfacedItem],
        threshold: float = -0.5,
    ) -> list[SurfacedItem]:
        """Score surfaced items for coherence with user identity.

        Args:
            candidates: List of surfaced items to score.
            threshold: Items below this score are filtered out.

        Returns:
            Scored and filtered list of items.
        """
        from reos.cairn.coherence import AttentionDemand, CoherenceVerifier

        identity = self._get_identity_model()
        if identity is None:
            logger.debug("No identity model available, skipping coherence scoring")
            return candidates

        verifier = CoherenceVerifier(identity, llm=self.llm, max_depth=2)
        scored: list[SurfacedItem] = []

        for item in candidates:
            try:
                # Create attention demand from surfaced item
                demand = AttentionDemand.create(
                    source=f"{item.entity_type}:{item.entity_id}",
                    content=f"{item.title}: {item.reason}",
                    urgency=self._urgency_to_int(item.urgency),
                )

                # Verify coherence
                result = verifier.verify(demand)

                # Update item with coherence info
                item.coherence_score = result.overall_score
                item.coherence_recommendation = result.recommendation

                # Filter items below threshold (unless critical urgency)
                if result.overall_score >= threshold or item.urgency == "critical":
                    scored.append(item)
                else:
                    logger.debug(
                        "Filtered item %s (score=%.2f, threshold=%.2f)",
                        item.title[:30], result.overall_score, threshold
                    )

            except Exception as e:
                logger.warning("Coherence check failed for %s: %s", item.entity_id, e)
                # Keep item if coherence check fails
                scored.append(item)

        # Re-sort by coherence score as secondary criterion
        scored.sort(key=lambda x: (
            self._urgency_order(x.urgency),
            -(x.coherence_score or 0.0),
        ))

        return scored

    def _urgency_to_int(self, urgency: str) -> int:
        """Convert urgency string to int (0-10)."""
        mapping = {"critical": 10, "high": 7, "medium": 5, "low": 3}
        return mapping.get(urgency, 5)

    def _urgency_order(self, urgency: str) -> int:
        """Get sort order for urgency (lower = more urgent)."""
        mapping = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return mapping.get(urgency, 4)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_entity_title(self, entity_type: str, entity_id: str) -> str:
        """Get the title of a Play entity.

        Args:
            entity_type: Type of entity (act, scene).
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
            # Backward compatibility for old "beat" entity type
            elif entity_type == "beat":
                scene = self.play.get_scene(entity_id)
                return scene.title if scene else entity_id
        except Exception as e:
            logger.debug("Failed to get entity title for %s/%s: %s", entity_type, entity_id, e)

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


def get_integration_context(store_path: Path | None = None) -> str:
    """Get context about integrations for LLM system prompts.

    This enables CAIRN to naturally discuss integration status in conversation.

    Args:
        store_path: Path to the CAIRN store. If None, returns generic message.

    Returns:
        Context string describing integration state.
    """
    if store_path is None:
        return "Integration status unknown."

    try:
        from reos.cairn.store import CairnStore

        store = CairnStore(store_path)
        thunderbird_state = store.get_integration_state("thunderbird")

        if thunderbird_state is None or thunderbird_state["state"] == "not_configured":
            return (
                "Thunderbird is not connected. "
                "The user can say 'connect Thunderbird' or 'set up calendar' to configure it. "
                "This will enable calendar events and contact awareness."
            )

        if thunderbird_state["state"] == "declined":
            return (
                "The user has declined Thunderbird integration. "
                "Do not suggest connecting it unless they ask about calendar or contacts. "
                "They can re-enable it in Settings > Integrations."
            )

        if thunderbird_state["state"] == "active":
            config = thunderbird_state.get("config", {})
            active_profiles = config.get("active_profiles", []) if config else []
            profile_count = len(active_profiles)
            return (
                f"Thunderbird is connected with {profile_count} profile(s). "
                "Calendar events and contacts are available for surfacing. "
                "You can reference the user's upcoming events and linked contacts."
            )

        return "Integration status unknown."

    except Exception as e:
        logger.debug("Failed to get integration context: %s", e)
        return "Integration status unavailable."


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
