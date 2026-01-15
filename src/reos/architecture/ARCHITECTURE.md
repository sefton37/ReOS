# ReOS Architecture Blueprint

> This document is designed to be loaded into AI agent context (~8K tokens).
> It provides the essential knowledge for CAIRN, RIVA, and other agents to understand
> and work with the ReOS codebase.

## System Overview

ReOS is a Linux desktop AI assistant with three core components:

1. **CAIRN** - The Attention Minder (knowledge management, calendar, surfacing)
2. **RIVA** - The Code Assistant (development, git, building)
3. **The Play** - Life organization metaphor (Acts → Scenes → Beats)

```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri Desktop App                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  CAIRN UI   │  │  RIVA UI    │  │  The Play Overlay   │  │
│  │  (Chat)     │  │  (Code)     │  │  (Organization)     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │              │
│         └────────────────┼─────────────────────┘              │
│                          ▼                                    │
│              ┌───────────────────────┐                        │
│              │   JSON-RPC Bridge     │                        │
│              │   (Rust ↔ Python)     │                        │
│              └───────────┬───────────┘                        │
└──────────────────────────┼──────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    Python Backend                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │   Agent     │  │  MCP Tools  │  │  Intent Engine      │   │
│  │   Router    │  │  (40+ tools)│  │  (4-stage pipeline) │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
│         │                │                     │               │
│         ▼                ▼                     ▼               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              LLM Provider (Ollama/Anthropic)            │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Core Data Models

### The Play Hierarchy

```python
# Location: src/reos/play_fs.py

Act         # Major life area (Career, Health, Family)
  └─ Scene  # Project or focus area within an Act
       └─ Beat  # Individual task/item with stage

BeatStage = "planning" | "in_progress" | "awaiting_data" | "complete"

# Special protected elements:
YOUR_STORY_ACT_ID = "your-story"     # Cannot be deleted
STAGE_DIRECTION_SCENE = "stage-direction-{act_id}"  # First scene, auto-created
```

### CAIRN Knowledge Store

```python
# Location: src/reos/cairn/store.py (SQLite)

Tables:
- knowledge_items     # User's stored knowledge/notes
- beat_calendar_links # Beat ↔ Calendar event mappings
- preferences         # User preferences learned over time

Key relationships:
- One Beat per calendar event (recurring events NOT expanded)
- next_occurrence computed from RRULE for recurring events
```

### Surfaced Items

```python
# Location: src/reos/cairn/models.py

@dataclass
class SurfacedItem:
    entity_type: str      # "beat", "calendar_event", "knowledge"
    entity_id: str
    title: str
    reason: str           # Why surfaced (e.g., "In 30 minutes")
    priority: int         # 1-5, higher = more urgent
    act_id: str | None    # For navigation
    scene_id: str | None
    act_title: str | None
    is_recurring: bool
    recurrence_frequency: str | None
```

## Component Architecture

### CAIRN (Attention Minder)

**Purpose:** Help user stay on top of what matters through intelligent surfacing.

**Key Files:**
- `cairn/intent_engine.py` - 4-stage intent processing pipeline
- `cairn/surfacing.py` - Attention surfacing algorithms
- `cairn/mcp_tools.py` - CAIRN-specific MCP tool implementations
- `cairn/thunderbird.py` - Thunderbird calendar/contacts bridge
- `cairn/beat_calendar_sync.py` - Calendar → Beat synchronization

**Intent Engine Pipeline:**
```
Stage 1: Extract Intent
  └─ Pattern matching → Category (CALENDAR, PLAY, SYSTEM, etc.)
  └─ Action detection (VIEW, CREATE, UPDATE, DELETE)

Stage 2: Verify Intent
  └─ Check tool availability
  └─ Build tool arguments from natural language

Stage 3: Execute Tool
  └─ Call MCP tool with extracted args
  └─ Handle errors gracefully

Stage 4: Generate Response
  └─ Strictly from tool results (no hallucination)
  └─ Verify grounding before returning
```

**Intent Categories:**
- `CALENDAR` → cairn_get_calendar, cairn_get_upcoming_events
- `PLAY` → cairn_list_acts, cairn_create_beat, cairn_move_beat_to_act, etc.
- `SYSTEM` → linux_system_info, linux_list_processes
- `CONTACTS` → cairn_search_contacts
- `PERSONAL` → Answered from The Play context (no tool)

### RIVA (Code Assistant)

**Purpose:** Assist with software development tasks.

**Key Files:**
- `code_mode/` - Code mode implementation
- `providers/` - LLM provider abstraction (Ollama, Anthropic)

**Capabilities:**
- Git operations (bounded to configured repos)
- Code search and navigation
- Build and test execution
- File reading/writing (within safety bounds)

### The Play (Life Organization)

**Purpose:** Theatrical metaphor for organizing life into manageable pieces.

**Key Files:**
- `play_fs.py` - Filesystem-based Play storage
- `play_root()` - Returns ~/.reos-data/play by default

**Hierarchy:**
```
~/.reos-data/play/
├── acts.json           # List of Acts
├── {act-id}/
│   ├── scenes.json     # List of Scenes in this Act
│   ├── {scene-id}/
│   │   └── beats.json  # List of Beats in this Scene
```

**Protected Elements:**
- "Your Story" Act cannot be deleted (default landing place)
- "Stage Direction" Scene cannot be deleted (first scene in each Act)

## MCP Tools System

### Tool Registration

```python
# Location: src/reos/mcp_tools.py

