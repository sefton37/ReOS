# CAIRN Architecture

**CAIRN** = The attention minder. Scrum master / air traffic controller for your Play knowledge base.

## Core Philosophy

CAIRN embodies "No One" - calm, non-coercive, makes room rather than demands attention.
- Surfaces the **next thing**, not everything
- Priority driven by **user decision**, CAIRN surfaces when decisions are needed
- Time and calendar aware
- Never gamifies, never guilt-trips

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CAIRN Layer                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Activity Tracker│  │Priority Surfacer│  │ Kanban Manager  │  │
│  │ (last touched,  │  │ (needs decision,│  │ (active, back-  │  │
│  │  engagement)    │  │  stale items)   │  │  log, waiting)  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                              │                                   │
│              ┌───────────────┴───────────────┐                   │
│              │      Knowledge Graph          │                   │
│              │  (contacts ↔ projects/tasks)  │                   │
│              └───────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Play Store    │  │Thunderbird Bridge│  │  CAIRN SQLite   │
│  (Acts/Scenes/  │  │ (Calendar, Email,│  │ (Activity logs, │
│   Beats/KB)     │  │  Contacts)       │  │  priorities)    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Data Model

### 1. Play Extensions (existing, enhanced)

The Play architecture (Acts → Scenes → Beats) remains the source of truth for projects/tasks.
CAIRN adds **metadata overlays**:

```python
@dataclass
class CairnMetadata:
    """Activity tracking overlay for Play entities."""
    entity_type: str        # "act", "scene", "beat"
    entity_id: str

    # Activity tracking
    last_touched: datetime  # Last user interaction
    touch_count: int        # Number of interactions
    created_at: datetime

    # Kanban state
    kanban_state: str       # "active", "backlog", "waiting", "someday", "done"
    waiting_on: str | None  # Who/what we're waiting for
    waiting_since: datetime | None

    # Priority (user-set, not computed)
    priority: int | None    # 1-5, None = needs decision
    priority_set_at: datetime | None
    priority_reason: str | None

    # Time awareness
    due_date: datetime | None
    start_date: datetime | None
    defer_until: datetime | None
```

### 2. Thunderbird Bridge (read-only)

CAIRN reads from Thunderbird's local SQLite databases:

```python
@dataclass
class ThunderbirdConfig:
    """Configuration for Thunderbird integration."""
    profile_path: Path  # e.g., ~/snap/thunderbird/common/.thunderbird/xxx.default

    # Databases
    address_book: Path  # abook.sqlite
    calendar: Path      # calendar-data/local.sqlite

    # Read-only - Thunderbird remains source of truth
    sync_interval_seconds: int = 300  # 5 minutes


@dataclass
class CalendarEvent:
    """Event from Thunderbird calendar."""
    id: str
    title: str
    start: datetime
    end: datetime
    status: str  # "TENTATIVE", "CONFIRMED", "CANCELLED"
    priority: int | None

    # CAIRN enrichment
    linked_acts: list[str]      # Act IDs this relates to
    linked_contacts: list[str]  # Contact IDs


@dataclass
class Contact:
    """Contact from Thunderbird address book."""
    id: str
    display_name: str
    email: str | None
    phone: str | None
    organization: str | None

    # CAIRN enrichment (stored in CAIRN DB, not Thunderbird)
    linked_acts: list[str]      # Projects they're involved in
    last_interaction: datetime | None
    interaction_count: int
    notes: str | None
```

### 3. Contact Knowledge Graph

Links contacts to Play entities:

```python
@dataclass
class ContactLink:
    """Link between a contact and a Play entity."""
    link_id: str
    contact_id: str         # Thunderbird contact ID
    entity_type: str        # "act", "scene", "beat"
    entity_id: str
    relationship: str       # "owner", "collaborator", "stakeholder", "waiting_on"
    created_at: datetime
    notes: str | None
```

### 4. CAIRN SQLite Schema

