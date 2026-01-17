# The Play

The Play is Talking Rock's organizational system for your life and projects, managed by CAIRN.

## A Mirror, Not a Manager

> Every productivity tool asks: *"How can we capture what this person does?"*
>
> Talking Rock asks: *"How can this person see themselves clearly?"*

The Play doesn't track you—it reflects you. Zero trust. Local only. Encrypted at rest. Never phones home. The only report goes to the only stakeholder that matters: you.

## Philosophy

The Play uses a deliberately simple two-tier structure to prevent the temptation to obscure responsibility in layers of complexity:

- **Acts** = Life narratives (months to years)
- **Scenes** = Calendar events that define your narrative's journey

That's it. Two levels. No more.

## Structure

```
The Play
├── Acts (life narratives: Career, Health, Home, Learning)
│   ├── Scenes (calendar events within an Act)
│   └── Notebook (markdown notes for the Act)
└── Contacts (people linked to Acts/Scenes)
```

## Concepts

### Acts
Life narratives that span months to years. These are the major chapters of your story.

Examples: "Career at Acme Corp", "Health Journey 2026", "Home Renovation", "Learning Rust"

Each Act represents a sustained narrative in your life—something you'll work on over time with a coherent theme. Acts are knowledge bases for these narratives.

Each Act can have:
- A markdown notebook for notes, reflections, and context
- Child Scenes (calendar events and tasks)
- Associated repositories (for RIVA code context)
- Linked contacts (people involved in this narrative)
- A color (for visual organization)

### Scenes
Calendar events that make up the moments defining an Act's narrative. Scenes are the atomic units of progress.

Examples: "Weekly team standup", "Doctor appointment", "Contractor walkthrough", "Rust study session"

Scenes are tied to time. They can be:
- One-time events (a single appointment)
- Recurring series (weekly 1:1s, daily standups)
- Tasks with deadlines (review PR by Friday)

Each Scene has:
- Title and optional notes
- Stage: `planning` → `in_progress` → `awaiting_data` → `complete`
- Link to external resources (URLs, documents)
- Calendar event ID (for Thunderbird sync)
- Recurrence rule (for repeating events)

### Notebooks
Markdown files attached to Acts (and optionally Scenes). Free-form notes, meeting logs, research, whatever you need.

## Why Two Tiers?

Many productivity systems fail because they encourage over-organization:
- Projects contain sub-projects
- Sub-projects have milestones
- Milestones have tasks
- Tasks have subtasks

This complexity becomes a place to hide from actually doing the work.

The Play forces clarity:
1. **What narrative does this belong to?** (Act)
2. **When am I doing this?** (Scene)

If you can't answer these two questions, you're not ready to act.

## CAIRN's Role

CAIRN is the attention minder for The Play:

1. **Surfaces what needs attention** - Shows upcoming Scenes without overwhelming
2. **Tracks activity** - Knows when you last touched each item
3. **Manages calendar sync** - Bidirectional sync with Thunderbird
4. **Filters through identity** - Uses the Coherence Kernel to reject distractions
5. **Never guilt-trips** - Surfaces options, doesn't judge

## Storage

The Play is stored in SQLite (`~/.local/share/reos/reos.db`) with tables:
- `acts` - Life narratives
- `scenes` - Calendar events and tasks (with act_id foreign key)
- `attachments` - File attachments to Acts/Scenes
- `cairn_metadata` - Activity tracking, priorities
- `scene_calendar_links` - Thunderbird calendar event links

## Calendar Integration

Scenes can be linked to Thunderbird calendar events:
- Create a Scene → optionally creates a Thunderbird event
- Thunderbird event → automatically creates a Scene
- Recurring events (RRULE) are fully supported
- Next occurrence is computed for surfacing

## MCP Tools

CAIRN exposes MCP tools for Play management:
- `cairn_play_*` - CRUD for Acts/Scenes
- `cairn_kb_*` - Notebook read/write with diff preview
- `cairn_surface_*` - Priority surfacing
- `cairn_contacts_*` - Contact management
- `cairn_calendar_*` - Thunderbird calendar integration

See `docs/cairn_architecture.md` for full tool documentation.