def list_tools() -> list[Tool]:
    """Returns all available tools based on settings."""
    # Categories:
    # - Linux System Tools (always available)
    # - Git/Repo Tools (if git_integration_enabled)
    # - CAIRN Tools (knowledge, calendar, Play CRUD)
```

### Tool Routing

```python
def call_tool(db: Database, name: str, arguments: dict) -> dict:
    # Routes based on prefix:
    # - "linux_*" → linux_tools.py handlers
    # - "reos_*" → git/repo handlers
    # - "cairn_*" → CairnToolHandler in cairn/mcp_tools.py
```

### CAIRN Tools (Play CRUD)

| Tool | Purpose |
|------|---------|
| `cairn_list_acts` | List all Acts |
| `cairn_create_act` | Create new Act |
| `cairn_update_act` | Rename an Act |
| `cairn_delete_act` | Delete Act (not Your Story) |
| `cairn_list_scenes` | List Scenes in Act |
| `cairn_create_scene` | Create Scene in Act |
| `cairn_delete_scene` | Delete Scene (not Stage Direction) |
| `cairn_list_beats` | List Beats, optionally by Act |
| `cairn_create_beat` | Create Beat in Scene |
| `cairn_update_beat` | Update Beat title/stage/notes |
| `cairn_delete_beat` | Delete a Beat |
| `cairn_move_beat_to_act` | Move Beat between Acts |

All tools support **fuzzy matching** for names (e.g., "career" matches "Career").

## Communication Patterns

### Frontend ↔ Backend (JSON-RPC)

```typescript
// Location: apps/reos-tauri/src/main.ts

invoke<T>("rpc_call", {
  method: "chat",
  params: { message, agent_type, conversation_id }
})

// Common methods:
// - "chat" → Main chat endpoint
// - "cairn/attention" → Get surfaced items
// - "play/acts/list" → List Acts
// - "play/beats/create" → Create Beat
```

### Agent ↔ LLM

```python
# Location: src/reos/agent.py

class ReOSAgent:
    def chat(self, user_text, agent_type, conversation_id):
        # For CAIRN: Uses IntentEngine (structured)
        # For RIVA: Uses direct LLM with tools
```

## Safety & Bounds

### Command Execution
- Allowlist of safe commands
- Blocklist of dangerous patterns (rm -rf /, etc.)
- Timeout limits (default 30s, max 120s)
- Working directory restrictions

### Git Operations
- Bounded to configured repositories
- No operations outside repo root
- Diff size limits

### Protected Data
- "Your Story" Act cannot be deleted
- "Stage Direction" Scenes cannot be deleted
- Calendar links preserved on Beat operations

## File Index

### Python Backend (`src/reos/`)

| File | Purpose | Key Exports |
|------|---------|-------------|
| `agent.py` | Main agent routing | `ReOSAgent` |
| `mcp_tools.py` | Tool registry & routing | `list_tools()`, `call_tool()` |
| `play_fs.py` | Play filesystem operations | `create_act()`, `create_beat()`, etc. |
| `settings.py` | Configuration management | `settings` singleton |
| `database.py` | SQLite wrapper | `Database` class |

### CAIRN (`src/reos/cairn/`)

| File | Purpose | Key Exports |
|------|---------|-------------|
| `intent_engine.py` | 4-stage intent pipeline | `CairnIntentEngine` |
| `mcp_tools.py` | CAIRN tool implementations | `CairnToolHandler` |
| `store.py` | CAIRN knowledge store | `CairnStore` |
| `surfacing.py` | Attention surfacing | `CairnSurfacer` |
| `thunderbird.py` | Calendar/contacts bridge | `ThunderbirdBridge` |
| `beat_calendar_sync.py` | Calendar → Beat sync | `sync_calendar_to_beats()` |

### Frontend (`apps/reos-tauri/src/`)

| File | Purpose |
|------|---------|
| `main.ts` | App initialization, RPC calls |
| `cairnView.ts` | CAIRN chat UI |
| `playOverlay.ts` | The Play organization UI |
| `types.ts` | TypeScript type definitions |

## Extending the System

### Adding a New MCP Tool

1. Define in `list_tools()` in `mcp_tools.py`
2. Add handler in `call_tool()` or appropriate handler file
3. If CAIRN tool: Add to `CairnToolHandler.call_tool()`
4. Add intent pattern in `intent_engine.py` if natural language support needed

### Adding a New Intent Category

1. Add to `IntentCategory` enum in `intent_engine.py`
2. Add patterns to `INTENT_PATTERNS` dict
3. Add default tool to `CATEGORY_TOOLS` dict
4. Implement `_select_*_tool()` method if multiple tools
5. Add argument extraction in `_build_tool_args()`

---

*This document is auto-loaded into CAIRN context. Last updated: 2026-01-14*
