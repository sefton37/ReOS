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
    PendingConfirmation,
    TOOLS_REQUIRING_CONFIRMATION,
    UndoContext,
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
        # Beat Organization
        # =====================================================================
        Tool(
            name="cairn_move_beat_to_act",
            description=(
                "Move a Beat to a different Act. Use this when the user wants to "
                "reorganize their Beats, e.g., 'Career Coaching should be in the Career act'. "
                "Uses fuzzy matching for beat and act names."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {
                        "type": "string",
                        "description": "Name/title of the Beat to move (fuzzy matched)",
                    },
                    "target_act_name": {
                        "type": "string",
                        "description": "Name of the Act to move the Beat to (fuzzy matched)",
                    },
                    "target_scene_name": {
                        "type": "string",
                        "description": "Optional: Scene within the Act (defaults to Stage Direction)",
                    },
                },
                "required": ["beat_name", "target_act_name"],
            },
        ),
        Tool(
            name="cairn_list_beats",
            description=(
                "List all Beats with their current Act and Scene locations. "
                "Useful for seeing what Beats exist and where they are organized."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Optional: Filter to Beats in a specific Act (fuzzy matched)",
                    },
                },
            },
        ),
        # =====================================================================
        # The Play CRUD - Acts
        # =====================================================================
        Tool(
            name="cairn_list_acts",
            description=(
                "List all Acts in The Play. Shows each Act's title, notes, "
                "and whether it's the active Act."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_create_act",
            description=(
                "Create a new Act in The Play. An Act represents a major life domain "
                "or project (e.g., 'Career', 'Health', 'Family')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The Act title (e.g., 'Career', 'Health')",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about this Act",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="cairn_update_act",
            description="Update an Act's title, notes, or color.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act to update (fuzzy matched)",
                    },
                    "new_title": {
                        "type": "string",
                        "description": "New title for the Act",
                    },
                    "new_notes": {
                        "type": "string",
                        "description": "New notes for the Act",
                    },
                    "new_color": {
                        "type": "string",
                        "description": "New color for the Act (hex code like '#8b5cf6' or color name)",
                    },
                },
                "required": ["act_name"],
            },
        ),
        Tool(
            name="cairn_delete_act",
            description=(
                "Delete an Act and all its Scenes and Beats. "
                "WARNING: This is permanent. The 'Your Story' Act cannot be deleted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act to delete (fuzzy matched)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                    },
                },
                "required": ["act_name", "confirm"],
            },
        ),
        Tool(
            name="cairn_set_active_act",
            description="Set which Act is currently active/in-focus.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act to make active (fuzzy matched)",
                    },
                },
                "required": ["act_name"],
            },
        ),
        # =====================================================================
        # The Play CRUD - Scenes
        # =====================================================================
        Tool(
            name="cairn_list_scenes",
            description="List all Scenes in an Act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act (fuzzy matched)",
                    },
                },
                "required": ["act_name"],
            },
        ),
        Tool(
            name="cairn_create_scene",
            description=(
                "Create a new Scene within an Act. A Scene represents a specific "
                "area or phase within an Act (e.g., 'Job Search', 'Interviews')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act to add Scene to (fuzzy matched)",
                    },
                    "title": {
                        "type": "string",
                        "description": "The Scene title",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Optional: The Scene's purpose/intent",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about this Scene",
                    },
                },
                "required": ["act_name", "title"],
            },
        ),
        Tool(
            name="cairn_update_scene",
            description=(
                "Update a Scene's properties including title, notes, stage, or move it to a different Act. "
                "To move a scene, provide new_act_name with the target Act. "
                "For moves, act_name is optional - the scene will be found by name across all Acts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act containing the Scene (fuzzy matched). Optional for move operations.",
                    },
                    "scene_name": {
                        "type": "string",
                        "description": "Name of the Scene to update (fuzzy matched)",
                    },
                    "new_title": {
                        "type": "string",
                        "description": "New title for the Scene",
                    },
                    "new_act_name": {
                        "type": "string",
                        "description": "Move scene to this Act (fuzzy matched). This updates the scene's act_id.",
                    },
                    "new_stage": {
                        "type": "string",
                        "description": "New stage: planning, in_progress, awaiting_data, or complete",
                    },
                    "new_notes": {
                        "type": "string",
                        "description": "New notes for the Scene",
                    },
                    "new_link": {
                        "type": "string",
                        "description": "New link/URL for the Scene",
                    },
                },
                "required": ["scene_name"],
            },
        ),
        Tool(
            name="cairn_delete_scene",
            description=(
                "Delete a Scene and all its Beats. "
                "WARNING: This is permanent. Stage Direction scenes cannot be deleted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act (fuzzy matched)",
                    },
                    "scene_name": {
                        "type": "string",
                        "description": "Name of the Scene to delete (fuzzy matched)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                    },
                },
                "required": ["act_name", "scene_name", "confirm"],
            },
        ),
        # =====================================================================
        # The Play CRUD - Beats
        # =====================================================================
        Tool(
            name="cairn_create_beat",
            description=(
                "Create a new Beat within a Scene. A Beat represents a specific "
                "task, event, or action item."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {
                        "type": "string",
                        "description": "Name of the Act (fuzzy matched)",
                    },
                    "scene_name": {
                        "type": "string",
                        "description": "Name of the Scene (fuzzy matched, defaults to Stage Direction)",
                    },
                    "title": {
                        "type": "string",
                        "description": "The Beat title",
                    },
                    "stage": {
                        "type": "string",
                        "enum": ["planning", "in_progress", "awaiting_data", "complete"],
                        "description": "Beat stage (default: planning)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about this Beat",
                    },
                },
                "required": ["act_name", "title"],
            },
        ),
        Tool(
            name="cairn_update_beat",
            description="Update a Beat's title, stage, or notes.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {
                        "type": "string",
                        "description": "Name of the Beat to update (fuzzy matched)",
                    },
                    "new_title": {
                        "type": "string",
                        "description": "New title for the Beat",
                    },
                    "new_stage": {
                        "type": "string",
                        "enum": ["planning", "in_progress", "awaiting_data", "complete"],
                        "description": "New stage for the Beat",
                    },
                    "new_notes": {
                        "type": "string",
                        "description": "New notes for the Beat",
                    },
                },
                "required": ["beat_name"],
            },
        ),
        Tool(
            name="cairn_delete_beat",
            description="Delete a Beat. WARNING: This is permanent.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {
                        "type": "string",
                        "description": "Name of the Beat to delete (fuzzy matched)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                    },
                },
                "required": ["beat_name", "confirm"],
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
        # =====================================================================
        # Undo
        # =====================================================================
        Tool(
            name="cairn_undo_last",
            description=(
                "Undo the last reversible action. Use this when the user wants to "
                "revert their previous action, e.g., 'undo that', 'put it back', "
                "'nevermind'. Some actions like delete cannot be undone."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional: Scope undo to a specific conversation",
                    },
                },
            },
        ),
        # =====================================================================
        # Confirmation (for irreversible actions)
        # =====================================================================
        Tool(
            name="cairn_confirm_action",
            description=(
                "Confirm a pending irreversible action. IMPORTANT: Only call this "
                "AFTER the user has explicitly said 'yes', 'confirm', 'do it', or "
                "similar approval. Never call this automatically."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "confirmation_id": {
                        "type": "string",
                        "description": "The confirmation ID shown to user (optional if only one pending)",
                    },
                },
            },
        ),
        Tool(
            name="cairn_cancel_action",
            description=(
                "Cancel a pending irreversible action. Use when user says 'no', "
                "'cancel', 'never mind', or wants to abort the pending action."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "confirmation_id": {
                        "type": "string",
                        "description": "The confirmation ID to cancel (optional if only one pending)",
                    },
                },
            },
        ),
        # =====================================================================
        # System Settings
        # =====================================================================
        Tool(
            name="cairn_set_autostart",
            description=(
                "Enable or disable Talking Rock autostart on Ubuntu login. "
                "Use when user asks to 'start automatically', 'open on boot', "
                "'launch on login', or similar requests about startup behavior."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable autostart on login, False to disable",
                    },
                },
                "required": ["enabled"],
            },
        ),
        Tool(
            name="cairn_get_autostart",
            description=(
                "Get current autostart status for Talking Rock. "
                "Use when user asks if autostart is enabled, or wants to know "
                "the current startup configuration."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
        ),
        # =====================================================================
        # Block Editor
        # =====================================================================
        Tool(
            name="cairn_create_block",
            description=(
                "Create a new block in a page. Blocks are Notion-style content units "
                "like paragraphs, headings, lists, code blocks, etc."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "paragraph", "heading_1", "heading_2", "heading_3",
                            "bulleted_list", "numbered_list", "to_do",
                            "code", "divider", "callout"
                        ],
                        "description": "Block type",
                    },
                    "act_id": {"type": "string", "description": "Act ID"},
                    "page_id": {"type": "string", "description": "Page ID (optional)"},
                    "parent_id": {"type": "string", "description": "Parent block ID for nesting (optional)"},
                    "text": {"type": "string", "description": "Plain text content"},
                    "properties": {
                        "type": "object",
                        "description": "Type-specific properties (e.g., language for code, checked for to_do)",
                    },
                },
                "required": ["type", "act_id"],
            },
        ),
        Tool(
            name="cairn_update_block",
            description="Update an existing block's content or properties.",
            input_schema={
                "type": "object",
                "properties": {
                    "block_id": {"type": "string", "description": "Block ID to update"},
                    "text": {"type": "string", "description": "New plain text content"},
                    "properties": {
                        "type": "object",
                        "description": "Properties to update (merged with existing)",
                    },
                },
                "required": ["block_id"],
            },
        ),
        Tool(
            name="cairn_search_blocks",
            description="Search for blocks containing specific text.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "act_id": {"type": "string", "description": "Limit to specific act (optional)"},
                    "page_id": {"type": "string", "description": "Limit to specific page (optional)"},
                    "limit": {"type": "number", "description": "Max results (default: 20)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cairn_get_page_content",
            description=(
                "Get all blocks for a page as readable content. "
                "Returns blocks in order with their formatting."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Page ID"},
                    "format": {
                        "type": "string",
                        "enum": ["blocks", "markdown"],
                        "description": "Output format (default: markdown)",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="cairn_create_page",
            description="Create a new page within an act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_id": {"type": "string", "description": "Act ID"},
                    "title": {"type": "string", "description": "Page title"},
                    "parent_page_id": {"type": "string", "description": "Parent page ID for nesting (optional)"},
                    "icon": {"type": "string", "description": "Page icon emoji (optional)"},
                },
                "required": ["act_id", "title"],
            },
        ),
        Tool(
            name="cairn_list_pages",
            description="List all pages in an act, optionally filtered by parent.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_id": {"type": "string", "description": "Act ID"},
                    "parent_page_id": {"type": "string", "description": "Filter to children of this page (optional)"},
                },
                "required": ["act_id"],
            },
        ),
        Tool(
            name="cairn_update_page",
            description="Update a page's title or icon.",
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Page ID to update"},
                    "title": {"type": "string", "description": "New title (optional)"},
                    "icon": {"type": "string", "description": "New icon emoji (optional)"},
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="cairn_add_scene_block",
            description="Add a scene embed block to a page. Links a scene to appear in page content.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_id": {"type": "string", "description": "Act ID"},
                    "scene_id": {"type": "string", "description": "Scene ID to embed"},
                    "page_id": {"type": "string", "description": "Page ID (optional)"},
                    "parent_id": {"type": "string", "description": "Parent block ID (optional)"},
                },
                "required": ["act_id", "scene_id"],
            },
        ),
        Tool(
            name="cairn_get_unchecked_todos",
            description="Get all unchecked to-do items in an act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_id": {"type": "string", "description": "Act ID"},
                },
                "required": ["act_id"],
            },
        ),
        Tool(
            name="cairn_get_page_tree",
            description="Get the full page tree (hierarchy) for an act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_id": {"type": "string", "description": "Act ID"},
                },
                "required": ["act_id"],
            },
        ),
        Tool(
            name="cairn_export_page_markdown",
            description="Export a page's block content as Markdown text.",
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Page ID"},
                },
                "required": ["page_id"],
            },
        ),
    ]


