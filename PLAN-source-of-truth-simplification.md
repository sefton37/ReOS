# Source of Truth Simplification Plan

## COMPLETED CHANGES (2026-01-15)

The following issues have been fixed:

### 1. Context Toggles Now Work
- `agent.py:_build_full_context()` now checks `disabled_sources` before loading each context
- Added `_get_disabled_sources()` helper method to agent
- Context toggles in UI now actually affect what's included in LLM prompts

### 2. ContextService Uses Database (Not In-Memory)
- Removed `_disabled_sources` in-memory set
- Now reads/writes to `context_disabled_sources` database key
- CLI and RPC share same source of truth

### 3. Valid Sources Unified
- Created `src/reos/context_sources.py` - single source of truth
- `VALID_SOURCE_NAMES` and `DISABLEABLE_SOURCES` exported as frozensets
- `ui_rpc_server.py` and `context_service.py` now import from shared module
- "codebase" now properly included in valid sources

### 4. Safety Settings Persisted
- Handlers save to database: `safety_sudo_limit`, `safety_command_length`, `safety_max_iterations`, `safety_wall_clock_timeout`
- `_load_persisted_safety_settings()` loads on startup
- Settings survive application restart

---

## ORIGINAL ANALYSIS (Kept for Reference)

## Executive Summary

Investigation reveals **three major areas** with source of truth issues between UI and Python:

1. **Context Menu Toggles** - CRITICAL: The UI shows toggles for context sources, but **the agent completely ignores them**
2. **Settings/Personas** - HIGH: `agent_type` silently dropped, default prompts duplicated, safety settings not persisted
3. **Dead Code** - MEDIUM: `ContextService` class is unused duplication

---

## Issue 1: Context Menu Toggles (BROKEN FEATURE)

### Current State

The context overlay (`contextOverlay.ts`) shows toggles for:
- System Prompt
- The Play
- Learned Knowledge
- System State
- Architecture (codebase)
- Conversation (cannot disable)

**Problem:** When user toggles a source OFF:
1. `ui_rpc_server.py:2744-2745` stores it in database: `context_disabled_sources`
2. `context_meter.py:162-167` uses it for **statistics only**
3. `agent.py:1741-1747` builds context **without ever checking disabled_sources**

### Evidence

```python
# agent.py:1741-1747 - NO disabled_sources check
play_context = self._get_play_context()
play_data = self._gather_play_data()
learned_context = self._get_learned_context()
system_context = self._get_system_context()
codebase_context = self._get_codebase_context()
```

### Recommendation: Option A (Simple) - Make toggles work

```python
# agent.py - Add disabled_sources parameter
def _build_full_context(self, user_text, conversation_id, agent_type=None):
    # Get disabled sources from database
    disabled = self._get_disabled_sources()

    # Only load enabled sources
    play_context = "" if "play_context" in disabled else self._get_play_context()
    learned_context = "" if "learned_kb" in disabled else self._get_learned_context()
    system_context = "" if "system_state" in disabled else self._get_system_context()
    codebase_context = "" if "codebase" in disabled else self._get_codebase_context()
```

### Recommendation: Option B (Simpler) - Remove the feature

If context toggles aren't needed, remove:
- `contextOverlay.ts` toggle UI
- `context/toggle_source` RPC handler
- `context_disabled_sources` database key
- Keep only the statistics display

**My recommendation:** Option A if users need fine control over context, Option B if not.

---

## Issue 2: Context Source Definitions in 3 Places

### Current State

Valid context sources defined separately in:

| Location | Sources Listed |
|----------|----------------|
| `context_meter.py:179-228` | system_prompt, play_context, learned_kb, system_state, **codebase**, messages |
| `ui_rpc_server.py:2730` | system_prompt, play_context, learned_kb, system_state, messages (**missing codebase**) |
| `contextOverlay.ts:233-240` | Colors for each source |

**Problem:** "codebase" is missing from validation, meaning toggle would fail silently.

### Recommendation: Single Source of Truth

Create a shared constant:

```python
# src/reos/context_sources.py (NEW FILE)
CONTEXT_SOURCES = {
    "system_prompt": {"display_name": "System Prompt", "can_disable": False},
    "play_context": {"display_name": "The Play", "can_disable": True},
    "learned_kb": {"display_name": "Learned Knowledge", "can_disable": True},
    "system_state": {"display_name": "System State", "can_disable": True},
    "codebase": {"display_name": "Architecture", "can_disable": True},
    "messages": {"display_name": "Conversation", "can_disable": False},
}
```

