# ADR-0001: The Play Hierarchy (Acts → Scenes)

**Status:** Accepted (Updated)
**Date:** 2026-01-17 (Updated from 2026-01-14)
**Decision Makers:** ReOS Core Team

## Context

Users need a way to organize their life, work, and tasks in a meaningful way that goes beyond simple todo lists. We needed a structure that:

1. Is intuitive and memorable
2. Supports hierarchical organization without encouraging over-complexity
3. Allows for both planning and execution tracking
4. Scales from single tasks to life goals
5. Prevents hiding from responsibility in layers of abstraction

## Decision

We adopted a theatrical metaphor called "The Play" with **two levels**:

```
Act → Scene
```

### Acts (Life Narratives)
- Represent sustained narratives in your life (months to years)
- Examples: Career, Health, Family, Side Projects, Home Renovation
- Serve as knowledge bases for these narratives
- One Act can be active at a time (sets context for AI)
- "Your Story" is a protected default Act for unassigned items

### Scenes (Calendar Events & Tasks)
- Calendar events that make up the moments defining an Act's narrative
- The atomic units of progress
- Have a stage: `planning` → `in_progress` → `awaiting_data` → `complete`
- Can be linked to calendar events (including recurring series)
- Tied to time: one-time events, recurring series, or deadlined tasks

## Rationale: Why Two Tiers?

The original design had three tiers (Acts → Scenes → Beats). We simplified to two tiers based on the principle:

> **Two levels prevent the temptation to obscure responsibility in complexity.**

Many productivity systems fail because they encourage over-organization:
- Projects contain sub-projects
- Sub-projects have milestones
- Milestones have tasks
- Tasks have subtasks

This complexity becomes a hiding place. Users organize instead of doing.

The Play forces clarity:
1. **What narrative does this belong to?** → Act
2. **When am I doing this?** → Scene

If you can't answer these two questions, you're not ready to act.

## Consequences

### Positive
- Simple mental model for organization
- Two-level hierarchy matches how people actually commit to work
- Calendar-centric design aligns with how time actually works
- Prevents procrastination through over-organization
- "Your Story" provides safe landing place for new items

### Negative
- Some users may want more nesting (by design, we don't offer it)
- Theatrical terminology may confuse some users initially
- Less flexibility than multi-level task managers

### Migration from 3-tier
- Former "Beats" became the new "Scenes"
- Former "Scenes" (middle tier) were eliminated
- Data migration preserves all content, just flattens structure
- Backward compatibility aliases maintained in code for transition

## Implementation Notes

- Storage: SQLite database (`~/.local/share/reos/reos.db`)
- Acts and Scenes stored in database tables with foreign key relationship
- Scenes include calendar linking metadata (event ID, recurrence rule)
- Thunderbird integration for bidirectional calendar sync
- Protected "Your Story" Act cannot be deleted