class CairnToolHandler:
    """Handler for CAIRN MCP tools."""

    def __init__(
        self,
        store: CairnStore,
        play_store: Any | None = None,
        llm: Any | None = None,
    ):
        """Initialize the handler.

        Args:
            store: CAIRN SQLite store.
            play_store: Optional Play store for entity titles.
            llm: LLM provider for entity resolution (uses cheap local inference).
        """
        self.store = store
        self.play_store = play_store
        self._llm = llm
        self._thunderbird: ThunderbirdBridge | None = None
        self._surfacer: CairnSurfacer | None = None

    def set_llm(self, llm: Any):
        """Set the LLM provider for entity resolution."""
        self._llm = llm

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
        # Beat Organization
        # =====================================================================
        if name == "cairn_move_beat_to_act":
            return self._move_beat_to_act(args)

        if name == "cairn_list_beats":
            return self._list_beats(args)

        # =====================================================================
        # The Play CRUD - Acts
        # =====================================================================
        if name == "cairn_list_acts":
            return self._list_acts()

        if name == "cairn_create_act":
            return self._create_act(args)

        if name == "cairn_update_act":
            return self._update_act(args)

        if name == "cairn_delete_act":
            return self._delete_act(args)

        if name == "cairn_set_active_act":
            return self._set_active_act(args)

        # =====================================================================
        # The Play CRUD - Scenes
        # =====================================================================
        if name == "cairn_list_scenes":
            return self._list_scenes(args)

        if name == "cairn_create_scene":
            return self._create_scene(args)

        if name == "cairn_update_scene":
            return self._update_scene(args)

        if name == "cairn_delete_scene":
            return self._delete_scene(args)

        # =====================================================================
        # The Play CRUD - Beats
        # =====================================================================
        if name == "cairn_create_beat":
            return self._create_beat(args)

        if name == "cairn_update_beat":
            return self._update_beat(args)

        if name == "cairn_delete_beat":
            return self._delete_beat(args)

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

        # =====================================================================
        # Undo
        # =====================================================================
        if name == "cairn_undo_last":
            return self._undo_last(args)

        # =====================================================================
        # Confirmation (for irreversible actions)
        # =====================================================================
        if name == "cairn_confirm_action":
            return self._confirm_action(args)

        if name == "cairn_cancel_action":
            return self._cancel_action(args)

        # =====================================================================
        # System Settings
        # =====================================================================
        if name == "cairn_set_autostart":
            return self._set_autostart(args)

        if name == "cairn_get_autostart":
            return self._get_autostart()

        # =====================================================================
        # Block Editor
        # =====================================================================
        if name == "cairn_create_block":
            return self._create_block(args)

        if name == "cairn_update_block":
            return self._update_block(args)

        if name == "cairn_search_blocks":
            return self._search_blocks(args)

        if name == "cairn_get_page_content":
            return self._get_page_content(args)

        if name == "cairn_create_page":
            return self._create_page(args)

        if name == "cairn_list_pages":
            return self._list_pages(args)

        if name == "cairn_update_page":
            return self._update_page(args)

        if name == "cairn_add_scene_block":
            return self._add_scene_block(args)

        if name == "cairn_get_unchecked_todos":
            return self._get_unchecked_todos(args)

        if name == "cairn_get_page_tree":
            return self._get_page_tree(args)

        if name == "cairn_export_page_markdown":
            return self._export_page_markdown(args)

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

        # Get old value for undo context
        old_metadata = self.store.get_metadata(entity_type, entity_id)
        old_priority = old_metadata.priority if old_metadata else None
        old_reason = old_metadata.priority_reason if old_metadata else None

        metadata = self.store.set_priority(entity_type, entity_id, priority, reason)

        # Log undo context
        undo_context = UndoContext(
            tool_name="cairn_set_priority",
            reverse_tool="cairn_set_priority",
            reverse_args={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "priority": old_priority if old_priority is not None else 3,  # Default mid priority
                "reason": old_reason,
            },
            before_state={"priority": old_priority, "reason": old_reason},
            after_state={"priority": priority, "reason": reason},
            description=f"Set priority from {old_priority} to {priority}",
            reversible=True,
        )
        self.store.log_tool_execution("cairn_set_priority", undo_context)

        return {
            "success": True,
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

        # Get old value for undo context
        old_metadata = self.store.get_metadata(entity_type, entity_id)
        old_state = old_metadata.kanban_state.value if old_metadata else "backlog"
        old_waiting_on = old_metadata.waiting_on if old_metadata else None

        metadata = self.store.set_kanban_state(entity_type, entity_id, state, waiting_on)

        # Log undo context
        undo_context = UndoContext(
            tool_name="cairn_set_kanban_state",
            reverse_tool="cairn_set_kanban_state",
            reverse_args={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "state": old_state,
                "waiting_on": old_waiting_on,
            },
            before_state={"state": old_state, "waiting_on": old_waiting_on},
            after_state={"state": state.value, "waiting_on": waiting_on},
            description=f"Changed kanban state from '{old_state}' to '{state.value}'",
            reversible=True,
        )
        self.store.log_tool_execution("cairn_set_kanban_state", undo_context)

        return {
            "success": True,
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

    # =========================================================================
    # Beat Organization
    # =========================================================================

    def _fuzzy_match(self, query: str, candidates: list[tuple[str, str]]) -> tuple[str, str, float] | None:
        """Fuzzy match a query against candidates.

        Args:
            query: The search string.
            candidates: List of (id, name) tuples to match against.

        Returns:
            (id, name, score) of best match, or None if no good match.
        """
        if not candidates:
            return None

        query_lower = query.lower().strip()

        # First try exact match
        for cid, name in candidates:
            if name.lower() == query_lower:
                return (cid, name, 1.0)

        # Then try substring match
        best_match = None
        best_score = 0.0

        for cid, name in candidates:
            name_lower = name.lower()

            # Check if query is contained in name or vice versa
            if query_lower in name_lower:
                score = len(query_lower) / len(name_lower)
                if score > best_score:
                    best_score = score
                    best_match = (cid, name, score)
            elif name_lower in query_lower:
                score = len(name_lower) / len(query_lower) * 0.8  # Penalty for partial
                if score > best_score:
                    best_score = score
                    best_match = (cid, name, score)

        # If no substring match, try word overlap
        if best_match is None or best_score < 0.3:
            query_words = set(query_lower.split())
            for cid, name in candidates:
                name_words = set(name.lower().split())
                overlap = query_words & name_words
                if overlap:
                    score = len(overlap) / max(len(query_words), len(name_words))
                    if score > best_score:
                        best_score = score
                        best_match = (cid, name, score)

        # Only return if we have a reasonable match
        if best_match and best_score >= 0.3:
            return best_match

        return None

    def _fuzzy_match_all(
        self, query: str, candidates: list[tuple[str, str]], threshold: float = 0.3
    ) -> list[tuple[str, str, float]]:
        """Find ALL candidates matching above threshold (for disambiguation).

        Args:
            query: The search string.
            candidates: List of (id, name) tuples to match against.
            threshold: Minimum score to include (default 0.3).

        Returns:
            List of (id, name, score) sorted by score descending.
        """
        if not candidates:
            return []

        query_lower = query.lower().strip()
        matches = []

        for cid, name in candidates:
            name_lower = name.lower()
            score = 0.0

            # Exact match
            if name_lower == query_lower:
                score = 1.0
            # Substring match
            elif query_lower in name_lower:
                score = len(query_lower) / len(name_lower)
            elif name_lower in query_lower:
                score = len(name_lower) / len(query_lower) * 0.8
            else:
                # Word overlap
                query_words = set(query_lower.split())
                name_words = set(name_lower.split())
                overlap = query_words & name_words
                if overlap:
                    score = len(overlap) / max(len(query_words), len(name_words))

            if score >= threshold:
                matches.append((cid, name, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches

    def _needs_disambiguation(self, matches: list[tuple[str, str, float]]) -> bool:
        """Check if multiple matches are close enough to need disambiguation.

        Returns True if there are 2+ matches with similar scores (within 0.2 of each other).
        """
        if len(matches) < 2:
            return False

        top_score = matches[0][2]
        close_matches = [m for m in matches if top_score - m[2] < 0.2]
        return len(close_matches) >= 2

    def _list_beats(self, args: dict[str, Any]) -> dict[str, Any]:
        """List all beats with their locations."""
        from reos import play_fs

        act_filter = args.get("act_name")
        acts, _ = play_fs.list_acts()

        # Build act name -> id lookup
        act_lookup = [(a.act_id, a.title) for a in acts]

        # If filtering by act, find the matching act
        target_act_ids = None
        if act_filter:
            match = self._fuzzy_match(act_filter, act_lookup)
            if match:
                target_act_ids = {match[0]}

        beats_info = []

        for act in acts:
            if target_act_ids and act.act_id not in target_act_ids:
                continue

            scenes = play_fs.list_scenes(act_id=act.act_id)

            for scene in scenes:
                beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)

                for beat in beats:
                    beats_info.append({
                        "beat_id": beat.beat_id,
                        "title": beat.title,
                        "stage": beat.stage,
                        "act_id": act.act_id,
                        "act_title": act.title,
                        "scene_id": scene.scene_id,
                        "scene_title": scene.title,
                        "has_calendar_link": beat.calendar_event_id is not None,
                    })

        return {
            "count": len(beats_info),
            "beats": beats_info,
        }

    def _move_beat_to_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Move a Beat to a different Act."""
        from reos import play_fs

        beat_name = args.get("beat_name")
        target_act_name = args.get("target_act_name")
        target_scene_name = args.get("target_scene_name")

        if not beat_name:
            raise CairnToolError("missing_param", "beat_name is required")
        if not target_act_name:
            raise CairnToolError("missing_param", "target_act_name is required")

        # Get all acts
        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        # Find target act
        target_act_match = self._fuzzy_match(target_act_name, act_lookup)
        if not target_act_match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{target_act_name}'",
                "available_acts": [a.title for a in acts],
            }

        target_act_id, target_act_title, act_match_score = target_act_match

        # Find target scene (default to Stage Direction)
        target_scenes = play_fs.list_scenes(act_id=target_act_id)
        scene_lookup = [(s.scene_id, s.title) for s in target_scenes]

        target_scene_id = None
        target_scene_title = None

        if target_scene_name:
            scene_match = self._fuzzy_match(target_scene_name, scene_lookup)
            if scene_match:
                target_scene_id, target_scene_title, _ = scene_match

        if not target_scene_id:
            # Default to Stage Direction
            stage_direction_id = play_fs._get_stage_direction_scene_id(target_act_id)
            for scene in target_scenes:
                if scene.scene_id == stage_direction_id:
                    target_scene_id = scene.scene_id
                    target_scene_title = scene.title
                    break

            # If still not found, use first scene
            if not target_scene_id and target_scenes:
                target_scene_id = target_scenes[0].scene_id
                target_scene_title = target_scenes[0].title

        if not target_scene_id:
            return {
                "success": False,
                "error": f"No scenes found in Act '{target_act_title}'",
            }

        # Find the beat by searching all acts/scenes
        found_beat = None
        source_act_id = None
        source_scene_id = None
        source_act_title = None
        source_scene_title = None

        all_beats = []
        for act in acts:
            scenes = play_fs.list_scenes(act_id=act.act_id)
            for scene in scenes:
                beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)
                for beat in beats:
                    all_beats.append((beat.beat_id, beat.title, act, scene))

        beat_lookup = [(b[0], b[1]) for b in all_beats]
        beat_match = self._fuzzy_match(beat_name, beat_lookup)

        if not beat_match:
            return {
                "success": False,
                "error": f"Could not find Beat matching '{beat_name}'",
                "available_beats": [b[1] for b in all_beats[:20]],  # Show first 20
            }

        beat_id, beat_title, _ = beat_match

        # Find the full beat info
        for bid, btitle, act, scene in all_beats:
            if bid == beat_id:
                found_beat = beat_id
                source_act_id = act.act_id
                source_scene_id = scene.scene_id
                source_act_title = act.title
                source_scene_title = scene.title
                break

        if not found_beat:
            return {
                "success": False,
                "error": f"Beat '{beat_title}' not found",
            }

        # Check if already in target location
        if source_act_id == target_act_id and source_scene_id == target_scene_id:
            return {
                "success": True,
                "message": f"Beat '{beat_title}' is already in Act '{target_act_title}'",
                "no_change": True,
            }

        # Move the beat
        try:
            result = play_fs.move_beat(
                beat_id=beat_id,
                source_act_id=source_act_id,
                source_scene_id=source_scene_id,
                target_act_id=target_act_id,
                target_scene_id=target_scene_id,
            )

            # NOTE: We no longer update beat_calendar_links.act_id/scene_id
            # Surfacing now queries play_fs directly for canonical beat location

            # Log undo context for this move operation
            undo_context = UndoContext(
                tool_name="cairn_move_beat_to_act",
                reverse_tool="cairn_move_beat_to_act",
                reverse_args={
                    "beat_name": beat_title,
                    "target_act_name": source_act_title,
                    "target_scene_name": source_scene_title,
                },
                before_state={
                    "act_id": source_act_id,
                    "act_title": source_act_title,
                    "scene_id": source_scene_id,
                    "scene_title": source_scene_title,
                },
                after_state={
                    "act_id": target_act_id,
                    "act_title": target_act_title,
                    "scene_id": target_scene_id,
                    "scene_title": target_scene_title,
                },
                description=f"Moved '{beat_title}' from '{source_act_title}' to '{target_act_title}'",
                reversible=True,
            )
            self.store.log_tool_execution("cairn_move_beat_to_act", undo_context)

            return {
                "success": True,
                "message": f"Moved '{beat_title}' from '{source_act_title}' to '{target_act_title}'",
                "beat_id": beat_id,
                "beat_title": beat_title,
                "from_act": source_act_title,
                "from_scene": source_scene_title,
                "to_act": target_act_title,
                "to_scene": target_scene_title,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # =========================================================================
    # The Play CRUD - Acts
    # =========================================================================

    def _list_acts(self) -> dict[str, Any]:
        """List all acts."""
        from reos import play_fs

        acts, active_id = play_fs.list_acts()

        return {
            "count": len(acts),
            "active_act_id": active_id,
            "acts": [
                {
                    "act_id": a.act_id,
                    "title": a.title,
                    "notes": a.notes,
                    "active": a.active,
                    "is_your_story": a.act_id == play_fs.YOUR_STORY_ACT_ID,
                    "has_repo": a.repo_path is not None,
                }
                for a in acts
            ],
        }

    def _create_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new act."""
        from reos import play_fs

        title = args.get("title")
        notes = args.get("notes", "")

        if not title:
            raise CairnToolError("missing_param", "title is required")

        try:
            acts, new_act_id = play_fs.create_act(title=title, notes=notes)
            new_act = next((a for a in acts if a.act_id == new_act_id), None)

            return {
                "success": True,
                "message": f"Created Act '{title}'",
                "act_id": new_act_id,
                "title": title,
                "active": new_act.active if new_act else False,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _update_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update an act."""
        from reos import play_fs

        act_name = args.get("act_name")
        new_title = args.get("new_title")
        new_notes = args.get("new_notes")
        new_color = args.get("new_color")

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        match = self._fuzzy_match(act_name, act_lookup)
        if not match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, old_title, _ = match

        # Get current Act for old color
        old_act = next((a for a in acts if a.act_id == act_id), None)
        old_color = old_act.color if old_act else None

        try:
            play_fs.update_act(
                act_id=act_id,
                title=new_title,
                notes=new_notes,
                color=new_color,
            )
            result = {
                "success": True,
                "message": f"Updated Act '{old_title}'",
                "act_id": act_id,
                "old_title": old_title,
                "new_title": new_title or old_title,
            }
            if new_color:
                result["new_color"] = new_color
                result["old_color"] = old_color
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete an act. Requires explicit user confirmation."""
        from reos import play_fs

        act_name = args.get("act_name")
        confirmation_id = args.get("_confirmation_id")  # Internal: set by confirm_action

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        match = self._fuzzy_match(act_name, act_lookup)
        if not match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, act_title, _ = match

        # Extra protection for Your Story
        if act_id == play_fs.YOUR_STORY_ACT_ID:
            return {
                "success": False,
                "error": "Cannot delete 'Your Story' - it is a protected system Act",
            }

        # Check if this execution has been confirmed
        if not confirmation_id:
            # Count scenes and beats to show impact
            scenes = play_fs.list_scenes(act_id=act_id)
            beat_count = sum(
                len(play_fs.list_beats(act_id=act_id, scene_id=s.scene_id))
                for s in scenes
            )

            # Create pending confirmation - user must explicitly approve
            pending = self.store.create_pending_confirmation(
                tool_name="cairn_delete_act",
                tool_args={"act_name": act_name},
                description=f"Delete Act '{act_title}' with {len(scenes)} scenes and {beat_count} beats",
                warning="This will permanently delete the Act and ALL its contents (scenes, beats).",
            )
            return {
                "success": False,
                "awaiting_confirmation": True,
                "confirmation_id": pending.confirmation_id,
                "action": f"Delete Act '{act_title}'",
                "warning": f"This will permanently delete '{act_title}' including {len(scenes)} scenes and {beat_count} beats.",
                "message": f"⚠️ Are you sure you want to delete Act '{act_title}' and all its contents? Say 'yes' or 'confirm' to proceed, or 'cancel' to abort.",
            }

        # Execution is confirmed - proceed with delete
        try:
            play_fs.delete_act(act_id=act_id)
            return {
                "success": True,
                "message": f"Deleted Act '{act_title}' and all its contents",
                "deleted_act_id": act_id,
                "deleted_act_title": act_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _set_active_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set the active act."""
        from reos import play_fs

        act_name = args.get("act_name")

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        match = self._fuzzy_match(act_name, act_lookup)
        if not match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, act_title, _ = match

        try:
            play_fs.set_active_act_id(act_id=act_id)
            return {
                "success": True,
                "message": f"Set '{act_title}' as the active Act",
                "active_act_id": act_id,
                "active_act_title": act_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # The Play CRUD - Scenes
    # =========================================================================

    def _list_scenes(self, args: dict[str, Any]) -> dict[str, Any]:
        """List scenes in an act."""
        from reos import play_fs

        act_name = args.get("act_name")

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        match = self._fuzzy_match(act_name, act_lookup)
        if not match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, act_title, _ = match
        scenes = play_fs.list_scenes(act_id=act_id)

        return {
            "act_id": act_id,
            "act_title": act_title,
            "count": len(scenes),
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "title": s.title,
                    "intent": s.intent,
                    "is_stage_direction": s.scene_id == play_fs._get_stage_direction_scene_id(act_id),
                }
                for s in scenes
            ],
        }

    def _create_scene(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new scene."""
        from reos import play_fs

        act_name = args.get("act_name")
        title = args.get("title")
        intent = args.get("intent", "")
        notes = args.get("notes", "")

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")
        if not title:
            raise CairnToolError("missing_param", "title is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        match = self._fuzzy_match(act_name, act_lookup)
        if not match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, act_title, _ = match

        try:
            scenes = play_fs.create_scene(
                act_id=act_id,
                title=title,
                intent=intent,
                notes=notes,
            )
            new_scene = scenes[-1] if scenes else None

            return {
                "success": True,
                "message": f"Created Scene '{title}' in Act '{act_title}'",
                "scene_id": new_scene.scene_id if new_scene else None,
                "scene_title": title,
                "act_id": act_id,
                "act_title": act_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _update_scene(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update a scene's fields or move it to a different Act.

        Supports updating: title, stage, notes, link, and act (via new_act_name).
        Moving a scene is just updating its act_id field.

        Uses LLM-based entity resolution - no fuzzy matching.
        When uncertain, returns clarification request for atomic verification to handle.
        """
        from reos import play_fs

        act_name = args.get("act_name")
        scene_name = args.get("scene_name")
        new_title = args.get("new_title")
        new_act_name = args.get("new_act_name")  # For moving to different Act
        new_stage = args.get("new_stage")
        new_notes = args.get("new_notes")
        new_link = args.get("new_link")
        conversation_context = args.get("_conversation_context", "")  # Injected by bridge

        if not scene_name:
            raise CairnToolError("missing_param", "scene_name is required")

        acts, _ = play_fs.list_acts()

        # Build scene list for LLM resolution
        all_scenes = []
        for act in acts:
            scenes = play_fs.list_scenes(act_id=act.act_id)
            for s in scenes:
                all_scenes.append({
                    "id": s.scene_id,
                    "scene_id": s.scene_id,
                    "title": s.title,
                    "act_id": act.act_id,
                    "act_title": act.title,
                })

        # Use LLM-based entity resolution
        if self._llm:
            from reos.atomic_ops.entity_resolver import EntityResolver
            resolver = EntityResolver(self._llm)

            # Resolve scene reference
            resolved = resolver.resolve_scene(
                user_reference=scene_name,
                available_scenes=all_scenes,
                conversation_context=conversation_context,
            )

            # If clarification needed, return it for atomic verification to handle
            if resolved.needs_clarification or resolved.confidence < 0.7:
                return {
                    "success": False,
                    "needs_clarification": True,
                    "clarification_prompt": resolved.clarification_prompt or f"Which scene did you mean by '{scene_name}'?",
                    "candidates": resolved.alternatives or [
                        {"title": s["title"], "act": s["act_title"]}
                        for s in all_scenes[:10]
                    ],
                    "confidence": resolved.confidence,
                    "reasoning": resolved.reasoning,
                }

            if not resolved.entity_id:
                return {
                    "success": False,
                    "error": f"Could not find scene matching '{scene_name}'",
                    "reasoning": resolved.reasoning,
                }

            # Found the scene
            scene_id = resolved.entity_id
            old_scene_title = resolved.entity_name

            # Find the source act
            source_act_id = None
            source_act_title = None
            for s in all_scenes:
                if s["scene_id"] == scene_id:
                    source_act_id = s["act_id"]
                    source_act_title = s["act_title"]
                    break
        else:
            # Fallback to fuzzy match if no LLM (shouldn't happen in production)
            act_lookup = [(a.act_id, a.title) for a in acts]
            source_act_id = None
            source_act_title = None

            if act_name:
                act_match = self._fuzzy_match(act_name, act_lookup)
                if not act_match:
                    return {
                        "success": False,
                        "error": f"Could not find Act matching '{act_name}'",
                        "available_acts": [a.title for a in acts],
                    }
                source_act_id, source_act_title, _ = act_match
                scenes = play_fs.list_scenes(act_id=source_act_id)
                scene_lookup = [(s.scene_id, s.title) for s in scenes]
                scene_match = self._fuzzy_match(scene_name, scene_lookup)
            else:
                flat_lookup = [(s["scene_id"], s["title"]) for s in all_scenes]
                scene_match = self._fuzzy_match(scene_name, flat_lookup)
                if scene_match:
                    for s in all_scenes:
                        if s["scene_id"] == scene_match[0]:
                            source_act_id = s["act_id"]
                            source_act_title = s["act_title"]
                            break

            if not scene_match:
                return {
                    "success": False,
                    "error": f"Could not find scene matching '{scene_name}'",
                }

            scene_id = scene_match[0]
            old_scene_title = scene_match[1]

        # Find scene - check for disambiguation when multiple matches
        if act_name:
            # Search within the specified act
            all_matches = self._fuzzy_match_all(scene_name, scene_lookup)
            if self._needs_disambiguation(all_matches):
                # Multiple close matches - ask user to clarify
                return {
                    "success": False,
                    "error": "Multiple scenes match. Please be more specific.",
                    "disambiguation_needed": True,
                    "candidates": [
                        {"title": m[1], "score": round(m[2], 2)}
                        for m in all_matches[:5]
                    ],
                    "hint": f"Did you mean one of these scenes in '{source_act_title}'?",
                }
            scene_match = all_matches[0] if all_matches else None
        else:
            # Search across all acts - build a map to get act info back
            scene_to_act = {}  # scene_id -> (act_id, act_title)
            flat_lookup = []
            for scene_id, scene_title, act_id, act_title in scene_lookup:
                flat_lookup.append((scene_id, scene_title))
                scene_to_act[scene_id] = (act_id, act_title)

            all_matches = self._fuzzy_match_all(scene_name, flat_lookup)
            if self._needs_disambiguation(all_matches):
                # Multiple close matches - ask user to clarify with act context
                candidates = []
                for m in all_matches[:5]:
                    act_info = scene_to_act.get(m[0], ("", "Unknown"))
                    candidates.append({
                        "title": m[1],
                        "act": act_info[1],
                        "score": round(m[2], 2),
                    })
                return {
                    "success": False,
                    "error": "Multiple scenes match. Please be more specific.",
                    "disambiguation_needed": True,
                    "candidates": candidates,
                    "hint": "Which scene did you mean? Please use the exact title.",
                }

            scene_match = all_matches[0] if all_matches else None
            if scene_match:
                found_scene_id = scene_match[0]
                source_act_id, source_act_title = scene_to_act[found_scene_id]

        if not scene_match:
            if act_name:
                # We were searching in a specific act
                return {
                    "success": False,
                    "error": f"Could not find Scene matching '{scene_name}' in Act '{source_act_title}'",
                    "available_scenes": [s[1] for s in scene_lookup],  # scene_lookup is [(id, title)]
                }
            else:
                # We searched all acts
                all_scenes = [s[1] for s in flat_lookup] if flat_lookup else []
                return {
                    "success": False,
                    "error": f"Could not find Scene matching '{scene_name}' in any Act",
                    "available_scenes": all_scenes[:20],  # Limit for readability
                }

        scene_id, old_scene_title, _ = scene_match
        messages = []

        try:
            # Handle move to different Act (updating act_id field)
            if new_act_name:
                target_act_match = self._fuzzy_match(new_act_name, act_lookup)
                if not target_act_match:
                    return {
                        "success": False,
                        "error": f"Could not find target Act matching '{new_act_name}'",
                        "available_acts": [a.title for a in acts],
                    }

                target_act_id, target_act_title, _ = target_act_match

                if target_act_id != source_act_id:
                    play_fs.move_scene(
                        scene_id=scene_id,
                        source_act_id=source_act_id,
                        target_act_id=target_act_id,
                    )
                    messages.append(f"Moved from '{source_act_title}' to '{target_act_title}'")
                    # Update source_act_id for subsequent update_scene call
                    source_act_id = target_act_id
                    source_act_title = target_act_title

            # Handle other field updates
            has_updates = any([new_title, new_stage, new_notes, new_link])
            if has_updates:
                play_fs.update_scene(
                    act_id=source_act_id,
                    scene_id=scene_id,
                    title=new_title,
                    stage=new_stage,
                    notes=new_notes,
                    link=new_link,
                )
                if new_title:
                    messages.append(f"Title changed to '{new_title}'")
                if new_stage:
                    messages.append(f"Stage changed to '{new_stage}'")
                if new_notes:
                    messages.append("Notes updated")
                if new_link:
                    messages.append("Link updated")

            if not messages:
                return {
                    "success": False,
                    "error": "No changes specified. Provide new_title, new_act_name, new_stage, new_notes, or new_link.",
                }

            return {
                "success": True,
                "message": f"Updated Scene '{old_scene_title}': {'; '.join(messages)}",
                "scene_id": scene_id,
                "old_title": old_scene_title,
                "new_title": new_title or old_scene_title,
                "act_id": source_act_id,
                "act_title": source_act_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_scene(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete a scene. Requires explicit user confirmation."""
        from reos import play_fs

        act_name = args.get("act_name")
        scene_name = args.get("scene_name")
        confirmation_id = args.get("_confirmation_id")  # Internal: set by confirm_action

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")
        if not scene_name:
            raise CairnToolError("missing_param", "scene_name is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        act_match = self._fuzzy_match(act_name, act_lookup)
        if not act_match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
            }

        act_id, act_title, _ = act_match
        scenes = play_fs.list_scenes(act_id=act_id)
        scene_lookup = [(s.scene_id, s.title) for s in scenes]

        scene_match = self._fuzzy_match(scene_name, scene_lookup)
        if not scene_match:
            return {
                "success": False,
                "error": f"Could not find Scene matching '{scene_name}'",
            }

        scene_id, scene_title, _ = scene_match

        # Protect Stage Direction
        if scene_id == play_fs._get_stage_direction_scene_id(act_id):
            return {
                "success": False,
                "error": "Cannot delete 'Stage Direction' - it is a protected system Scene",
            }

        # Check if this execution has been confirmed
        if not confirmation_id:
            # Count beats to show impact
            beats = play_fs.list_beats(act_id=act_id, scene_id=scene_id)

            # Create pending confirmation - user must explicitly approve
            pending = self.store.create_pending_confirmation(
                tool_name="cairn_delete_scene",
                tool_args={"act_name": act_name, "scene_name": scene_name},
                description=f"Delete Scene '{scene_title}' from Act '{act_title}' with {len(beats)} beats",
                warning="This will permanently delete the Scene and ALL its beats.",
            )
            return {
                "success": False,
                "awaiting_confirmation": True,
                "confirmation_id": pending.confirmation_id,
                "action": f"Delete Scene '{scene_title}'",
                "warning": f"This will permanently delete '{scene_title}' including {len(beats)} beats.",
                "message": f"⚠️ Are you sure you want to delete Scene '{scene_title}' and all its beats? Say 'yes' or 'confirm' to proceed, or 'cancel' to abort.",
            }

        # Execution is confirmed - proceed with delete
        try:
            play_fs.delete_scene(act_id=act_id, scene_id=scene_id)
            return {
                "success": True,
                "message": f"Deleted Scene '{scene_title}' from Act '{act_title}'",
                "deleted_scene_id": scene_id,
                "deleted_scene_title": scene_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # The Play CRUD - Beats
    # =========================================================================

    def _create_beat(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new beat."""
        from reos import play_fs

        act_name = args.get("act_name")
        scene_name = args.get("scene_name")
        title = args.get("title")
        stage = args.get("stage", "planning")
        notes = args.get("notes", "")

        if not act_name:
            raise CairnToolError("missing_param", "act_name is required")
        if not title:
            raise CairnToolError("missing_param", "title is required")

        acts, _ = play_fs.list_acts()
        act_lookup = [(a.act_id, a.title) for a in acts]

        act_match = self._fuzzy_match(act_name, act_lookup)
        if not act_match:
            return {
                "success": False,
                "error": f"Could not find Act matching '{act_name}'",
                "available_acts": [a.title for a in acts],
            }

        act_id, act_title, _ = act_match
        scenes = play_fs.list_scenes(act_id=act_id)

        # Default to Stage Direction if no scene specified
        scene_id = None
        scene_title = "Stage Direction"

        if scene_name:
            scene_lookup = [(s.scene_id, s.title) for s in scenes]
            scene_match = self._fuzzy_match(scene_name, scene_lookup)
            if scene_match:
                scene_id, scene_title, _ = scene_match

        if not scene_id:
            # Use Stage Direction
            scene_id = play_fs._get_stage_direction_scene_id(act_id)
            scene_title = "Stage Direction"

        try:
            beats = play_fs.create_beat(
                act_id=act_id,
                scene_id=scene_id,
                title=title,
                stage=stage,
                notes=notes,
            )
            new_beat = beats[-1] if beats else None

            return {
                "success": True,
                "message": f"Created Beat '{title}' in '{act_title}' / '{scene_title}'",
                "beat_id": new_beat.beat_id if new_beat else None,
                "beat_title": title,
                "act_title": act_title,
                "scene_title": scene_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _update_beat(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update a beat."""
        from reos import play_fs

        beat_name = args.get("beat_name")
        new_title = args.get("new_title")
        new_stage = args.get("new_stage")
        new_notes = args.get("new_notes")

        if not beat_name:
            raise CairnToolError("missing_param", "beat_name is required")

        # Find the beat
        acts, _ = play_fs.list_acts()
        all_beats = []

        for act in acts:
            scenes = play_fs.list_scenes(act_id=act.act_id)
            for scene in scenes:
                beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)
                for beat in beats:
                    all_beats.append((beat.beat_id, beat.title, act, scene))

        beat_lookup = [(b[0], b[1]) for b in all_beats]
        beat_match = self._fuzzy_match(beat_name, beat_lookup)

        if not beat_match:
            return {
                "success": False,
                "error": f"Could not find Beat matching '{beat_name}'",
                "available_beats": [b[1] for b in all_beats[:20]],
            }

        beat_id, old_title, _ = beat_match

        # Find act_id and scene_id for this beat
        act_id = None
        scene_id = None
        for bid, btitle, act, scene in all_beats:
            if bid == beat_id:
                act_id = act.act_id
                scene_id = scene.scene_id
                break

        try:
            play_fs.update_beat(
                act_id=act_id,
                scene_id=scene_id,
                beat_id=beat_id,
                title=new_title,
                stage=new_stage,
                notes=new_notes,
            )
            return {
                "success": True,
                "message": f"Updated Beat '{old_title}'",
                "beat_id": beat_id,
                "old_title": old_title,
                "new_title": new_title or old_title,
                "new_stage": new_stage,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_beat(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete a beat. Requires explicit user confirmation."""
        from reos import play_fs

        beat_name = args.get("beat_name")
        confirmation_id = args.get("_confirmation_id")  # Internal: set by confirm_action

        if not beat_name:
            raise CairnToolError("missing_param", "beat_name is required")

        # Find the beat first to get accurate details
        acts, _ = play_fs.list_acts()
        all_beats = []

        for act in acts:
            scenes = play_fs.list_scenes(act_id=act.act_id)
            for scene in scenes:
                beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)
                for beat in beats:
                    all_beats.append((beat.beat_id, beat.title, act, scene))

        beat_lookup = [(b[0], b[1]) for b in all_beats]
        beat_match = self._fuzzy_match(beat_name, beat_lookup)

        if not beat_match:
            return {
                "success": False,
                "error": f"Could not find Beat matching '{beat_name}'",
            }

        beat_id, beat_title, _ = beat_match

        # Find act_id and scene_id for this beat
        act_id = None
        scene_id = None
        act_title = None
        for bid, btitle, act, scene in all_beats:
            if bid == beat_id:
                act_id = act.act_id
                scene_id = scene.scene_id
                act_title = act.title
                break

        # Check if this execution has been confirmed
        if not confirmation_id:
            # Create pending confirmation - user must explicitly approve
            pending = self.store.create_pending_confirmation(
                tool_name="cairn_delete_beat",
                tool_args={"beat_name": beat_name},
                description=f"Delete Beat '{beat_title}' from Act '{act_title}'",
                warning="This action cannot be undone. The Beat and all its data will be permanently deleted.",
            )
            return {
                "success": False,
                "awaiting_confirmation": True,
                "confirmation_id": pending.confirmation_id,
                "action": f"Delete Beat '{beat_title}'",
                "warning": "This action cannot be undone. The Beat will be permanently deleted.",
                "message": f"⚠️ Are you sure you want to delete '{beat_title}'? Say 'yes' or 'confirm' to proceed, or 'cancel' to abort.",
            }

        # Execution is confirmed - proceed with delete
        try:
            play_fs.delete_beat(act_id=act_id, scene_id=scene_id, beat_id=beat_id)

            # Also remove from beat_calendar_links if present
            self.store.delete_beat_calendar_link(beat_id=beat_id)

            # Log non-reversible undo context (delete cannot be undone)
            undo_context = UndoContext(
                tool_name="cairn_delete_beat",
                reverse_tool=None,
                reverse_args={},
                before_state={
                    "beat_id": beat_id,
                    "beat_title": beat_title,
                    "act_title": act_title,
                },
                after_state={"deleted": True},
                description=f"Deleted Beat '{beat_title}' from Act '{act_title}'",
                reversible=False,
                not_reversible_reason="Delete operations cannot be undone - the data is gone",
            )
            self.store.log_tool_execution("cairn_delete_beat", undo_context)

            return {
                "success": True,
                "message": f"Deleted Beat '{beat_title}' from Act '{act_title}'",
                "deleted_beat_id": beat_id,
                "deleted_beat_title": beat_title,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Undo Implementation
    # =========================================================================

    def _undo_last(self, args: dict[str, Any]) -> dict[str, Any]:
        """Undo the last reversible action.

        Retrieves the most recent reversible action from activity_log and
        executes the reverse operation.
        """
        conversation_id = args.get("conversation_id")

        # Get the last undoable action
        result = self.store.get_last_undoable_action(conversation_id)

        if result is None:
            return {
                "success": False,
                "message": "Nothing to undo - no recent reversible actions found.",
                "no_action": True,
            }

        log_id, undo_context = result

        # Check if reversible
        if not undo_context.reversible:
            reason = undo_context.not_reversible_reason or "This action cannot be undone"
            return {
                "success": False,
                "message": f"Cannot undo: {reason}",
                "action_description": undo_context.description,
            }

        # Execute the reverse operation
        reverse_tool = undo_context.reverse_tool
        reverse_args = undo_context.reverse_args

        if not reverse_tool:
            return {
                "success": False,
                "message": "Cannot undo: no reverse operation defined",
                "action_description": undo_context.description,
            }

        try:
            # Call the reverse tool
            reverse_result = self._execute_reverse_tool(reverse_tool, reverse_args)

            if reverse_result.get("success", False):
                # Mark the original action as undone (prevents double-undo)
                self.store.mark_undo_executed(log_id)

                return {
                    "success": True,
                    "message": f"Undone: {undo_context.description}",
                    "original_action": undo_context.description,
                    "reverse_action": reverse_result.get("message", "Action reversed"),
                    "before_state": undo_context.before_state,
                    "restored_state": undo_context.after_state,
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to undo: {reverse_result.get('error', 'Unknown error')}",
                    "action_description": undo_context.description,
                    "details": reverse_result,
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"Error during undo: {str(e)}",
                "action_description": undo_context.description,
            }

    def _execute_reverse_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a reverse tool operation.

        This is a dispatcher that calls the appropriate internal method
        for the reverse operation.
        """
        # Map tool names to methods
        tool_methods = {
            "cairn_move_beat_to_act": self._move_beat_to_act,
            "cairn_update_act": self._update_act,
            "cairn_update_scene": self._update_scene,
            "cairn_update_beat": self._update_beat,
            "cairn_set_priority": self._set_priority,
            "cairn_set_kanban_state": self._set_kanban_state,
            "cairn_delete_act": self._delete_act,  # For undoing create
            "cairn_delete_scene": self._delete_scene,  # For undoing create
            "cairn_delete_beat": self._delete_beat,  # For undoing create
        }

        method = tool_methods.get(tool_name)
        if method:
            return method(args)

        raise CairnToolError(
            code="unknown_reverse_tool",
            message=f"No handler for reverse tool: {tool_name}",
        )

    # =========================================================================
    # Confirmation Handlers (for irreversible actions)
    # =========================================================================

    def _confirm_action(self, args: dict[str, Any]) -> dict[str, Any]:
        """Confirm a pending irreversible action and execute it.

        IMPORTANT: This should only be called AFTER the user has explicitly
        said 'yes', 'confirm', 'do it', or similar approval.
        """
        confirmation_id = args.get("confirmation_id")

        # Get pending confirmation (by ID or most recent)
        if confirmation_id:
            pending = self.store.get_pending_confirmation(confirmation_id)
        else:
            pending = self.store.get_latest_pending_confirmation()

        if pending is None:
            return {
                "success": False,
                "error": "No pending action to confirm",
                "message": "There is no pending action waiting for confirmation.",
            }

        if pending.is_expired:
            return {
                "success": False,
                "error": "Confirmation expired",
                "message": f"The confirmation for '{pending.description}' has expired. Please request the action again.",
            }

        if not pending.is_actionable:
            return {
                "success": False,
                "error": "Action already processed",
                "message": "This action has already been confirmed, executed, or cancelled.",
            }

        # Mark as confirmed
        if not self.store.confirm_pending(pending.confirmation_id):
            return {
                "success": False,
                "error": "Could not confirm action",
                "message": "Failed to confirm the pending action.",
            }

        # Execute the confirmed action
        # Add the confirmation_id to args so the tool knows it's confirmed
        tool_args = dict(pending.tool_args)
        tool_args["_confirmation_id"] = pending.confirmation_id

        # Dispatch to the appropriate tool
        tool_methods = {
            "cairn_delete_beat": self._delete_beat,
            "cairn_delete_act": self._delete_act,
            "cairn_delete_scene": self._delete_scene,
        }

        method = tool_methods.get(pending.tool_name)
        if not method:
            return {
                "success": False,
                "error": f"Unknown tool: {pending.tool_name}",
            }

        # Execute the tool
        result = method(tool_args)

        # Mark as executed if successful
        if result.get("success"):
            self.store.mark_confirmation_executed(pending.confirmation_id)

        return result

    def _cancel_action(self, args: dict[str, Any]) -> dict[str, Any]:
        """Cancel a pending irreversible action.

        Use when the user says 'no', 'cancel', 'never mind', etc.
        """
        confirmation_id = args.get("confirmation_id")

        # Get pending confirmation (by ID or most recent)
        if confirmation_id:
            pending = self.store.get_pending_confirmation(confirmation_id)
        else:
            pending = self.store.get_latest_pending_confirmation()

        if pending is None:
            return {
                "success": False,
                "error": "No pending action to cancel",
                "message": "There is no pending action waiting for cancellation.",
            }

        if not pending.is_actionable:
            return {
                "success": False,
                "error": "Action already processed",
                "message": "This action has already been confirmed, executed, or cancelled.",
            }

        # Cancel the pending action
        if self.store.cancel_pending(pending.confirmation_id):
            return {
                "success": True,
                "message": f"Cancelled: {pending.description}",
                "cancelled_action": pending.description,
            }
        else:
            return {
                "success": False,
                "error": "Could not cancel action",
                "message": "Failed to cancel the pending action.",
            }

    # =========================================================================
    # System Settings
    # =========================================================================

    def _set_autostart(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enable or disable Talking Rock autostart on Ubuntu login."""
        from ..autostart import set_autostart

        enabled = args.get("enabled")
        if not isinstance(enabled, bool):
            raise CairnToolError(
                code="invalid_argument",
                message="'enabled' must be a boolean",
            )

        result = set_autostart(enabled)

        if result.get("success"):
            action = "enabled" if enabled else "disabled"
            return {
                "success": True,
                "enabled": result["enabled"],
                "message": f"Autostart {action}. Talking Rock will {'now start automatically' if enabled else 'no longer start automatically'} when you log in.",
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "message": f"Failed to update autostart setting: {result.get('error', 'Unknown error')}",
            }

    def _get_autostart(self) -> dict[str, Any]:
        """Get current autostart status for Talking Rock."""
        from ..autostart import get_autostart_status

        status = get_autostart_status()

        return {
            "success": True,
            "enabled": status["enabled"],
            "desktop_file": status["desktop_file"],
            "message": f"Autostart is currently {'enabled' if status['enabled'] else 'disabled'}.",
        }

    # =========================================================================
    # Block Editor implementations
    # =========================================================================

    def _create_block(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new block."""
        from ..play import blocks_db
        from ..play.blocks_models import BlockType

        block_type = args.get("type")
        act_id = args.get("act_id")
        if not block_type:
            raise CairnToolError(code="invalid_input", message="type is required")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")

        text = args.get("text", "")
        properties = args.get("properties")

        # Use create_text_block for simple text content
        if text:
            block = blocks_db.create_text_block(
                type=block_type,
                act_id=act_id,
                page_id=args.get("page_id"),
                parent_id=args.get("parent_id"),
                text=text,
                **(properties or {}),
            )
        else:
            block = blocks_db.create_block(
                type=block_type,
                act_id=act_id,
                page_id=args.get("page_id"),
                parent_id=args.get("parent_id"),
                properties=properties,
            )

        return {
            "success": True,
            "block_id": block.id,
            "type": block.type.value,
            "message": f"Created {block.type.value} block",
        }

    def _update_block(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update an existing block."""
        from ..play import blocks_db

        block_id = args.get("block_id")
        if not block_id:
            raise CairnToolError(code="invalid_input", message="block_id is required")

        text = args.get("text")
        properties = args.get("properties")

        rich_text = None
        if text is not None:
            rich_text = [{"content": text}]

        block = blocks_db.update_block(
            block_id,
            rich_text=rich_text,
            properties=properties,
        )

        if not block:
            raise CairnToolError(code="not_found", message=f"Block not found: {block_id}")

        return {
            "success": True,
            "block_id": block.id,
            "message": "Block updated",
        }

    def _search_blocks(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search for blocks containing text."""
        from ..play import blocks_db
        from ..play_db import _get_connection, init_db

        query = args.get("query")
        if not query:
            raise CairnToolError(code="invalid_input", message="query is required")

        act_id = args.get("act_id")
        page_id = args.get("page_id")
        limit = args.get("limit", 20)

        init_db()
        conn = _get_connection()

        # Search rich_text table for matching content
        sql = """
            SELECT DISTINCT b.id, b.type, b.act_id, b.page_id, rt.content
            FROM blocks b
            JOIN rich_text rt ON rt.block_id = b.id
            WHERE rt.content LIKE ?
        """
        params = [f"%{query}%"]

        if act_id:
            sql += " AND b.act_id = ?"
            params.append(act_id)

        if page_id:
            sql += " AND b.page_id = ?"
            params.append(page_id)

        sql += f" ORDER BY b.updated_at DESC LIMIT {int(limit)}"

        cursor = conn.execute(sql, params)
        results = []
        for row in cursor:
            results.append({
                "block_id": row["id"],
                "type": row["type"],
                "act_id": row["act_id"],
                "page_id": row["page_id"],
                "preview": row["content"][:100] + ("..." if len(row["content"]) > 100 else ""),
            })

        return {
            "success": True,
            "count": len(results),
            "results": results,
        }

    def _get_page_content(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all blocks for a page."""
        from ..play import blocks_db
        from ..play.markdown_renderer import render_markdown

        page_id = args.get("page_id")
        if not page_id:
            raise CairnToolError(code="invalid_input", message="page_id is required")

        output_format = args.get("format", "markdown")

        blocks = blocks_db.get_page_blocks(page_id, recursive=True)

        if output_format == "markdown":
            content = render_markdown(blocks)
            return {
                "success": True,
                "page_id": page_id,
                "format": "markdown",
                "content": content,
                "block_count": len(blocks),
            }
        else:
            return {
                "success": True,
                "page_id": page_id,
                "format": "blocks",
                "blocks": [b.to_dict(include_children=True) for b in blocks],
                "block_count": len(blocks),
            }

    def _create_page(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new page within an act."""
        from .. import play_db

        act_id = args.get("act_id")
        title = args.get("title")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")
        if not title:
            raise CairnToolError(code="invalid_input", message="title is required")

        parent_page_id = args.get("parent_page_id")
        icon = args.get("icon")

        _, page_id = play_db.create_page(
            act_id=act_id,
            title=title,
            parent_page_id=parent_page_id,
            icon=icon,
        )

        return {
            "success": True,
            "page_id": page_id,
            "title": title,
            "message": f"Created page '{title}'",
        }

    def _list_pages(self, args: dict[str, Any]) -> dict[str, Any]:
        """List all pages in an act."""
        from .. import play_db

        act_id = args.get("act_id")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")

        parent_page_id = args.get("parent_page_id")

        pages = play_db.list_pages(act_id, parent_page_id)

        return {
            "success": True,
            "act_id": act_id,
            "count": len(pages),
            "pages": pages,
        }

    def _update_page(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update a page's title or icon."""
        from .. import play_db

        page_id = args.get("page_id")
        if not page_id:
            raise CairnToolError(code="invalid_input", message="page_id is required")

        title = args.get("title")
        icon = args.get("icon")

        page = play_db.update_page(
            page_id=page_id,
            title=title,
            icon=icon,
        )

        if not page:
            raise CairnToolError(code="not_found", message=f"Page not found: {page_id}")

        return {
            "success": True,
            "page_id": page_id,
            "title": page["title"],
            "message": "Page updated",
        }

    def _add_scene_block(self, args: dict[str, Any]) -> dict[str, Any]:
        """Add a scene embed block to a page."""
        from ..play import blocks_tree

        act_id = args.get("act_id")
        scene_id = args.get("scene_id")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")
        if not scene_id:
            raise CairnToolError(code="invalid_input", message="scene_id is required")

        page_id = args.get("page_id")
        parent_id = args.get("parent_id")

        try:
            block = blocks_tree.create_scene_block(
                act_id=act_id,
                scene_id=scene_id,
                page_id=page_id,
                parent_id=parent_id,
            )
        except ValueError as e:
            raise CairnToolError(code="invalid_input", message=str(e)) from e

        return {
            "success": True,
            "block_id": block.id,
            "scene_id": scene_id,
            "message": f"Added scene embed block for scene {scene_id}",
        }

    def _get_unchecked_todos(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all unchecked to-do items in an act."""
        from .. import play_db

        act_id = args.get("act_id")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")

        todos = play_db.get_unchecked_todos(act_id)

        return {
            "success": True,
            "act_id": act_id,
            "count": len(todos),
            "todos": todos,
        }

    def _get_page_tree(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get the full page tree for an act."""
        from .. import play_db

        act_id = args.get("act_id")
        if not act_id:
            raise CairnToolError(code="invalid_input", message="act_id is required")

        tree = play_db.get_page_tree(act_id)

        return {
            "success": True,
            "act_id": act_id,
            "pages": tree,
        }

    def _export_page_markdown(self, args: dict[str, Any]) -> dict[str, Any]:
        """Export a page's block content as Markdown."""
        from ..play import blocks_db
        from ..play.markdown_renderer import render_markdown

        page_id = args.get("page_id")
        if not page_id:
            raise CairnToolError(code="invalid_input", message="page_id is required")

        blocks = blocks_db.get_page_blocks(page_id, recursive=True)
        markdown = render_markdown(blocks)

        return {
            "success": True,
            "page_id": page_id,
            "markdown": markdown,
            "block_count": len(blocks),
        }