Then import everywhere instead of duplicating.

---

## Issue 3: Dead Code - ContextService

### Current State

`src/reos/services/context_service.py` has:
- `_disabled_sources: set[str]` in memory (line 96)
- `toggle_source()` method (line 134)
- `get_disabled_sources()` method (line 161)

**Problem:** This class is **never used**. The RPC handlers go directly to database.

### Recommendation: Delete it

```bash
rm src/reos/services/context_service.py
```

Or, refactor to USE it consistently instead of direct database access.

---

## Issue 4: Persona `agent_type` Not Stored

### Current State

Frontend sends:
```typescript
// settingsOverlay.ts:1643
{ id, name, agent_type, system_prompt, ... }
```

Backend receives and stores:
```python
# db.py:188-199 - NO agent_type column
INSERT INTO agent_personas (id, name, system_prompt, default_context, ...)
```

**Problem:** `agent_type` is silently dropped, then reconstructed by parsing the ID pattern (`persona-cairn` → `cairn`).

### Recommendation: Either store it or don't send it

**Option A:** Add `agent_type` column to database schema
**Option B:** Stop sending `agent_type` from frontend, let backend derive it

---

## Issue 5: Default System Prompts Duplicated

### Current State

| Location | What's There |
|----------|--------------|
| `settingsOverlay.ts:1489-1564` | CAIRN, RIVA, REOS defaults |
| `agent.py:896-931` | REOS default only |

**Problem:** If frontend defaults change, backend doesn't know. If CAIRN/RIVA personas are deleted, backend can't restore them.

### Recommendation: Store defaults in database at first run

Move default prompts to Python only, insert into database on first startup:

```python
# db.py or agent.py - on init
def _ensure_default_personas():
    for agent_type in ["cairn", "riva", "reos"]:
        if not db.get_agent_persona(f"persona-{agent_type}"):
            db.upsert_agent_persona(id=f"persona-{agent_type}", ...)
```

Frontend reads defaults from database via RPC, never has hardcoded prompts.

---

## Issue 6: Safety Settings Not Persisted

### Current State

```python
# ui_rpc_server.py:3186, 3208, etc.
linux_tools._MAX_SUDO_ESCALATIONS = value  # Module-level var
security.MAX_COMMAND_LEN = value            # Module-level var
```

**Problem:** These reset to defaults on app restart.

### Recommendation: Store in database

```python
# On set:
db.set_state("safety_sudo_limit", value)
linux_tools._MAX_SUDO_ESCALATIONS = value

# On startup:
def _load_safety_settings():
    val = db.get_state("safety_sudo_limit")
    if val: linux_tools._MAX_SUDO_ESCALATIONS = int(val)
```

---

## Priority Order

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | Context toggles broken | Medium | HIGH - Feature is non-functional |
| 2 | Delete ContextService dead code | Low | LOW - Cleanup |
| 3 | Unify context source definitions | Low | MEDIUM - Prevents bugs |
| 4 | Persist safety settings | Low | MEDIUM - UX improvement |
| 5 | Default prompts single source | Medium | LOW - Edge case |
| 6 | agent_type storage | Low | LOW - Works via convention |

---

## Recommended Action Plan

### Phase 1: Fix or Remove Context Toggles
- Decide: Do users need to toggle context sources?
- If YES: Wire `disabled_sources` into `agent.py:_build_full_context()`
- If NO: Remove toggle UI and RPC handlers

### Phase 2: Cleanup
- Delete `src/reos/services/context_service.py`
- Add "codebase" to `ui_rpc_server.py:2730` valid sources
- Create shared `CONTEXT_SOURCES` constant

### Phase 3: Persistence
- Persist safety settings to database
- Load on startup

### Phase 4: Optional
- Consider adding `agent_type` column if needed
- Consider backend-only default prompts

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/reos/agent.py` | Add disabled_sources check to `_build_full_context()` |
| `src/reos/ui_rpc_server.py:2730` | Add "codebase" to valid_sources |
| `src/reos/services/context_service.py` | DELETE (dead code) |
| `apps/reos-tauri/src/contextOverlay.ts` | Either fix or simplify |
| `src/reos/db.py` | Add safety settings persistence (optional) |
