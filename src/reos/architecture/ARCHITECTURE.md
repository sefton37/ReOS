# ReOS Architecture Blueprint

> This document is designed to be loaded into AI agent context (~8K tokens).
> It provides the essential knowledge for CAIRN, RIVA, and other agents to understand
> and work with the ReOS codebase.

## System Overview

ReOS is a Linux desktop AI assistant with three core components:

1. **CAIRN** - The Attention Minder (knowledge management, calendar, surfacing)
2. **RIVA** - The Code Assistant (development, git, building)
3. **The Play** - Life organization (Acts = narratives, Scenes = calendar events)

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
│  │   Router    │  │  (62 tools) │  │  (4-stage pipeline) │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
│         │                │                     │               │
│         ▼                ▼                     ▼               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              LLM Provider (Ollama)                       │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Core Data Models

### Atomic Operations (V2 Foundation)

Every user request is classified into atomic operations using the 3x2x3 taxonomy:

```python
# Classification dimensions
destination_type: "stream" | "file" | "process"  # Where output goes
consumer_type: "human" | "machine"               # Who consumes result
execution_semantics: "read" | "interpret" | "execute"  # What action

# Example classifications
"show memory"        → (stream, human, read)
"save to notes.txt"  → (file, human, execute)
"run pytest"         → (process, machine, execute)
```

Agents generate atomic operations:
- **CAIRN** → Calendar/Play operations (mostly file, human, read/execute)
- **ReOS** → System operations (mostly process, machine, execute)
- **RIVA** → Code operations (mostly file, machine, execute)

See [Foundation](../../../docs/FOUNDATION.md) for complete architecture.

### The Play Hierarchy (2-tier)

```python
# Location: src/reos/play_fs.py

Act     # Life narrative (Career, Health, Family) - months to years
  └─ Scene  # Calendar event or task with stage

SceneStage = "planning" | "in_progress" | "awaiting_data" | "complete"

# Philosophy: Two levels prevent obscuring responsibility in complexity
# - Acts answer "What narrative does this belong to?"
# - Scenes answer "When am I doing this?"
```

### CAIRN Knowledge Store

```python
# Location: src/reos/cairn/store.py (SQLite)

Tables:
- knowledge_items      # User's stored knowledge/notes
- scene_calendar_links # Scene ↔ Calendar event mappings
- preferences          # User preferences learned over time

Key relationships:
- One Scene per calendar event (recurring events NOT expanded)
- next_occurrence computed from RRULE for recurring events
```

### Surfaced Items

```python
# Location: src/reos/cairn/models.py

@dataclass
class SurfacedItem:
    entity_type: str      # "scene", "calendar_event", "knowledge"
    entity_id: str
    title: str
    reason: str           # Why surfaced (e.g., "In 30 minutes")
    priority: int         # 1-5, higher = more urgent
    act_id: str | None    # For navigation
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
- `cairn/scene_calendar_sync.py` - Calendar → Scene synchronization

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
- `PLAY` → cairn_list_acts, cairn_create_scene, cairn_move_scene, etc.
- `SYSTEM` → linux_system_info, linux_list_processes
- `CONTACTS` → cairn_search_contacts
- `PERSONAL` → Answered from The Play context (no tool)

### RIVA (Code Assistant)

**Purpose:** Assist with software development tasks.

**Key Files:**
- `code_mode/` - Code mode implementation
- `providers/` - LLM provider abstraction (Ollama)

**Capabilities:**
- Git operations (bounded to configured repos)
- Code search and navigation
- Build and test execution
- File reading/writing (within safety bounds)

### The Play (Life Organization)

**Purpose:** Two-tier organizational system for life management.

**Philosophy:**
- Acts = Life narratives (months to years)
- Scenes = Calendar events that define the narrative's journey
- Two levels prevent obscuring responsibility in complexity

**Key Files:**
- `play_fs.py` - Play storage operations
- `play_db.py` - SQLite-based Play storage

**Database Schema:**
```sql
acts (
  act_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  active INTEGER DEFAULT 0,
  notes TEXT,
  color TEXT,
  ...
)

