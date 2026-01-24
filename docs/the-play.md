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

Scenes can be embedded in Pages as Scene blocks, creating a seamless connection between your knowledge base and calendar.

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

Current schema version: **8** (includes blocks support)

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

- `docs/blocks-api.md` - Detailed blocks API documentation
- `docs/cairn_architecture.md` - CAIRN attention minder design
- `docs/testing-strategy.md` - Testing approach
