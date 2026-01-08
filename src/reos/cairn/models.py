"""CAIRN data models.

These models define the metadata overlays CAIRN adds to the Play architecture,
as well as the contact knowledge graph and activity tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class KanbanState(Enum):
    """Kanban states for items."""

    ACTIVE = "active"           # Currently working on
    BACKLOG = "backlog"         # To do, not started
    WAITING = "waiting"         # Blocked, waiting on someone/something
    SOMEDAY = "someday"         # Maybe later, low priority
    DONE = "done"               # Completed


class ActivityType(Enum):
    """Types of activity tracked."""

    VIEWED = "viewed"           # User looked at item
    EDITED = "edited"           # User modified item
    COMPLETED = "completed"     # Item marked complete
    CREATED = "created"         # Item created
    PRIORITY_SET = "priority_set"  # Priority was set/changed
    STATE_CHANGED = "state_changed"  # Kanban state changed
    DEFERRED = "deferred"       # Item deferred to later
    LINKED = "linked"           # Contact linked to item


class ContactRelationship(Enum):
    """Relationship types between contacts and Play entities."""

    OWNER = "owner"             # Owns/leads this project
    COLLABORATOR = "collaborator"  # Working on this together
    STAKEHOLDER = "stakeholder"    # Has interest, not actively working
    WAITING_ON = "waiting_on"      # We're waiting on them for something


@dataclass
class CairnMetadata:
    """Activity tracking overlay for Play entities (Acts/Scenes/Beats)."""

    entity_type: str            # "act", "scene", "beat"
    entity_id: str

    # Activity tracking
    last_touched: datetime | None = None
    touch_count: int = 0
    created_at: datetime | None = None

    # Kanban state
    kanban_state: KanbanState = KanbanState.BACKLOG
    waiting_on: str | None = None       # Who/what we're waiting for
    waiting_since: datetime | None = None

    # Priority (user-set, not computed)
    # None = needs priority decision
    priority: int | None = None         # 1-5, None = needs decision
    priority_set_at: datetime | None = None
    priority_reason: str | None = None

    # Time awareness
    due_date: datetime | None = None
    start_date: datetime | None = None
    defer_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "last_touched": self.last_touched.isoformat() if self.last_touched else None,
            "touch_count": self.touch_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "kanban_state": self.kanban_state.value,
            "waiting_on": self.waiting_on,
            "waiting_since": self.waiting_since.isoformat() if self.waiting_since else None,
            "priority": self.priority,
            "priority_set_at": self.priority_set_at.isoformat() if self.priority_set_at else None,
            "priority_reason": self.priority_reason,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "defer_until": self.defer_until.isoformat() if self.defer_until else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CairnMetadata:
        """Create from dictionary."""
        def parse_dt(val: str | None) -> datetime | None:
            if val is None:
                return None
            return datetime.fromisoformat(val)

        return cls(
            entity_type=data["entity_type"],
            entity_id=data["entity_id"],
            last_touched=parse_dt(data.get("last_touched")),
            touch_count=data.get("touch_count", 0),
            created_at=parse_dt(data.get("created_at")),
            kanban_state=KanbanState(data.get("kanban_state", "backlog")),
            waiting_on=data.get("waiting_on"),
            waiting_since=parse_dt(data.get("waiting_since")),
            priority=data.get("priority"),
            priority_set_at=parse_dt(data.get("priority_set_at")),
            priority_reason=data.get("priority_reason"),
            due_date=parse_dt(data.get("due_date")),
            start_date=parse_dt(data.get("start_date")),
            defer_until=parse_dt(data.get("defer_until")),
        )

    @property
    def needs_priority(self) -> bool:
        """Check if this item needs a priority decision."""
        # Active items without priority need one
        if self.kanban_state == KanbanState.ACTIVE and self.priority is None:
            return True
        # Items with due dates soon need priority
        if self.due_date and self.priority is None:
            days_until = (self.due_date - datetime.now()).days
            if days_until <= 7:
                return True
        return False

    @property
    def is_stale(self) -> bool:
        """Check if item hasn't been touched in a while."""
        if self.last_touched is None:
            return True
        days_since = (datetime.now() - self.last_touched).days
        # Different thresholds for different states
        if self.kanban_state == KanbanState.ACTIVE:
            return days_since > 3  # Active items stale after 3 days
        elif self.kanban_state == KanbanState.BACKLOG:
            return days_since > 14  # Backlog items after 2 weeks
        return False


@dataclass
class ActivityLogEntry:
    """A single activity log entry."""

    log_id: str
    entity_type: str
    entity_id: str
    activity_type: ActivityType
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "log_id": self.log_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "activity_type": self.activity_type.value,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


@dataclass
class ContactLink:
    """Link between a contact and a Play entity."""

    link_id: str
    contact_id: str             # Thunderbird contact ID
    entity_type: str            # "act", "scene", "beat"
    entity_id: str
    relationship: ContactRelationship
    created_at: datetime
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "link_id": self.link_id,
            "contact_id": self.contact_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "relationship": self.relationship.value,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContactLink:
        """Create from dictionary."""
        return cls(
            link_id=data["link_id"],
            contact_id=data["contact_id"],
            entity_type=data["entity_type"],
            entity_id=data["entity_id"],
            relationship=ContactRelationship(data["relationship"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            notes=data.get("notes"),
        )


@dataclass
class PriorityQueueItem:
    """An item that needs a priority decision from the user."""

    queue_id: str
    entity_type: str
    entity_id: str
    reason: str                 # Why priority decision is needed
    surfaced_at: datetime
    resolved_at: datetime | None = None
    resolution: str | None = None  # What the user decided


@dataclass
class SurfaceContext:
    """Context for surfacing decisions."""

    # Time context
    current_time: datetime = field(default_factory=datetime.now)
    is_morning: bool = False    # 6am - 12pm
    is_evening: bool = False    # 6pm - 10pm
    is_weekend: bool = False

    # User state (optional hints)
    energy_level: str | None = None  # "high", "low", "medium"
    time_available: int | None = None  # Minutes available

    # Filters
    include_stale: bool = True
    include_someday: bool = False
    max_items: int = 5

    # Context (optional)
    current_act_id: str | None = None  # Focus on specific Act


@dataclass
class SurfacedItem:
    """An item surfaced by CAIRN for attention."""

    entity_type: str
    entity_id: str
    title: str
    reason: str                 # Why this is surfaced
    urgency: str                # "critical", "high", "medium", "low"
    metadata: CairnMetadata | None = None

    # Additional context
    due_in_days: int | None = None
    waiting_days: int | None = None
    stale_days: int | None = None
    linked_contacts: list[str] = field(default_factory=list)
    linked_events: list[str] = field(default_factory=list)