scenes (
  scene_id TEXT PRIMARY KEY,
  act_id TEXT REFERENCES acts(act_id),
  title TEXT NOT NULL,
  stage TEXT DEFAULT 'planning',
  calendar_event_id TEXT,
  recurrence_rule TEXT,
  ...
)
```

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
| `cairn_delete_act` | Delete Act |
| `cairn_list_scenes` | List Scenes in Act |
| `cairn_create_scene` | Create Scene in Act |
| `cairn_update_scene` | Update Scene title/stage/notes |
| `cairn_delete_scene` | Delete a Scene |
| `cairn_move_scene` | Move Scene between Acts |

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
// - "play/scenes/create" → Create Scene
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
- Calendar links preserved on Scene operations

## File Index

### Python Backend (`src/reos/`)

| File | Purpose | Key Exports |
|------|---------|-------------|
| `agent.py` | Main agent routing | `ReOSAgent` |
| `mcp_tools.py` | Tool registry & routing | `list_tools()`, `call_tool()` |
| `play_fs.py` | Play operations | `create_act()`, `create_scene()`, etc. |
| `play_db.py` | Play SQLite storage | Schema and CRUD |
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
| `scene_calendar_sync.py` | Calendar → Scene sync | `sync_calendar_to_scenes()` |

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

## Health Pulse (Dialectical Health Framework)

**Purpose:** Monitor system health across three axes without becoming intrusive.

**Master Dialectic:** *The system genuinely needs you AND must never coerce you.*

### Three Health Axes

**1. Context Health (Engagement)**
- Context freshness (data staleness)
- Pattern currency (behavioral drift detection)
- Act vitality (dormant narrative detection)

**2. Calibration Health**
- Signal quality (feedback genuineness)
- Stated vs. demonstrated preferences
- Correction intake (error visibility)

**3. System Health (Integrity)**
- Software currency (dependency updates)
- Data integrity (SQLite health)
- Security posture (zero-trust guarantees)

### Anti-Nag Protocol

Health findings are surfaced through:
- **Rate limiting** — Max 2 surfacings per day
- **Deduplication** — Dismissed items silenced for 7 days
- **Snooze detection** — No surfacing during flow states
- **Acknowledgment tracking** — Never repeat acknowledged items
- **Reframing** — "My context may be outdated" vs. "You haven't logged in"

### Access Patterns

- **Chat-invokable** — "How are you doing?" returns full health report
- **Passive UI indicator** — Colored badge in nav (green/yellow/red)
- **Startup greeting** — Optional single-line mention if needed

**Key Files:**
- `cairn/health/pulse.py` - Unified health assessment
- `cairn/health/checks/` - Individual axis checks
- `cairn/health/anti_nag.py` - Surfacing protocol

---

## New Package Structure

As of the LLM-first directory restructure, six new top-level packages exist alongside `src/reos/`:

### Top-Level Packages

| Package | Purpose | Wraps |
|---------|---------|-------|
| `llm/` | LLM inference layer | `reos.providers` |
| `classification/` | Request classification | `reos.atomic_ops.classifier` |
| `agents/` | Agent abstractions | Core agent interfaces |
| `routing/` | Request routing | `reos.atomic_ops.processor` |
| `verification/` | Verification pipeline + LLM-as-judge | New infrastructure |
| `search/` | Semantic search | `reos.memory.embeddings` |

### Import Guidance

New code should prefer the new packages for cleaner dependencies:

```python
# Preferred (new)
from llm import OllamaProvider, get_provider
from classification import LLMClassifier
from agents import CAIRNAgent, ReOSAgent
from routing import RequestRouter
from verification import LLMIntentVerifier

# Legacy (still works)
from reos.providers import OllamaProvider
from reos.atomic_ops.classifier import AtomicClassifier
```

### Package Files

**llm/**
- `__init__.py` - Re-exports from `reos.providers` + `OllamaInference`
- `inference.py` - `OllamaInference` wrapper (generate, classify, stream)

**classification/**
- `__init__.py` - Re-exports `Classification`, `LLMClassifier`, enum types
- `llm_classifier.py` - `LLMClassifier` with keyword fallback

**agents/**
- `__init__.py` - Re-exports all agents + legacy `ChatAgent`
- `base_agent.py` - `BaseAgent` ABC, `AgentContext`, `AgentResponse`
- `cairn_agent.py` - `CAIRNAgent` (Play data, knowledge, calendar)
- `reos_agent.py` - `ReOSAgent` (system info, command proposals)

**routing/**
- `__init__.py` - Re-exports `RequestRouter` + legacy `AtomicOpsProcessor`
- `router.py` - `RequestRouter` (classify → route → respond)

**verification/**
- `__init__.py` - Re-exports all verifiers from `reos.atomic_ops.verifiers`
- `intent_verifier.py` - `LLMIntentVerifier` (LLM-as-judge, fail-closed)

**search/**
- `__init__.py` - Re-exports `EmbeddingService` from `reos.memory.embeddings`

---

*This document is auto-loaded into CAIRN context. Last updated: 2026-02-11*
