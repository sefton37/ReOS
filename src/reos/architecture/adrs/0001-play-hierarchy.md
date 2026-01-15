# ADR-0001: The Play Hierarchy (Acts → Scenes → Beats)

**Status:** Accepted
**Date:** 2026-01-14
**Decision Makers:** ReOS Core Team

## Context

Users need a way to organize their life, work, and tasks in a meaningful way that goes beyond simple todo lists. We needed a metaphor that:

1. Is intuitive and memorable
2. Supports hierarchical organization
3. Allows for both planning and execution tracking
4. Scales from single tasks to life goals

## Decision

We adopted a theatrical metaphor called "The Play" with three levels:

```
Act → Scene → Beat
```

### Acts (Major Life Areas)
- Represent major areas of life/work (Career, Health, Family, etc.)
- One Act is active at a time (sets context for AI)
- "Your Story" is a protected default Act for unassigned items

### Scenes (Projects/Focus Areas)
- Projects or focus areas within an Act
- "Stage Direction" is a protected first Scene in each Act
- Contains the Beats that make up the project

### Beats (Tasks/Items)
- Individual actionable items
- Have a stage: `planning` → `in_progress` → `awaiting_data` → `complete`
- Can be linked to calendar events (many events → one Beat for recurring)

## Consequences

### Positive
- Intuitive mental model for organization
- Natural hierarchy matches how people think about life
- Stage metaphor makes progress tracking natural
- "Your Story" provides safe landing place for new items

### Negative
- Three-level hierarchy may be overkill for simple tasks
- Theatrical terminology may confuse some users initially
- Protected elements (Your Story, Stage Direction) add complexity

## Implementation Notes

- Storage: Filesystem-based (`~/.reos-data/play/`)
- Acts and Scenes stored in JSON files
- Beats include calendar linking metadata
- Delete operations protected for Your Story and Stage Direction
