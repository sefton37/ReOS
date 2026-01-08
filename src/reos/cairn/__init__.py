"""CAIRN - The Attention Minder.

CAIRN is the scrum master / air traffic controller for your Play knowledge base.
It surfaces what needs attention, tracks activity, and helps prioritize without
being coercive.

Core principles:
- Surfaces the next thing, not everything
- Priority driven by user decision, CAIRN surfaces when decisions are needed
- Time and calendar aware
- Never gamifies, never guilt-trips
"""

from __future__ import annotations

from reos.cairn.models import (
    CairnMetadata,
    KanbanState,
    ActivityType,
    ActivityLogEntry,
    ContactLink,
    ContactRelationship,
    PriorityQueueItem,
    SurfacedItem,
    SurfaceContext,
)

from reos.cairn.store import CairnStore

from reos.cairn.thunderbird import (
    ThunderbirdBridge,
    ThunderbirdConfig,
    ThunderbirdContact,
    CalendarEvent,
    CalendarTodo,
)

from reos.cairn.surfacing import (
    CairnSurfacer,
    create_surface_context,
)

from reos.cairn.mcp_tools import (
    CairnToolHandler,
    CairnToolError,
    list_tools as list_cairn_tools,
)

__all__ = [
    # Models
    "CairnMetadata",
    "KanbanState",
    "ActivityType",
    "ActivityLogEntry",
    "ContactLink",
    "ContactRelationship",
    "PriorityQueueItem",
    "SurfacedItem",
    "SurfaceContext",
    # Store
    "CairnStore",
    # Thunderbird
    "ThunderbirdBridge",
    "ThunderbirdConfig",
    "ThunderbirdContact",
    "CalendarEvent",
    "CalendarTodo",
    # Surfacing
    "CairnSurfacer",
    "create_surface_context",
    # MCP Tools
    "CairnToolHandler",
    "CairnToolError",
    "list_cairn_tools",
]
