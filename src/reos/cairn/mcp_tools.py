"""CAIRN MCP tools.

MCP tool definitions for CAIRN - the Attention Minder.

These tools provide:
1. Knowledge Base CRUD - List, get, touch, set priority, kanban state
2. Surfacing - Get what needs attention next
3. Contact Management - Link contacts to entities
4. Thunderbird Integration - Calendar and contact access
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from reos.cairn.models import (
    ActivityType,
    ContactRelationship,
    KanbanState,
)
from reos.cairn.store import CairnStore
from reos.cairn.surfacing import CairnSurfacer, create_surface_context
from reos.cairn.thunderbird import ThunderbirdBridge


class CairnToolError(RuntimeError):
    """Error from a CAIRN tool."""

    def __init__(self, code: str, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Tool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: dict[str, Any]


def list_tools() -> list[Tool]:
    """List all CAIRN tools."""
    return [
        # =====================================================================
        # Knowledge Base CRUD
        # =====================================================================
        Tool(
            name="cairn_list_items",
            description=(
                "List items in the knowledge base with optional filters. "
                "Returns items with their CAIRN metadata (kanban state, priority, etc.)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                        "description": "Filter by entity type",
                    },
                    "kanban_state": {
                        "type": "string",
                        "enum": ["active", "backlog", "waiting", "someday", "done"],
                        "description": "Filter by kanban state",
                    },
                    "has_priority": {
                        "type": "boolean",
                        "description": "true = only with priority, false = only without",
                    },
                    "is_overdue": {
                        "type": "boolean",
                        "description": "Only return overdue items",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max items to return (default: 50)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_get_item",
            description="Get full details for a single item including CAIRN metadata.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
        Tool(
            name="cairn_touch_item",
            description=(
                "Mark an item as touched (user interacted with it). "
                "Updates last_touched timestamp and increments touch_count."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "activity_type": {
                        "type": "string",
                        "enum": ["viewed", "edited", "completed", "created"],
                        "description": "Type of activity (default: viewed)",
                    },
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
        Tool(
            name="cairn_set_priority",
            description=(
                "Set priority for an item. Priority is 1-5 (higher = more important). "
                "Priority is user-driven - CAIRN surfaces when decisions are needed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "priority": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Priority level (1-5, higher = more important)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for the priority",
                    },
                },
                "required": ["entity_type", "entity_id", "priority"],
            },
        ),
        Tool(
            name="cairn_set_kanban_state",
            description=(
                "Move an item between kanban states: active, backlog, waiting, someday, done."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["active", "backlog", "waiting", "someday", "done"],
                    },
                    "waiting_on": {
                        "type": "string",
                        "description": "Who/what we're waiting on (for 'waiting' state)",
                    },
                },
                "required": ["entity_type", "entity_id", "state"],
            },
        ),
        Tool(
            name="cairn_set_due_date",
            description="Set or clear the due date for an item.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "due_date": {
                        "type": "string",
                        "description": "Due date in ISO format (YYYY-MM-DD), or null to clear",
                    },
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
        Tool(
            name="cairn_defer_item",
            description="Defer an item until a later date. Moves to 'someday' if active.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "defer_until": {
                        "type": "string",
                        "description": "Date to defer until (ISO format YYYY-MM-DD)",
                    },
                },
                "required": ["entity_type", "entity_id", "defer_until"],
            },
        ),
        # =====================================================================
        # Surfacing & Prioritization
        # =====================================================================
        Tool(
            name="cairn_surface_next",
            description=(
                "Get the 'next thing' that needs attention. "
                "Considers priority, due dates, calendar, and staleness."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "current_act_id": {
                        "type": "string",
                        "description": "Focus on a specific Act",
                    },
                    "include_stale": {
                        "type": "boolean",
                        "description": "Include stale items (default: true)",
                    },
                    "max_items": {
                        "type": "number",
                        "description": "Max items to surface (default: 5)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_surface_today",
            description="Get everything relevant for today (calendar + due items).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_surface_stale",
            description=(
                "Get items not touched in a while. "
                "Phrased gently: 'These are waiting when you're ready'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "number",
                        "description": "Days without touch to consider stale (default: 7)",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max items (default: 10)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_surface_needs_priority",
            description="Get items that need a priority decision.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Max items (default: 10)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_surface_waiting",
            description="Get items in 'waiting' state.",
            input_schema={
                "type": "object",
                "properties": {
                    "min_days": {
                        "type": "number",
                        "description": "Only show items waiting at least this many days",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max items (default: 10)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_surface_attention",
            description=(
                "Get items that need attention - primarily upcoming calendar events. "
                "Designed for the 'What Needs My Attention' section at app startup. "
                "Shows the next 7 days by default."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "number",
                        "description": "Look ahead this many hours (default: 168 = 7 days)",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max items (default: 10)",
                    },
                },
            },
        ),
        # =====================================================================
        # Contact Knowledge Graph
        # =====================================================================
        Tool(
            name="cairn_link_contact",
            description="Link a Thunderbird contact to a Play entity.",
            input_schema={
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "string",
                        "description": "Thunderbird contact ID",
                    },
                    "entity_type": {
                        "type": "string",
                        "enum": ["act", "scene", "beat"],
                    },
                    "entity_id": {"type": "string"},
                    "relationship": {
                        "type": "string",
                        "enum": ["owner", "collaborator", "stakeholder", "waiting_on"],
                        "description": "Relationship type",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about the link",
                    },
                },
                "required": ["contact_id", "entity_type", "entity_id", "relationship"],
            },
        ),
        Tool(
            name="cairn_unlink_contact",
            description="Remove a contact link.",
            input_schema={
                "type": "object",
                "properties": {
                    "link_id": {"type": "string", "description": "The link ID to remove"},
                },
                "required": ["link_id"],
            },
        ),
        Tool(
            name="cairn_surface_contact",
            description="Get everything related to a specific contact.",
            input_schema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "string", "description": "Thunderbird contact ID"},
                    "limit": {"type": "number", "description": "Max items (default: 10)"},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="cairn_get_contact_links",
            description="Get contact links for an entity or contact.",
            input_schema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "string"},
                    "entity_type": {"type": "string", "enum": ["act", "scene", "beat"]},
                    "entity_id": {"type": "string"},
                },
            },
        ),
        # =====================================================================
        # Thunderbird Integration
        # =====================================================================
        Tool(
            name="cairn_thunderbird_status",
            description="Get Thunderbird integration status (detected paths, availability).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_search_contacts",
            description="Search Thunderbird contacts by name, email, or organization.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "number", "description": "Max results (default: 20)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cairn_get_calendar",
            description="Get calendar events for a date range.",
            input_schema={
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "Start date (ISO format, default: now)",
                    },
                    "end": {
                        "type": "string",
                        "description": "End date (ISO format, default: 30 days from start)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_get_upcoming_events",
            description="Get calendar events in the next N hours.",
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "Hours to look ahead (default: 24)"},
                    "limit": {"type": "number", "description": "Max events (default: 10)"},
                },
            },
        ),
        Tool(
            name="cairn_get_todos",
            description=(
                "Get todos (Beats) from The Play with CAIRN metadata. "
                "Beats are tasks within Scenes within Acts. "
                "Returns priority, due dates, kanban state, and linked calendar events."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "include_completed": {
                        "type": "boolean",
                        "description": "Include completed todos (default: false)",
                    },
                    "kanban_state": {
                        "type": "string",
                        "enum": ["active", "backlog", "waiting", "someday", "done"],
                        "description": "Filter by kanban state (optional)",
                    },
                },
            },
        ),
        # =====================================================================
        # Beat-Calendar Linking
        # =====================================================================
        Tool(
            name="cairn_link_beat_to_event",
            description=(
                "Link a Beat (todo) to a calendar event. "
                "A Beat can have multiple calendar events linked to it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "beat_id": {"type": "string", "description": "The Beat ID to link"},
                    "calendar_event_id": {"type": "string", "description": "The calendar event ID"},
                    "notes": {"type": "string", "description": "Optional notes about this link"},
                },
                "required": ["beat_id", "calendar_event_id"],
            },
        ),
        Tool(
            name="cairn_unlink_beat_from_event",
            description="Remove link between a Beat and a calendar event.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_id": {"type": "string"},
                    "calendar_event_id": {"type": "string"},
                },
                "required": ["beat_id", "calendar_event_id"],
            },
        ),
        Tool(
            name="cairn_get_beat_events",
            description="Get all calendar events linked to a Beat.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_id": {"type": "string"},
                },
                "required": ["beat_id"],
            },
        ),
        # =====================================================================
        # Analytics
        # =====================================================================
        Tool(
            name="cairn_activity_summary",
            description="Get activity summary for an entity or overall.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": ["act", "scene", "beat"]},
                    "entity_id": {"type": "string"},
                    "days": {"type": "number", "description": "Days of history (default: 7)"},
                },
            },
        ),
        # =====================================================================
        # Coherence Verification (Identity-based filtering)
        # =====================================================================
        Tool(
            name="cairn_check_coherence",
            description=(
                "Check if an attention demand coheres with the user's identity. "
                "Returns a score (-1.0 to 1.0) and recommendation (accept/defer/reject)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "demand_text": {
                        "type": "string",
                        "description": "The attention demand to check",
                    },
                    "source": {
                        "type": "string",
                        "description": "Where this demand came from (e.g., 'email', 'thought')",
                    },
                    "urgency": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 10,
                        "description": "Claimed urgency (0-10, default: 5)",
                    },
                },
                "required": ["demand_text"],
            },
        ),
        Tool(
            name="cairn_add_anti_pattern",
            description=(
                "Add an anti-pattern to automatically reject matching attention demands. "
                "Anti-patterns are topics or sources the user wants filtered out."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The pattern to reject (e.g., 'spam', 'marketing')",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for adding this pattern",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="cairn_remove_anti_pattern",
            description="Remove an anti-pattern from the rejection list.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The pattern to remove",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="cairn_list_anti_patterns",
            description="List all current anti-patterns that are used to filter attention demands.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_get_identity_summary",
            description=(
                "Get a summary of the user's identity model as understood by CAIRN. "
                "Includes core identity, facets, and anti-patterns."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "include_facets": {
                        "type": "boolean",
                        "description": "Include identity facets (default: true)",
                    },
                    "max_facets": {
                        "type": "number",
                        "description": "Max facets to include (default: 10)",
                    },
                },
            },
        ),
    ]


class CairnToolHandler:
    """Handler for CAIRN MCP tools."""

    def __init__(
        self,
        store: CairnStore,
        play_store: Any | None = None,
    ):
        """Initialize the handler.

        Args:
            store: CAIRN SQLite store.
            play_store: Optional Play store for entity titles.
        """
        self.store = store
        self.play_store = play_store
        self._thunderbird: ThunderbirdBridge | None = None
        self._surfacer: CairnSurfacer | None = None

    @property
    def thunderbird(self) -> ThunderbirdBridge | None:
        """Get Thunderbird bridge (lazy init)."""
        if self._thunderbird is None:
            self._thunderbird = ThunderbirdBridge.auto_detect()
        return self._thunderbird

    @property
    def surfacer(self) -> CairnSurfacer:
        """Get surfacer (lazy init)."""
        if self._surfacer is None:
            self._surfacer = CairnSurfacer(
                cairn_store=self.store,
                play_store=self.play_store,
                thunderbird=self.thunderbird,
            )
        return self._surfacer

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> Any:
        """Call a CAIRN tool.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result.

        Raises:
            CairnToolError: If tool fails or is not found.
        """
        args = arguments or {}

        # =====================================================================
        # Knowledge Base CRUD
        # =====================================================================
        if name == "cairn_list_items":
            return self._list_items(args)

        if name == "cairn_get_item":
            return self._get_item(args)

        if name == "cairn_touch_item":
            return self._touch_item(args)

        if name == "cairn_set_priority":
            return self._set_priority(args)

        if name == "cairn_set_kanban_state":
            return self._set_kanban_state(args)

        if name == "cairn_set_due_date":
            return self._set_due_date(args)

        if name == "cairn_defer_item":
            return self._defer_item(args)

        # =====================================================================
        # Surfacing
        # =====================================================================
        if name == "cairn_surface_next":
            return self._surface_next(args)

        if name == "cairn_surface_today":
            return self._surface_today()

        if name == "cairn_surface_stale":
            return self._surface_stale(args)

        if name == "cairn_surface_needs_priority":
            return self._surface_needs_priority(args)

        if name == "cairn_surface_waiting":
            return self._surface_waiting(args)

        if name == "cairn_surface_attention":
            return self._surface_attention(args)

        # =====================================================================
        # Contact Management
        # =====================================================================
        if name == "cairn_link_contact":
            return self._link_contact(args)

        if name == "cairn_unlink_contact":
            return self._unlink_contact(args)

        if name == "cairn_surface_contact":
            return self._surface_contact(args)

        if name == "cairn_get_contact_links":
            return self._get_contact_links(args)

        # =====================================================================
        # Thunderbird
        # =====================================================================
        if name == "cairn_thunderbird_status":
            return self._thunderbird_status()

        if name == "cairn_search_contacts":
            return self._search_contacts(args)

        if name == "cairn_get_calendar":
            return self._get_calendar(args)

        if name == "cairn_get_upcoming_events":
            return self._get_upcoming_events(args)

        if name == "cairn_get_todos":
            return self._get_todos(args)

        # =====================================================================
        # Beat-Calendar Linking
        # =====================================================================
        if name == "cairn_link_beat_to_event":
            return self._link_beat_to_event(args)

        if name == "cairn_unlink_beat_from_event":
            return self._unlink_beat_from_event(args)

        if name == "cairn_get_beat_events":
            return self._get_beat_events(args)

        # =====================================================================
        # Analytics
        # =====================================================================
        if name == "cairn_activity_summary":
            return self._activity_summary(args)

        # =====================================================================
        # Coherence Verification
        # =====================================================================
        if name == "cairn_check_coherence":
            return self._check_coherence(args)

        if name == "cairn_add_anti_pattern":
            return self._add_anti_pattern(args)

        if name == "cairn_remove_anti_pattern":
            return self._remove_anti_pattern(args)

        if name == "cairn_list_anti_patterns":
            return self._list_anti_patterns()

        if name == "cairn_get_identity_summary":
            return self._get_identity_summary(args)

        raise CairnToolError(
            code="unknown_tool",
            message=f"Unknown CAIRN tool: {name}",
        )

    # =========================================================================
    # Tool implementations
    # =========================================================================

    def _list_items(self, args: dict[str, Any]) -> dict[str, Any]:
        """List items with filters."""
        entity_type = args.get("entity_type")
        kanban_state_str = args.get("kanban_state")
        has_priority = args.get("has_priority")
        is_overdue = args.get("is_overdue", False)
        limit = args.get("limit", 50)

        kanban_state = None
        if kanban_state_str:
            kanban_state = KanbanState(kanban_state_str)

        items = self.store.list_metadata(
            entity_type=entity_type,
            kanban_state=kanban_state,
            has_priority=has_priority,
            is_overdue=is_overdue,
            limit=limit,
        )

        return {
            "count": len(items),
            "items": [item.to_dict() for item in items],
        }

    def _get_item(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get a single item."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]

        metadata = self.store.get_metadata(entity_type, entity_id)
        if metadata is None:
            return {"found": False, "entity_type": entity_type, "entity_id": entity_id}

        # Get contact links
        links = self.store.get_contacts_for_entity(entity_type, entity_id)

        return {
            "found": True,
            "metadata": metadata.to_dict(),
            "contact_links": [link.to_dict() for link in links],
            "needs_priority": metadata.needs_priority,
            "is_stale": metadata.is_stale,
        }

    def _touch_item(self, args: dict[str, Any]) -> dict[str, Any]:
        """Touch an item."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]
        activity_str = args.get("activity_type", "viewed")
        activity_type = ActivityType(activity_str)

        metadata = self.store.touch(entity_type, entity_id, activity_type)

        return {
            "touched": True,
            "touch_count": metadata.touch_count,
            "last_touched": metadata.last_touched.isoformat() if metadata.last_touched else None,
        }

    def _set_priority(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set priority."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]
        priority = int(args["priority"])
        reason = args.get("reason")

        metadata = self.store.set_priority(entity_type, entity_id, priority, reason)

        return {
            "set": True,
            "priority": metadata.priority,
            "priority_reason": metadata.priority_reason,
        }

    def _set_kanban_state(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set kanban state."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]
        state = KanbanState(args["state"])
        waiting_on = args.get("waiting_on")

        metadata = self.store.set_kanban_state(entity_type, entity_id, state, waiting_on)

        return {
            "set": True,
            "kanban_state": metadata.kanban_state.value,
            "waiting_on": metadata.waiting_on,
        }

    def _set_due_date(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set due date."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]
        due_date_str = args.get("due_date")

        due_date = None
        if due_date_str:
            due_date = datetime.fromisoformat(due_date_str)

        metadata = self.store.set_due_date(entity_type, entity_id, due_date)

        return {
            "set": True,
            "due_date": metadata.due_date.isoformat() if metadata.due_date else None,
        }

    def _defer_item(self, args: dict[str, Any]) -> dict[str, Any]:
        """Defer an item."""
        entity_type = args["entity_type"]
        entity_id = args["entity_id"]
        defer_until = datetime.fromisoformat(args["defer_until"])

        metadata = self.store.defer_until(entity_type, entity_id, defer_until)

        return {
            "deferred": True,
            "defer_until": metadata.defer_until.isoformat() if metadata.defer_until else None,
            "kanban_state": metadata.kanban_state.value,
        }

    def _surface_next(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface next items."""
        context = create_surface_context(
            current_act_id=args.get("current_act_id"),
        )
        context.include_stale = args.get("include_stale", True)
        context.max_items = args.get("max_items", 5)

        items = self.surfacer.surface_next(context)

        return {
            "count": len(items),
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "reason": item.reason,
                    "urgency": item.urgency,
                }
                for item in items
            ],
        }

    def _surface_today(self) -> dict[str, Any]:
        """Surface today's items."""
        items = self.surfacer.surface_today()

        return {
            "count": len(items),
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "reason": item.reason,
                    "urgency": item.urgency,
                }
                for item in items
            ],
        }

    def _surface_stale(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface stale items."""
        days = args.get("days", 7)
        limit = args.get("limit", 10)

        items = self.surfacer.surface_stale(days=days, limit=limit)

        return {
            "count": len(items),
            "message": "These are waiting when you're ready",
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "stale_days": item.stale_days,
                }
                for item in items
            ],
        }

    def _surface_needs_priority(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface items needing priority."""
        limit = args.get("limit", 10)
        items = self.surfacer.surface_needs_priority(limit=limit)

        return {
            "count": len(items),
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                }
                for item in items
            ],
        }

    def _surface_waiting(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface waiting items."""
        min_days = args.get("min_days")
        limit = args.get("limit", 10)

        items = self.surfacer.surface_waiting(min_days=min_days, limit=limit)

        return {
            "count": len(items),
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "waiting_days": item.waiting_days,
                    "metadata": item.metadata.to_dict() if item.metadata else None,
                }
                for item in items
            ],
        }

    def _surface_attention(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface items needing attention - primarily calendar events (next 7 days)."""
        hours = args.get("hours", 168)  # 7 days
        limit = args.get("limit", 10)

        items = self.surfacer.surface_attention(hours=hours, limit=limit)

        return {
            "count": len(items),
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "reason": item.reason,
                    "urgency": item.urgency,
                    "calendar_start": item.calendar_start.isoformat() if item.calendar_start else None,
                    "calendar_end": item.calendar_end.isoformat() if item.calendar_end else None,
                    "metadata": item.metadata.to_dict() if item.metadata else None,
                }
                for item in items
            ],
        }

    def _link_contact(self, args: dict[str, Any]) -> dict[str, Any]:
        """Link a contact."""
        link = self.store.link_contact(
            contact_id=args["contact_id"],
            entity_type=args["entity_type"],
            entity_id=args["entity_id"],
            relationship=ContactRelationship(args["relationship"]),
            notes=args.get("notes"),
        )

        return {
            "linked": True,
            "link_id": link.link_id,
        }

    def _unlink_contact(self, args: dict[str, Any]) -> dict[str, Any]:
        """Unlink a contact."""
        removed = self.store.unlink_contact(args["link_id"])
        return {"unlinked": removed}

    def _surface_contact(self, args: dict[str, Any]) -> dict[str, Any]:
        """Surface items for a contact."""
        contact_id = args["contact_id"]
        limit = args.get("limit", 10)

        items = self.surfacer.surface_for_contact(contact_id, limit=limit)

        return {
            "count": len(items),
            "contact_id": contact_id,
            "items": [
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "title": item.title,
                    "reason": item.reason,
                }
                for item in items
            ],
        }

    def _get_contact_links(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get contact links."""
        links = self.store.get_contact_links(
            contact_id=args.get("contact_id"),
            entity_type=args.get("entity_type"),
            entity_id=args.get("entity_id"),
        )

        return {
            "count": len(links),
            "links": [link.to_dict() for link in links],
        }

    def _thunderbird_status(self) -> dict[str, Any]:
        """Get Thunderbird status."""
        if self.thunderbird is None:
            return {
                "available": False,
                "message": "Thunderbird profile not detected",
            }

        return {
            "available": True,
            **self.thunderbird.get_status(),
        }

    def _search_contacts(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search contacts."""
        if self.thunderbird is None:
            return {"available": False, "contacts": []}

        query = args["query"]
        limit = args.get("limit", 20)

        contacts = self.thunderbird.search_contacts(query, limit=limit)

        return {
            "count": len(contacts),
            "contacts": [
                {
                    "id": c.id,
                    "display_name": c.display_name,
                    "email": c.email,
                    "phone": c.phone,
                    "organization": c.organization,
                }
                for c in contacts
            ],
        }

    def _get_calendar(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get calendar events."""
        if self.thunderbird is None:
            return {"available": False, "events": []}

        start = None
        end = None
        if args.get("start"):
            start = datetime.fromisoformat(args["start"])
        if args.get("end"):
            end = datetime.fromisoformat(args["end"])

        events = self.thunderbird.list_events(start=start, end=end)

        return {
            "count": len(events),
            "events": [
                {
                    "id": e.id,
                    "title": e.title,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                    "location": e.location,
                    "all_day": e.all_day,
                }
                for e in events
            ],
        }

    def _get_upcoming_events(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get upcoming events."""
        if self.thunderbird is None:
            return {"available": False, "events": []}

        hours = args.get("hours", 24)
        limit = args.get("limit", 10)

        events = self.thunderbird.get_upcoming_events(hours=hours, limit=limit)

        return {
            "count": len(events),
            "events": [
                {
                    "id": e.id,
                    "title": e.title,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                    "location": e.location,
                }
                for e in events
            ],
        }

    def _get_todos(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get todos (Beats) from The Play with CAIRN metadata.

        Beats are the todos in ReOS - they come from The Play hierarchy.
        This returns Beats with their CAIRN attention metadata and linked calendar events.
        """
        from reos import play_fs

        include_completed = args.get("include_completed", False)
        kanban_filter = args.get("kanban_state")  # Optional: "active", "backlog", etc.

        todos = []

        # Get all Acts
        acts = play_fs.list_acts()
        for act in acts:
            # Get all Scenes in this Act
            scenes = play_fs.list_scenes(act_id=act.act_id)
            for scene in scenes:
                # Get all Beats in this Scene
                beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)
                for beat in beats:
                    # Get CAIRN metadata for this Beat
                    metadata = self.store.get_metadata("beat", beat.beat_id)

                    # Filter by kanban state
                    if kanban_filter:
                        if metadata is None or metadata.kanban_state.value != kanban_filter:
                            continue

                    # Filter completed if requested
                    if not include_completed:
                        if beat.status.lower() in ("done", "completed", "complete"):
                            continue
                        if metadata and metadata.kanban_state.value == "done":
                            continue

                    # Get linked calendar events
                    calendar_events = self.store.get_calendar_events_for_beat(beat.beat_id)

                    todo_item = {
                        "id": beat.beat_id,
                        "title": beat.title,
                        "status": beat.status,
                        "notes": beat.notes,
                        "link": beat.link,
                        # Context
                        "act_id": act.act_id,
                        "act_title": act.title,
                        "scene_id": scene.scene_id,
                        "scene_title": scene.title,
                    }

                    # Add CAIRN metadata if available
                    if metadata:
                        todo_item.update({
                            "kanban_state": metadata.kanban_state.value,
                            "priority": metadata.priority,
                            "due_date": metadata.due_date.isoformat() if metadata.due_date else None,
                            "waiting_on": metadata.waiting_on,
                            "last_touched": metadata.last_touched.isoformat() if metadata.last_touched else None,
                        })
                    else:
                        todo_item.update({
                            "kanban_state": "backlog",
                            "priority": None,
                            "due_date": None,
                            "waiting_on": None,
                            "last_touched": None,
                        })

                    # Add linked calendar events
                    if calendar_events:
                        todo_item["calendar_events"] = calendar_events

                    todos.append(todo_item)

        # Sort by priority (high first), then by due date
        def sort_key(t):
            priority = t.get("priority") or 0
            due = t.get("due_date") or "9999-12-31"
            return (-priority, due)

        todos.sort(key=sort_key)

        return {
            "count": len(todos),
            "todos": todos,
        }

    def _link_beat_to_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """Link a Beat to a calendar event."""
        beat_id = args.get("beat_id")
        calendar_event_id = args.get("calendar_event_id")
        notes = args.get("notes")

        if not beat_id or not calendar_event_id:
            raise CairnToolError(
                code="MISSING_PARAMS",
                message="beat_id and calendar_event_id are required",
            )

        # Try to get calendar event details from Thunderbird
        event_title = None
        event_start = None
        event_end = None

        if self.thunderbird:
            # Search for the event to get its details
            events = self.thunderbird.list_events()
            for e in events:
                if e.id == calendar_event_id:
                    event_title = e.title
                    event_start = e.start
                    event_end = e.end
                    break

        link_id = self.store.link_beat_to_calendar_event(
            beat_id=beat_id,
            calendar_event_id=calendar_event_id,
            calendar_event_title=event_title,
            calendar_event_start=event_start,
            calendar_event_end=event_end,
            notes=notes,
        )

        return {
            "success": True,
            "link_id": link_id,
            "beat_id": beat_id,
            "calendar_event_id": calendar_event_id,
        }

    def _unlink_beat_from_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """Remove link between Beat and calendar event."""
        beat_id = args.get("beat_id")
        calendar_event_id = args.get("calendar_event_id")

        if not beat_id or not calendar_event_id:
            raise CairnToolError(
                code="MISSING_PARAMS",
                message="beat_id and calendar_event_id are required",
            )

        removed = self.store.unlink_beat_from_calendar_event(
            beat_id=beat_id,
            calendar_event_id=calendar_event_id,
        )

        return {
            "success": removed,
            "beat_id": beat_id,
            "calendar_event_id": calendar_event_id,
        }

    def _get_beat_events(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all calendar events linked to a Beat."""
        beat_id = args.get("beat_id")

        if not beat_id:
            raise CairnToolError(
                code="MISSING_PARAMS",
                message="beat_id is required",
            )

        events = self.store.get_calendar_events_for_beat(beat_id)

        return {
            "beat_id": beat_id,
            "count": len(events),
            "events": events,
        }

    def _activity_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get activity summary."""
        entity_type = args.get("entity_type")
        entity_id = args.get("entity_id")
        days = args.get("days", 7)

        since = datetime.now()
        from datetime import timedelta
        since = since - timedelta(days=days)

        logs = self.store.get_activity_log(
            entity_type=entity_type,
            entity_id=entity_id,
            since=since,
            limit=100,
        )

        # Summarize by activity type
        by_type: dict[str, int] = {}
        for log in logs:
            key = log.activity_type.value
            by_type[key] = by_type.get(key, 0) + 1

        return {
            "total_activities": len(logs),
            "days": days,
            "by_type": by_type,
        }

    # =========================================================================
    # Coherence Verification implementations
    # =========================================================================

    def _check_coherence(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check if an attention demand coheres with identity."""
        from reos.cairn.coherence import AttentionDemand, CoherenceVerifier
        from reos.cairn.identity import build_identity_model

        demand_text = args["demand_text"]
        source = args.get("source", "unknown")
        urgency = args.get("urgency", 5)

        try:
            # Build identity model
            identity = build_identity_model(store=self.store)

            # Create demand
            demand = AttentionDemand.create(
                source=source,
                content=demand_text,
                urgency=int(urgency),
            )

            # Verify coherence (no LLM for now - uses heuristics)
            verifier = CoherenceVerifier(identity, llm=None, max_depth=2)
            result = verifier.verify(demand)

            return {
                "coherence_score": round(result.overall_score, 3),
                "recommendation": result.recommendation,
                "checks_performed": len(result.checks),
                "trace": result.trace,
                "demand_id": result.demand.id,
            }

        except Exception as e:
            return {
                "error": str(e),
                "coherence_score": 0.0,
                "recommendation": "defer",
            }

    def _add_anti_pattern(self, args: dict[str, Any]) -> dict[str, Any]:
        """Add an anti-pattern."""
        from reos.cairn.identity import add_anti_pattern

        pattern = args["pattern"]
        reason = args.get("reason")

        try:
            patterns = add_anti_pattern(pattern, reason)
            return {
                "added": True,
                "pattern": pattern,
                "total_patterns": len(patterns),
            }
        except ValueError as e:
            return {
                "added": False,
                "error": str(e),
            }

    def _remove_anti_pattern(self, args: dict[str, Any]) -> dict[str, Any]:
        """Remove an anti-pattern."""
        from reos.cairn.identity import remove_anti_pattern

        pattern = args["pattern"]
        patterns = remove_anti_pattern(pattern)

        return {
            "removed": True,
            "pattern": pattern,
            "total_patterns": len(patterns),
        }

    def _list_anti_patterns(self) -> dict[str, Any]:
        """List all anti-patterns."""
        from reos.cairn.identity import load_anti_patterns

        patterns = load_anti_patterns()

        return {
            "count": len(patterns),
            "patterns": patterns,
        }

    def _get_identity_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get identity model summary."""
        from reos.cairn.identity import build_identity_model, get_identity_hash

        include_facets = args.get("include_facets", True)
        max_facets = args.get("max_facets", 10)

        try:
            identity = build_identity_model(store=self.store, max_facets=max_facets)

            result: dict[str, Any] = {
                "identity_hash": get_identity_hash(identity),
                "core_preview": identity.core[:500] + "..." if len(identity.core) > 500 else identity.core,
                "facet_count": len(identity.facets),
                "anti_pattern_count": len(identity.anti_patterns),
                "anti_patterns": identity.anti_patterns,
                "built_at": identity.built_at.isoformat(),
            }

            if include_facets:
                result["facets"] = [
                    {
                        "name": f.name,
                        "source": f.source,
                        "preview": f.content[:200] + "..." if len(f.content) > 200 else f.content,
                        "weight": f.weight,
                    }
                    for f in identity.facets[:max_facets]
                ]

            return result

        except Exception as e:
            return {
                "error": str(e),
                "identity_hash": None,
            }
