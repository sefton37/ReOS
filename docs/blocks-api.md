# Blocks API Documentation

The Blocks API provides a Notion-style block editor system for The Play. Blocks are the atomic units of content within Pages.

## Data Models

### Block

A content block in the editor.

```typescript
interface Block {
  id: string;                // UUID
  type: BlockType;           // Block type enum
  act_id: string;            // Act this block belongs to
  parent_id: string | null;  // Parent block ID (for nesting)
  page_id: string | null;    // Page ID (for root-level blocks)
  scene_id: string | null;   // Scene ID (for scene embed blocks)
  position: number;          // Position among siblings (0-indexed)
  created_at: string;        // ISO timestamp
  updated_at: string;        // ISO timestamp
  rich_text: RichTextSpan[]; // Content spans with formatting
  properties: Record<string, any>; // Type-specific properties
  children?: Block[];        // Nested children (when loaded)
}
```

### BlockType

Supported block types:

| Type | Description | Nestable | Properties |
|------|-------------|----------|------------|
| `page` | Container document | Yes | `icon?: string` |
| `paragraph` | Plain text | No | - |
| `heading_1` | Large heading | No | - |
| `heading_2` | Medium heading | No | - |
| `heading_3` | Small heading | No | - |
| `bulleted_list` | Unordered list item | Yes | - |
| `numbered_list` | Ordered list item | Yes | - |
| `to_do` | Checkbox task | Yes | `checked: boolean` |
| `code` | Code block | No | `language?: string` |
| `divider` | Horizontal rule | No | - |
| `callout` | Highlighted note | Yes | `icon?: string`, `color?: string` |
| `scene` | Calendar event embed | No | - |
| `atomic_operation` | Classified operation | Yes | See below |

**Nestable types** can have children blocks nested under them.

### Atomic Operation Block Type

The `atomic_operation` block type represents a classified user operation. Operations ARE blocks, enabling unified storage and querying.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `destination_type` | `'stream' \| 'file' \| 'process'` | Where output goes |
| `consumer_type` | `'human' \| 'machine'` | Who consumes result |
| `execution_semantics` | `'read' \| 'interpret' \| 'execute'` | What action is taken |
| `classification_confidence` | `number` | 0.0-1.0 confidence score |
| `user_request` | `string` | Original user request text |
| `status` | `string` | Operation status |

**Example:**

```json
{
  "id": "op-abc123",
  "type": "atomic_operation",
  "properties": {
    "destination_type": "process",
    "consumer_type": "machine",
    "execution_semantics": "execute",
    "classification_confidence": 0.85,
    "user_request": "run pytest",
    "status": "complete"
  }
}
```

Operations can have child operations when decomposed:

```json
{
  "id": "op-parent",
  "type": "atomic_operation",
  "properties": {
    "user_request": "Check memory and optimize auth.py",
    "status": "decomposed"
  },
  "children": [
    {"id": "op-child1", "type": "atomic_operation", "properties": {...}},
    {"id": "op-child2", "type": "atomic_operation", "properties": {...}}
  ]
}
```

See [Atomic Operations](./atomic-operations.md) for the complete taxonomy and [RLHF Learning](./rlhf-learning.md) for feedback collection on operations.

### RichTextSpan

A span of formatted text within a block.

```typescript
interface RichTextSpan {
  id: string;                    // UUID
  block_id: string;              // Parent block ID
  position: number;              // Position in text sequence
  content: string;               // Text content

  // Formatting flags
  bold: boolean;                 // default: false
  italic: boolean;               // default: false
  strikethrough: boolean;        // default: false
  code: boolean;                 // default: false
  underline: boolean;            // default: false

  // Optional styling
  color: string | null;          // Text color
  background_color: string | null; // Highlight color
  link_url: string | null;       // Hyperlink URL
}
```

## RPC Endpoints

All endpoints are called via the standard RPC protocol.

### Block CRUD

#### `blocks/create`

Create a new block.

**Request:**
```json
{
  "type": "paragraph",
  "act_id": "act_abc123",
  "parent_id": null,
  "page_id": "page_xyz789",
  "position": 0,
  "rich_text": [
    {"content": "Hello ", "bold": false},
    {"content": "world", "bold": true}
  ],
  "properties": {}
}
```

**Response:**
```json
{
  "block": {
    "id": "block_new123",
    "type": "paragraph",
    "act_id": "act_abc123",
    "page_id": "page_xyz789",
    "position": 0,
    "rich_text": [...],
    "properties": {},
    "created_at": "2026-01-24T10:00:00Z",
    "updated_at": "2026-01-24T10:00:00Z"
  }
}
```

