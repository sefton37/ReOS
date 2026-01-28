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
│   ├── Pages (block-based knowledge documents)
│   │   └── Blocks (paragraphs, headings, lists, todos, code, etc.)
│   ├── Scenes (calendar events within an Act)
│   └── Notebook (legacy markdown notes for the Act)
└── Contacts (people linked to Acts/Scenes)
```

## Concepts

### Acts
Life narratives that span months to years. These are the major chapters of your story.

Examples: "Career at Acme Corp", "Health Journey 2026", "Home Renovation", "Learning Rust"

Each Act represents a sustained narrative in your life—something you'll work on over time with a coherent theme. Acts are knowledge bases for these narratives.

Each Act can have:
- Pages with block-based content (Notion-style editor)
- A markdown notebook for legacy notes, reflections, and context
- Child Scenes (calendar events and tasks)
- Associated repositories (for RIVA code context)
- Linked contacts (people involved in this narrative)
- A color (for visual organization)

### Pages
Block-based documents within Acts. Pages provide a rich editing experience similar to Notion.

Each Page contains:
- Blocks of various types (see Block Types below)
- Nested sub-pages
- Optional icon for visual identification

### Blocks
The atomic units of content within Pages. Blocks form a tree structure where certain types can contain children.

**Block Types:**
| Type | Description | Nestable |
|------|-------------|----------|
| `paragraph` | Plain text content | No |
| `heading_1` | Large section heading | No |
| `heading_2` | Medium section heading | No |
| `heading_3` | Small section heading | No |
| `bulleted_list` | Unordered list item | Yes |
| `numbered_list` | Ordered list item | Yes |
| `to_do` | Task with checkbox | Yes |
| `code` | Code block with syntax highlighting | No |
| `divider` | Horizontal line separator | No |
| `callout` | Highlighted note with icon | Yes |
| `scene` | Embedded calendar event | No |
| `document_chunk` | Indexed document text for RAG | No |

**Rich Text Formatting:**
Block content supports rich text spans with:
- Bold, italic, underline, strikethrough
- Inline code
- Text and background colors
- Hyperlinks

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
- Needs Attention flag (disable auto-complete)

Scenes can be embedded in Pages as Scene blocks, creating a seamless connection between your knowledge base and calendar.

## How Scenes Operate

### The Core Assumption: You Keep Your Calendar

The Play operates on a simple premise: **your calendar is your commitment**. When you put something on your calendar, you intend to do it. The system trusts you to show up.

This is different from task managers that nag you about overdue items. The Play assumes you did what you said you'd do—unless you tell it otherwise.

### Scene Stages

Scenes flow through stages that reflect their lifecycle:

| Stage | Meaning |
|-------|---------|
| `planning` | Not yet scheduled or still being defined |
| `in_progress` | Scheduled and upcoming |
| `awaiting_data` | Blocked on external input |
| `need_attention` | Overdue and requires manual resolution |
| `complete` | Done |

The Kanban board in the Scene View displays these as columns.

### Auto-Complete: Trust Your Calendar

**Non-recurring scenes auto-complete when their time passes.**

If you scheduled a doctor's appointment for 2pm Tuesday and it's now Wednesday, The Play assumes you went to the appointment. The scene automatically moves to `complete`.

This isn't laziness—it's respect. The system trusts that you honor your commitments. It doesn't need you to manually check off every calendar event to prove you did it.

### Recurring Scenes Never Complete

**Recurring scenes can never be marked complete.**

A weekly team standup isn't something you "finish." It's an ongoing series. Each occurrence happens, but the series continues.

Recurring scenes:
- Cannot be set to `complete` stage (the option is hidden in the UI)
- Move to `need_attention` when overdue (prompting you to update their status)
- Represent the entire series, not individual occurrences

If you need to end a recurring series, delete the scene or remove its recurrence rule.

### Needs Attention: The Honesty Safeguard

Sometimes you don't keep your calendar. Meetings get skipped. Appointments get missed. Life happens.

**The "Needs Attention" flag disables auto-complete for scenes that matter.**

When enabled on a non-recurring scene:
- The scene will NOT auto-complete when its time passes
- Instead, it moves to the `need_attention` stage
- You must manually resolve it (complete, reschedule, or delete)

**When to use Needs Attention:**

| Scenario | Use Needs Attention? |
|----------|---------------------|
| Doctor appointment you might reschedule | Yes |
| Weekly team meeting (recurring) | N/A (recurring never auto-completes) |
| Deadline for a deliverable | Yes |
| Coffee with a friend | Probably not |
| Flight departure | No (you either made it or you didn't) |

The flag is a safeguard for commitments where you need accountability. It's up to you to know when to use it. Don't overuse it—if everything needs attention, nothing does.

### The Kanban Flow

The Scene View Kanban board shows the effective stage of each scene:

```
┌─────────────┬─────────────┬──────────────┬────────────────┬───────────┐
│  Planning   │ In Progress │ Awaiting Data│ Need Attention │ Complete  │
├─────────────┼─────────────┼──────────────┼────────────────┼───────────┤
│ Unscheduled │ Scheduled   │ Blocked on   │ Overdue items  │ Done      │
│ items       │ upcoming    │ external     │ requiring      │           │
│             │ events      │ input        │ resolution     │           │
└─────────────┴─────────────┴──────────────┴────────────────┴───────────┘
```

**Effective stage computation:**
1. Explicitly `complete` → Complete column
2. No scheduled time → Planning column
3. Overdue + auto-complete enabled → Complete column (auto-completed)
4. Overdue + auto-complete disabled → Need Attention column
5. Overdue + recurring → Need Attention column
6. Scheduled + `planning` stage → In Progress column (has a date)
7. Otherwise → Use explicit stage

### Summary

| Scene Type | When Overdue | Why |
|------------|--------------|-----|
| Non-recurring (default) | Auto-completes | Trust the calendar |
| Non-recurring + Needs Attention | Goes to Need Attention | You asked for accountability |
| Recurring | Goes to Need Attention | Series never "finishes" |

The system is designed to get out of your way. It assumes competence. The Needs Attention flag exists for when you want the system to hold you accountable—use it intentionally.

### Notebooks (Legacy)
Markdown files attached to Acts (and optionally Scenes). Free-form notes, meeting logs, research, whatever you need. This is the legacy system before blocks were introduced.

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

## The Block Editor UI

The Play includes a Notion-style block editor built with React and TipTap.

### Features

**Slash Commands:**
Type `/` anywhere to insert new blocks:
- `/h1`, `/h2`, `/h3` - Headings
- `/todo` - Checkbox task
- `/bullet`, `/number` - Lists
- `/code` - Code block
- `/divider` - Horizontal rule
- `/quote` - Callout/blockquote
- `/table` - Data table with rows and columns
- `/document` - Insert document into knowledge base (PDF, DOCX, TXT, MD, CSV, XLSX)

**Rich Text Formatting:**
- `Cmd+B` - Bold
- `Cmd+I` - Italic
- `Cmd+K` - Insert link
- Select text to see formatting toolbar

**Page Links:**
Type `[[` to link to other pages with autocomplete.

**Smart Views:**
- **Today** - Scenes due today + unchecked todos
- **Todos** - All unchecked todos grouped by Act
- **Waiting On** - Scenes in awaiting_data stage

**Global Search:**
`Cmd+K` opens a search modal to find content across all blocks.

**Drag & Drop:**
Reorder blocks by dragging the grip handle that appears on hover.

### Architecture

The editor is a React application mounted inside the vanilla TypeScript shell:

```
apps/reos-tauri/src/
├── react/                    # React components
│   ├── BlockEditor.tsx       # TipTap editor wrapper
│   ├── blocks/               # Block type components
│   ├── commands/             # Slash menu
│   ├── toolbar/              # Formatting toolbar
│   ├── links/                # Page link autocomplete
│   ├── sidebar/              # Tree navigation
│   ├── dnd/                  # Drag and drop
│   ├── views/                # Smart views
│   ├── search/               # Search modal
│   ├── hooks/                # React hooks
│   └── extensions/           # TipTap extensions
├── playActView.ts            # Mounts React editor
└── playWindow.ts             # Window frame
```

## CAIRN's Role

CAIRN is the attention minder for The Play:

1. **Surfaces what needs attention** - Shows upcoming Scenes without overwhelming
2. **Tracks activity** - Knows when you last touched each item
3. **Manages calendar sync** - Bidirectional sync with Thunderbird
4. **Filters through identity** - Uses the Coherence Kernel to reject distractions
5. **Never guilt-trips** - Surfaces options, doesn't judge

## Storage

The Play is stored in SQLite (`~/.local/share/reos/reos.db`) with tables:
- `acts` - Life narratives (with `root_block_id` for block-based content)
- `pages` - Block container documents within Acts
- `blocks` - Notion-style content blocks
- `rich_text` - Formatted text spans within blocks
- `block_properties` - Type-specific block properties (e.g., `checked` for todos)
- `scenes` - Calendar events and tasks (with act_id foreign key)
- `attachments` - File attachments to Acts/Scenes
- `cairn_metadata` - Activity tracking, priorities
- `scene_calendar_links` - Thunderbird calendar event links

### Schema Version

Current schema version: **10**

Recent schema changes:
- v10: Enforce recurring scenes cannot be 'complete'
- v9: Add `disable_auto_complete` for Needs Attention feature
- v8: Add `root_block_id` for block-based Act content
- v7: Add blocks, block_properties, rich_text tables

## Calendar Integration

Scenes can be linked to Thunderbird calendar events:
- Create a Scene → optionally creates a Thunderbird event
- Thunderbird event → automatically creates a Scene
- Recurring events (RRULE) are fully supported
- Next occurrence is computed for surfacing

## RPC Endpoints

### Block Operations
```
blocks/create          - Create a new block
blocks/get             - Get block by ID
blocks/list            - List blocks with filters
blocks/update          - Update block content/properties
blocks/delete          - Delete block (with optional cascade)
blocks/move            - Move block to new parent
blocks/reorder         - Reorder sibling blocks
blocks/ancestors       - Get ancestor chain
blocks/descendants     - Get all descendants
```

### Page Operations
```
blocks/page/tree       - Get block tree for page
blocks/page/markdown   - Export page as markdown
blocks/import/markdown - Import markdown as blocks
```

### Rich Text Operations
```
blocks/rich_text/get   - Get spans for block
blocks/rich_text/set   - Replace spans for block
```

### Property Operations
```
blocks/property/get    - Get single property
blocks/property/set    - Set single property
blocks/property/delete - Delete property
```

### Search Operations
```
blocks/search          - Search blocks by text
blocks/unchecked_todos - Get incomplete todos
```

### Scene Block Operations
```
blocks/scene/create    - Create scene embed block
blocks/scene/validate  - Validate scene reference
```

### Play Management (Legacy)
```
play/acts/*            - Act CRUD
play/scenes/*          - Scene CRUD
play/kb/*              - Notebook read/write
play/pages/*           - Page management
```

## Atomic Operations in The Play

Every user action on Acts and Scenes generates [atomic operations](./atomic-operations.md). The Play integrates with the V2 architecture as the primary data store for human-consumable, persistent content.

### User Actions → Atomic Operations

| User Action | Destination | Consumer | Semantics |
|-------------|-------------|----------|-----------|
| View Acts list | stream | human | read |
| Create Act | file | human | execute |
| Update Act title | file | human | execute |
| Delete Act | file | human | execute |
| View Scenes | stream | human | read |
| Create Scene | file | human | execute |
| Move Scene stage | file | human | execute |
| Mark Scene complete | file | human | execute |

### Block Editor Actions as Atomic Operations

The Notion-style block editor generates atomic operations for each edit:

| Block Action | Destination | Consumer | Semantics |
|--------------|-------------|----------|-----------|
| Create block | file | human | execute |
| Update block content | file | human | execute |
| Delete block | file | human | execute |
| Move block | file | human | execute |
| Toggle todo checkbox | file | human | execute |
| Search blocks | stream | human | read |

### Two-Tier Philosophy and Atomic Operations

The Play's two-tier simplicity (Acts → Scenes) prevents complexity hiding in the same way atomic operations prevent verification hiding:

- **Acts** answer "What narrative does this belong to?" → Operation context
- **Scenes** answer "When am I doing this?" → Operation temporal binding
- **Atomic Operations** answer "What exactly will happen?" → Operation verification

Both systems enforce clarity by limiting depth:
- The Play: 2 levels (Acts, Scenes)
- Atomic Operations: 3 dimensions (destination, consumer, semantics)

### RLHF Integration

Play actions generate feedback opportunities:

- **Scene completed on time** → Positive signal for auto-complete
- **Scene marked "needs attention"** → User requested accountability
- **Act archived** → Long-term outcome signal
- **Block content persisted** → Positive content quality signal

See [RLHF Learning](./rlhf-learning.md) for the complete feedback system.

## MCP Tools

CAIRN exposes MCP tools for Play management:
- `cairn_play_*` - CRUD for Acts/Scenes
- `cairn_kb_*` - Notebook read/write with diff preview
- `cairn_surface_*` - Priority surfacing
- `cairn_contacts_*` - Contact management
- `cairn_calendar_*` - Thunderbird calendar integration
- `cairn_blocks_*` - Block operations

See `docs/cairn_architecture.md` for full tool documentation.

## Related Documentation

- [Foundation](./FOUNDATION.md) - Core philosophy and architecture
- [Atomic Operations](./atomic-operations.md) - Operation classification
- [Blocks API](./blocks-api.md) - Detailed blocks API documentation
- [Documents](./documents.md) - Document ingestion for RAG
- [Memory System](./memory-system.md) - Semantic search and retrieval
- [CAIRN Architecture](./cairn_architecture.md) - CAIRN attention minder design
- [Testing Strategy](./testing-strategy.md) - Testing approach
