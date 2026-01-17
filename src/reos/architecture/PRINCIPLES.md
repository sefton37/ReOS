# ReOS Architecture Principles

> Guidelines for maintaining the self-knowledge system and architectural documentation.

## Core Principle: AI Should Understand Itself

ReOS agents (CAIRN, RIVA) should be able to:
1. Explain how their own features work
2. Locate relevant code when implementing changes
3. Understand architectural decisions
4. Navigate the codebase efficiently

## Three-Tier Knowledge System

### Tier 1: Architecture Blueprint (Always Available)

**File:** `ARCHITECTURE.md` (~8K tokens)

**Purpose:** Provides compressed but comprehensive overview that fits in AI context.

**Maintenance Rules:**
- Keep under 8K tokens (verify with `len(content) // 4`)
- Update when major features are added/changed
- Focus on "what" and "how", not line-by-line details
- Include: data models, component architecture, tool index, file purposes

**Update Triggers:**
- New major component added
- Data model changes
- New tool category added
- Significant architectural changes

### Tier 2: RAG/Retrieval (On-Demand)

**Files:** `code_index.py`, `__init__.py`

**Purpose:** Search codebase for specific code when needed.

**Maintenance Rules:**
- Index rebuilds automatically (no manual maintenance)
- Add docstrings to new functions/classes (improves search quality)
- Use descriptive function names (improves search quality)

**Best Practices for Searchability:**
```python
# Good: Descriptive name + docstring
def sync_calendar_to_scenes(thunderbird, store, hours=168):
    """Sync calendar events to Scenes in The Play.

    For each calendar event (NOT expanded recurring events):
    1. Check if a Scene already exists for this event
    2. If not, create Scene in the appropriate Act
    3. Link the Scene to the calendar event
    """

# Bad: Vague name, no docstring
def sync(t, s, h=168):
    pass
```

### Tier 3: ADRs (Architectural Decisions)

**Directory:** `adrs/`

**Purpose:** Document the "why" behind architectural decisions.

**ADR Template:**
```markdown
# ADR-NNNN: Title

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Decision Makers:** Team/Person

## Context
What problem are we solving? What constraints exist?

## Decision
What did we decide? How does it work?

## Consequences
### Positive
- Benefits of this decision

### Negative
- Drawbacks or risks

## Implementation Notes
Key files, patterns, or code references.
```

**When to Write an ADR:**
- New major feature or subsystem
- Significant architectural change
- Decision that might be questioned later
- Trade-off that has alternatives

## Self-Documentation Standards

### Docstrings

Every public function/class should have:
1. One-line summary
2. Detailed description (if complex)
3. Args with types and descriptions
4. Returns with type and description
5. Raises (if applicable)

```python
def create_scene(
    *,
    act_id: str,
    title: str,
    stage: str = "planning",
    notes: str = "",
) -> list[Scene]:
    """Create a new Scene in an Act.

    Scenes represent calendar events or tasks within an Act's narrative.
    They progress through stages: planning → in_progress → awaiting_data → complete.

    Args:
        act_id: ID of the Act to add the Scene to.
        title: Title for the new Scene.
        stage: Initial stage (default: "planning").
        notes: Optional notes for the Scene.

    Returns:
        Updated list of all Scenes in the Act.

    Raises:
        ValueError: If the Act doesn't exist.
    """
```

### Comments

Use comments for:
- "Why" not "what" (code shows what, comments explain why)
- Non-obvious business logic
- Workarounds with context
- TODO items with owner/date

```python
# Bad: Explains what (obvious from code)
# Increment counter by 1
counter += 1

# Good: Explains why
# Use +1 offset because calendar API uses 1-based indexing
event_index = position + 1
```

## MCP Tool Documentation

Every tool should have:
1. Clear `description` (used by LLM to understand purpose)
2. Complete `input_schema` with property descriptions
3. Handler that returns consistent structure

```python
Tool(
    name="cairn_move_scene",
    description=(
        "Move a Scene to a different Act. Uses fuzzy matching for names."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "scene_name": {
                "type": "string",
                "description": "Name of the Scene to move (fuzzy matched)"
            },
            "target_act_name": {
                "type": "string",
                "description": "Target Act name (fuzzy matched)"
            },
        },
    },
)
```

## Updating the Architecture

### When to Update ARCHITECTURE.md

1. **New Component:** Add to system overview diagram and file index
2. **New Data Model:** Add to Core Data Models section
3. **New Tool Category:** Add to MCP Tools System section
4. **New Communication Pattern:** Add to Communication Patterns section

### Verification Checklist

Before committing architecture changes:
- [ ] ARCHITECTURE.md under 8K tokens
- [ ] All new functions have docstrings
- [ ] ADR written for significant decisions
- [ ] Tool descriptions are clear and complete
- [ ] File index is up to date

### Testing Self-Knowledge

After changes, verify agents can:
```
1. "How does the intent engine work?"
   → Should describe 4-stage pipeline

2. "Where is scene creation implemented?"
   → Should find play_fs.py:create_scene

3. "Why do we use a theatrical metaphor?"
   → Should reference ADR-0001
```

## Maintenance Schedule

| Frequency | Task |
|-----------|------|
| Per PR | Add docstrings to new code |
| Weekly | Review ARCHITECTURE.md accuracy |
| Per feature | Write ADR if significant |
| Monthly | Rebuild and verify code index |

---

*These principles ensure ReOS agents maintain accurate self-knowledge as the codebase evolves.*