#### `blocks/get`

Get a block by ID.

**Request:**
```json
{
  "block_id": "block_abc123",
  "include_children": true
}
```

**Response:**
```json
{
  "block": {
    "id": "block_abc123",
    "type": "bulleted_list",
    "children": [
      {"id": "child1", "type": "bulleted_list", ...},
      {"id": "child2", "type": "bulleted_list", ...}
    ],
    ...
  }
}
```

#### `blocks/list`

List blocks with filtering.

**Request:**
```json
{
  "page_id": "page_xyz789",
  "parent_id": null,
  "act_id": "act_abc123"
}
```

All parameters are optional. Omit `parent_id` to get root-level blocks.

**Response:**
```json
{
  "blocks": [
    {"id": "block1", "type": "heading_1", "position": 0, ...},
    {"id": "block2", "type": "paragraph", "position": 1, ...}
  ]
}
```

#### `blocks/update`

Update block content or properties.

**Request:**
```json
{
  "block_id": "block_abc123",
  "rich_text": [
    {"content": "Updated text", "bold": false}
  ],
  "properties": {"checked": true},
  "position": 2
}
```

All update fields are optional. Only provided fields are updated.

**Response:**
```json
{
  "block": {
    "id": "block_abc123",
    "rich_text": [...],
    "properties": {"checked": true},
    "updated_at": "2026-01-24T10:05:00Z",
    ...
  }
}
```

#### `blocks/delete`

Delete a block and optionally its descendants.

**Request:**
```json
{
  "block_id": "block_abc123",
  "recursive": true
}
```

**Response:**
```json
{
  "deleted": true
}
```

### Block Tree Operations

#### `blocks/move`

Move a block to a new parent and/or position.

**Request:**
```json
{
  "block_id": "block_abc123",
  "new_parent_id": "block_parent456",
  "new_page_id": null,
  "new_position": 0
}
```

Use `new_parent_id: null` to move to root level (requires `new_page_id`).

**Response:**
```json
{
  "block": {
    "id": "block_abc123",
    "parent_id": "block_parent456",
    "position": 0,
    ...
  }
}
```

#### `blocks/reorder`

Reorder sibling blocks by providing the desired order.

**Request:**
```json
{
  "block_ids": ["block3", "block1", "block2"]
}
```

All blocks must be siblings (same parent).

**Response:**
```json
{
  "blocks": [
    {"id": "block3", "position": 0, ...},
    {"id": "block1", "position": 1, ...},
    {"id": "block2", "position": 2, ...}
  ]
}
```

#### `blocks/ancestors`

Get ancestor chain from a block to root.

**Request:**
```json
{
  "block_id": "block_deep123"
}
```

**Response:**
```json
{
  "ancestors": [
    {"id": "parent1", ...},
    {"id": "grandparent1", ...},
    {"id": "root_block", ...}
  ]
}
```

Ancestors are ordered from immediate parent to root.

#### `blocks/descendants`

Get all descendants of a block in depth-first order.

**Request:**
```json
{
  "block_id": "block_parent123"
}
```

**Response:**
```json
{
  "descendants": [
    {"id": "child1", ...},
    {"id": "grandchild1", ...},
    {"id": "child2", ...}
  ]
}
```

### Page Operations

#### `blocks/page/tree`

Get the complete block tree for a page.

**Request:**
```json
{
  "page_id": "page_xyz789"
}
```

**Response:**
```json
{
  "blocks": [
    {
      "id": "block1",
      "type": "heading_1",
      "children": [],
      ...
    },
    {
      "id": "block2",
      "type": "bulleted_list",
      "children": [
        {"id": "child1", "children": [], ...}
      ],
      ...
    }
  ]
}
```

#### `blocks/page/markdown`

Export page content as Markdown.

**Request:**
```json
{
  "page_id": "page_xyz789"
}
```

**Response:**
```json
{
  "markdown": "# Heading\n\nParagraph text with **bold**.\n\n- List item 1\n- List item 2\n",
  "block_count": 4
}
```

#### `blocks/import/markdown`

Import Markdown as blocks.

**Request:**
```json
{
  "act_id": "act_abc123",
  "page_id": "page_xyz789",
  "markdown": "# My Page\n\nSome content here.\n\n- Item 1\n- Item 2"
}
```