```sql
-- Activity tracking for Play entities
CREATE TABLE cairn_metadata (
    entity_type TEXT NOT NULL,      -- 'act', 'scene', 'beat'
    entity_id TEXT NOT NULL,
    last_touched TEXT,              -- ISO timestamp
    touch_count INTEGER DEFAULT 0,
    created_at TEXT,
    kanban_state TEXT DEFAULT 'backlog',  -- 'active', 'backlog', 'waiting', 'someday', 'done'
    waiting_on TEXT,
    waiting_since TEXT,
    priority INTEGER,               -- 1-5, NULL = needs decision
    priority_set_at TEXT,
    priority_reason TEXT,
    due_date TEXT,
    start_date TEXT,
    defer_until TEXT,
    PRIMARY KEY (entity_type, entity_id)
);

-- Contact knowledge graph
CREATE TABLE contact_links (
    link_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,       -- Thunderbird contact ID
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    relationship TEXT NOT NULL,     -- 'owner', 'collaborator', 'stakeholder', 'waiting_on'
    created_at TEXT NOT NULL,
    notes TEXT
);

CREATE INDEX idx_contact_links_contact ON contact_links(contact_id);
CREATE INDEX idx_contact_links_entity ON contact_links(entity_type, entity_id);

-- Activity log (for trends and last-touched tracking)
CREATE TABLE activity_log (
    log_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,    -- 'viewed', 'edited', 'completed', 'created', 'priority_set'
    timestamp TEXT NOT NULL,
    details TEXT                    -- JSON for additional context
);

CREATE INDEX idx_activity_log_entity ON activity_log(entity_type, entity_id);
CREATE INDEX idx_activity_log_timestamp ON activity_log(timestamp);

-- Priority decisions needed (surfaced by CAIRN)
CREATE TABLE priority_queue (
    queue_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,           -- Why priority decision is needed
    surfaced_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT                 -- What the user decided
);
```

## MCP Tools

### Knowledge Base CRUD

```
cairn_list_items        - List items with filters (kanban state, priority, due date, contact)
cairn_get_item          - Get single item with full context
cairn_touch_item        - Mark item as touched (updates last_touched)
cairn_set_priority      - Set priority (1-5) with optional reason
cairn_set_kanban_state  - Move item between kanban states
cairn_set_waiting       - Mark item as waiting on someone/something
cairn_defer_item        - Defer item until a date
cairn_link_contact      - Link a contact to an item
cairn_unlink_contact    - Remove contact link
```

### Surfacing & Prioritization

```
cairn_surface_next      - Get the "next thing" based on priority, due date, context
cairn_surface_stale     - Items not touched in N days that might need attention
cairn_surface_needs_priority - Items without priority that CAIRN thinks need one
cairn_surface_waiting   - Items waiting on others (with duration)
cairn_surface_today     - Calendar events + due items for today
cairn_surface_contact   - Everything related to a specific contact
```

### Thunderbird Integration

```
cairn_sync_calendar     - Sync calendar events from Thunderbird
cairn_sync_contacts     - Sync contacts from Thunderbird
cairn_get_calendar      - Get calendar events for date range
cairn_search_contacts   - Search contacts by name/email/org
```

### Analytics (for CAIRN's awareness)

```
cairn_activity_summary  - Activity patterns (when user is most active)
cairn_project_health    - Which projects are getting attention, which are stale
cairn_completion_rate   - How often items get completed vs abandoned
```

## Surfacing Algorithm

CAIRN surfaces items based on:

1. **Explicit Priority** (user-set, 1-5)
2. **Time Pressure** (due date proximity)
3. **Calendar Context** (events today/tomorrow)
4. **Staleness** (hasn't been touched in a while)
5. **Waiting Duration** (been waiting too long)
6. **Context Switches** (minimize by grouping related items)

```python
def surface_next(context: SurfaceContext) -> list[SurfacedItem]:
    """Surface the next thing(s) that need attention."""

    candidates = []

    # 1. Overdue items (highest priority)
    candidates.extend(get_overdue_items())

    # 2. Due today
    candidates.extend(get_due_today())

    # 3. Calendar events in next 2 hours
    candidates.extend(get_upcoming_events(hours=2))

    # 4. Active items by priority
    candidates.extend(get_active_by_priority())

    # 5. Items needing priority decision
    candidates.extend(get_needs_priority()[:3])  # Max 3

    # 6. Stale items (gentle nudge, not urgent)
    if context.include_stale:
        candidates.extend(get_stale_items(days=7)[:2])

    # Dedupe and rank
    return rank_and_dedupe(candidates, max_items=5)
```

## Non-Coercion Principles

1. **Never guilt-trip**: "You haven't touched X in 30 days" → "X is waiting when you're ready"
2. **User decides priority**: CAIRN surfaces the need, user sets the number
3. **Defer is valid**: "Not now" is a legitimate response
4. **Context matters**: Morning surfacing differs from evening
5. **Completion isn't the only goal**: Some items are ongoing, some get archived unfinished

## File Structure

```
src/reos/cairn/
├── __init__.py
├── models.py           # CairnMetadata, ContactLink, etc.
├── store.py            # CAIRN SQLite operations
├── thunderbird.py      # Thunderbird bridge (read-only)
├── surfacing.py        # Priority surfacing algorithms
├── activity.py         # Activity tracking
└── mcp_tools.py        # MCP tool definitions

src/reos/
├── cairn/              # New
├── code_mode/          # Existing (→ becomes RIVA)
├── linux_tools.py      # Existing (→ stays ReOS)
└── ...
```