**Response:**
```json
{
  "blocks": [
    {"id": "new1", "type": "heading_1", ...},
    {"id": "new2", "type": "paragraph", ...},
    {"id": "new3", "type": "bulleted_list", ...},
    {"id": "new4", "type": "bulleted_list", ...}
  ],
  "count": 4
}
```

### Scene Block Operations

#### `blocks/scene/create`

Create a scene embed block that displays a calendar event.

**Request:**
```json
{
  "act_id": "act_abc123",
  "scene_id": "scene_event456",
  "parent_id": null,
  "page_id": "page_xyz789",
  "position": 3
}
```

**Response:**
```json
{
  "block": {
    "id": "block_scene789",
    "type": "scene",
    "scene_id": "scene_event456",
    ...
  }
}
```

#### `blocks/scene/validate`

Validate that a scene block correctly references its scene.

**Request:**
```json
{
  "block_id": "block_scene789",
  "scene_id": "scene_event456"
}
```

**Response:**
```json
{
  "valid": true,
  "scene_exists": true,
  "act_matches": true
}
```

### Rich Text Operations

#### `blocks/rich_text/get`

Get rich text spans for a block.

**Request:**
```json
{
  "block_id": "block_abc123"
}
```

**Response:**
```json
{
  "spans": [
    {
      "id": "span1",
      "block_id": "block_abc123",
      "position": 0,
      "content": "Hello ",
      "bold": false,
      "italic": false
    },
    {
      "id": "span2",
      "block_id": "block_abc123",
      "position": 1,
      "content": "world",
      "bold": true,
      "italic": false
    }
  ]
}
```

#### `blocks/rich_text/set`

Replace all rich text for a block.

**Request:**
```json
{
  "block_id": "block_abc123",
  "spans": [
    {"content": "New ", "bold": false},
    {"content": "content", "italic": true}
  ]
}
```

**Response:**
```json
{
  "spans": [
    {"id": "newspan1", "content": "New ", ...},
    {"id": "newspan2", "content": "content", ...}
  ]
}
```

### Property Operations

#### `blocks/property/get`

Get a single block property.

**Request:**
```json
{
  "block_id": "block_todo123",
  "key": "checked"
}
```

**Response:**
```json
{
  "key": "checked",
  "value": true
}
```

#### `blocks/property/set`

Set a block property.

**Request:**
```json
{
  "block_id": "block_todo123",
  "key": "checked",
  "value": true
}
```

**Response:**
```json
{
  "ok": true,
  "key": "checked"
}
```

#### `blocks/property/delete`

Delete a block property.

**Request:**
```json
{
  "block_id": "block_code123",
  "key": "language"
}
```

**Response:**
```json
{
  "deleted": true,
  "key": "language"
}
```

### Search Operations

#### `blocks/search`

Search blocks by text content within an act.

**Request:**
```json
{
  "act_id": "act_abc123",
  "query": "meeting notes"
}
```

**Response:**
```json
{
  "blocks": [
    {
      "id": "block1",
      "type": "paragraph",
      "text": "Meeting notes from Monday...",
      "page_id": "page_xyz",
      "page_title": "Weekly Standup"
    }
  ],
  "count": 1
}
```

#### `blocks/unchecked_todos`

Get all unchecked to-do blocks in an act.

**Request:**
```json
{
  "act_id": "act_abc123"
}
```

**Response:**
```json
{
  "todos": [
    {
      "id": "todo1",
      "text": "Review PR #42",
      "page_id": "page_xyz",
      "page_title": "Sprint Tasks"
    },
    {
      "id": "todo2",
      "text": "Update documentation",
      "page_id": "page_abc",
      "page_title": "Q1 Goals"
    }
  ],
  "count": 2
}
```

## Error Codes

| Code | Meaning |
|------|---------|
| `-32602` | Invalid params (block not found, invalid type, etc.) |

## Usage Examples

### Creating a Page with Content

```typescript
// 1. Create the page block
const pageResult = await kernelRequest("blocks/create", {
  type: "page",
  act_id: "act_abc123",
  properties: { icon: "📝" }
});
const pageId = pageResult.block.id;

// 2. Add a heading
await kernelRequest("blocks/create", {
  type: "heading_1",
  act_id: "act_abc123",
  page_id: pageId,
  position: 0,
  rich_text: [{ content: "Meeting Notes" }]
});

// 3. Add a todo list
const todoParent = await kernelRequest("blocks/create", {
  type: "to_do",
  act_id: "act_abc123",
  page_id: pageId,
  position: 1,
  rich_text: [{ content: "Action items" }],
  properties: { checked: false }
});

// 4. Add nested todo items
await kernelRequest("blocks/create", {
  type: "to_do",
  act_id: "act_abc123",
  parent_id: todoParent.block.id,
  rich_text: [{ content: "Follow up with team" }],
  properties: { checked: false }
});
```

### Loading and Rendering a Page

```typescript
// Load the full block tree
const result = await kernelRequest("blocks/page/tree", {
  page_id: "page_xyz789"
});

// Render recursively
function renderBlock(block: Block): JSX.Element {
  const children = block.children?.map(renderBlock);

  switch (block.type) {
    case "heading_1":
      return <h1>{block.rich_text.map(renderSpan)}</h1>;
    case "paragraph":
      return <p>{block.rich_text.map(renderSpan)}</p>;
    case "bulleted_list":
      return <li>{block.rich_text.map(renderSpan)}<ul>{children}</ul></li>;
    // ... other types
  }
}
```

### Updating Todo Status

```typescript
// Toggle a todo checkbox
await kernelRequest("blocks/property/set", {
  block_id: "todo_block_123",
  key: "checked",
  value: true
});
```

### Drag and Drop Reordering

```typescript
// After drop, send new order
await kernelRequest("blocks/reorder", {
  block_ids: ["block3", "block1", "block2"]
});
```

## Database Schema

Blocks are stored in SQLite with these tables:

```sql
-- Main blocks table
CREATE TABLE blocks (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  act_id TEXT NOT NULL REFERENCES acts(id),
  parent_id TEXT REFERENCES blocks(id),
  page_id TEXT,
  scene_id TEXT REFERENCES scenes(id),
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Rich text spans
CREATE TABLE rich_text (
  id TEXT PRIMARY KEY,
  block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  content TEXT NOT NULL,
  bold INTEGER NOT NULL DEFAULT 0,
  italic INTEGER NOT NULL DEFAULT 0,
  strikethrough INTEGER NOT NULL DEFAULT 0,
  code INTEGER NOT NULL DEFAULT 0,
  underline INTEGER NOT NULL DEFAULT 0,
  color TEXT,
  background_color TEXT,
  link_url TEXT
);

-- Block properties
CREATE TABLE block_properties (
  block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (block_id, key)
);
```

## Block Relationships (Memory Graph)

Blocks can be connected via typed relationships, enabling semantic navigation and memory retrieval. This extends the vertical parent-child hierarchy with horizontal connections.

### Relationship Types

| Category | Types | Description |
|----------|-------|-------------|
| **Logical** | `references`, `follows_from`, `contradicts`, `supports` | Reasoning connections |
| **Semantic** | `similar_to`, `related_to`, `elaborates` | Content similarity |
| **Causal** | `caused_by`, `causes` | Event chains |
| **Feedback** | `corrects`, `supersedes`, `derived_from` | Learning signals |
| **Temporal** | `preceded_by`, `responds_to` | Conversation flow |

### Relationship Schema

```sql
CREATE TABLE block_relationships (
    id TEXT PRIMARY KEY,
    source_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    target_block_id TEXT NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,        -- 0.0-1.0
    weight REAL DEFAULT 1.0,            -- For graph algorithms
    source TEXT NOT NULL,               -- 'user', 'cairn', 'inferred', 'feedback', 'embedding'
    created_at TEXT NOT NULL,
    UNIQUE(source_block_id, target_block_id, relationship_type)
);
```

### RPC Endpoints

| Endpoint | Description |
|----------|-------------|
| `memory/relationships/create` | Create a relationship |
| `memory/relationships/list` | List relationships for a block |
| `memory/relationships/delete` | Delete a relationship |
| `memory/related` | Graph traversal from a block |

See [Memory System](./memory-system.md) for full documentation.

---

## Block Embeddings (Semantic Search)

Blocks can have vector embeddings for semantic similarity search:

```sql
CREATE TABLE block_embeddings (
    block_id TEXT PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,            -- 384-dim float32
    embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
    content_hash TEXT NOT NULL,         -- For staleness detection
    created_at TEXT NOT NULL
);
```

### RPC Endpoints

| Endpoint | Description |
|----------|-------------|
| `memory/search` | Semantic search with optional graph expansion |
| `memory/index/block` | Generate embedding for a block |
| `memory/index/batch` | Batch index multiple blocks |

See [Memory System](./memory-system.md) for full documentation.

---

## Related Documentation

- [The Play](./the-play.md) - Overview of the Play system
- [CAIRN Architecture](./cairn_architecture.md) - AI assistant integration
- [Memory System](./memory-system.md) - Relationship graph and semantic search
