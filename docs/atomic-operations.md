# Atomic Operations

> **The 3x2x3 taxonomy for classifying every user request.**

Atomic operations are the fundamental units of work in Talking Rock. Every user request is decomposed into one or more atomic operations, each classified along three dimensions.

---

## The 3x2x3 Taxonomy

Every atomic operation is classified by three independent dimensions:

### 1. Destination Type (Where does output go?)

| Value | Description | Examples |
|-------|-------------|----------|
| `stream` | Ephemeral output, displayed once | Chat response, terminal output |
| `file` | Persistent storage | Save to disk, database write |
| `process` | Spawns a system process | Run command, start service |

### 2. Consumer Type (Who consumes the result?)

| Value | Description | Examples |
|-------|-------------|----------|
| `human` | Human reads and interprets | Natural language response, formatted output |
| `machine` | Machine processes further | JSON output, exit code, structured data |

### 3. Execution Semantics (What action is taken?)

| Value | Description | Examples |
|-------|-------------|----------|
| `read` | Retrieve existing data | Query file, list processes, fetch calendar |
| `interpret` | Analyze or transform data | Parse code, verify syntax, check health |
| `execute` | Perform side-effecting action | Write file, run command, create event |

---

## Classification Examples

| User Request | Destination | Consumer | Semantics | Reasoning |
|--------------|-------------|----------|-----------|-----------|
| "What's my memory usage?" | stream | human | read | Display info to user |
| "Save this to notes.txt" | file | human | execute | Persist for human consumption |
| "Run pytest" | process | machine | execute | Spawn process, machine checks result |
| "Check if auth.py has errors" | stream | machine | interpret | Analysis for verification |
| "Show my calendar" | stream | human | read | Display events to user |
| "Create a scene for tomorrow" | file | human | execute | Persist to database |
| "Is nginx running?" | stream | human | read | Check and display status |
| "Restart nginx" | process | machine | execute | Spawn process to restart |

---

## The Classification Pipeline

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CLASSIFICATION PIPELINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  1. FEW-SHOT CONTEXT BUILDING                             │   │
│  │     • Load example classifications from database          │   │
│  │     • Select relevant examples using similarity search    │   │
│  │     • Build few-shot prompt with examples                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                            │                                     │
│                            ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  2. LLM CLASSIFICATION                                    │   │
│  │     • Submit request + examples to LLM                    │   │
│  │     • Parse JSON response with classification             │   │
│  │     • Extract confident: bool flag                        │   │
│  │     • Extract reasoning from LLM                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                            │                                     │
│                            ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  3. DECOMPOSITION CHECK                                   │   │
│  │     If confident == false:                                │   │
│  │       → Attempt decomposition into sub-operations         │   │
│  │     If request contains "and", "then", "also":            │   │
│  │       → Decompose into sequential operations              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌──────────────────────────┐
              │   Atomic Operation       │
              │   block_id: op-uuid      │
              │   destination: file      │
              │   consumer: human        │
              │   semantics: execute     │
              │   confident: true        │
              └──────────────────────────┘
```

---

## Indicator Patterns

### Persistence Indicators (→ Destination)

```python
PERSISTENCE_PATTERNS = {
    'file_extension': r'\.(py|js|ts|md|txt|json|yaml|sh)$',
    'file_operations': ['create', 'write', 'save', 'modify', 'edit', 'update'],
    'system_resources': ['memory', 'cpu', 'disk', 'network', 'process', 'service'],
}
```

**Decision tree:**
- Has file extension OR file operation verb → `file`
- Mentions system resource → `process`
- Default → `stream`

### Consumer Indicators (→ Consumer)

```python
CONSUMER_PATTERNS = {
    'immediate_verbs': ['show', 'list', 'display', 'print', 'find', 'tell'],
    'code_patterns': [r'\.(py|js|ts|jsx|tsx|rs|go|java|cpp)'],
    'machine_verbs': ['run', 'execute', 'test', 'build', 'compile', 'deploy'],
}
```

**Decision tree:**
- Has immediate verb + no code → `human`
- Has code extension OR machine verb → `machine`
- Default → `human`

### Execution Indicators (→ Semantics)

```python
EXECUTION_PATTERNS = {
    'execute_verbs': ['run', 'execute', 'start', 'launch', 'install', 'deploy', 'create', 'write'],
    'interpret_verbs': ['analyze', 'check', 'test', 'validate', 'verify', 'parse', 'review'],
    'read_verbs': ['show', 'list', 'get', 'display', 'print', 'find', 'read', 'fetch'],
}
```

**Decision tree:**
- Verb in execute_verbs → `execute`
- Verb in interpret_verbs → `interpret`
- Verb in read_verbs → `read`
- Default → `interpret`

---

## Operation Decomposition

When a request contains multiple operations, it's decomposed:

**Example:** "Check memory usage and optimize auth.py"

```
Parent Operation (compound)
├── Child 1: "Check memory usage"
│   └── (stream, human, read)
└── Child 2: "optimize auth.py"
    └── (file, machine, interpret)
```

### Decomposition Triggers

1. **Conjunction patterns:** "and", "then", "also", "after that"
2. **Low confidence:** Classification confidence < 0.7
3. **Long description:** > 200 characters
4. **Multiple verbs:** More than 2 action verbs detected

### Decomposition Rules

- Each child must be more verifiable than parent
- Children are 2-5 sub-operations
- Each child has independent classification
- Parent tracks child IDs in `decomposed_into` field

---

## Database Schema

```sql
CREATE TABLE atomic_operations (
    block_id TEXT PRIMARY KEY,

    -- User input
    user_request TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Classification result
    destination_type TEXT,              -- 'stream', 'file', 'process'
    consumer_type TEXT,                 -- 'human', 'machine'
    execution_semantics TEXT,           -- 'read', 'interpret', 'execute'

    -- Classification metadata
    classification_confident INTEGER,      -- Boolean: 1 if LLM is confident, 0 otherwise
    classification_pass_number INTEGER DEFAULT 1,
    requires_decomposition BOOLEAN DEFAULT 0,

    -- Decomposition
    is_decomposed BOOLEAN DEFAULT 0,
    decomposed_from TEXT,               -- Parent operation if this is child
    decomposed_into JSON,               -- Array of child operation IDs

    -- Execution state
    status TEXT NOT NULL,               -- 'classifying', 'awaiting_approval',
                                        -- 'executing', 'complete', 'failed'

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (block_id) REFERENCES blocks(id) ON DELETE CASCADE,

    CHECK (destination_type IN ('stream', 'file', 'process') OR destination_type IS NULL),
    CHECK (consumer_type IN ('human', 'machine') OR consumer_type IS NULL),
    CHECK (execution_semantics IN ('read', 'interpret', 'execute') OR execution_semantics IS NULL)
);

CREATE TABLE classification_reasoning (
    id TEXT PRIMARY KEY,
    operation_block_id TEXT NOT NULL,
    pass_number INTEGER NOT NULL,

    -- Indicators detected
    persistence_indicators JSON NOT NULL,
    execution_indicators JSON NOT NULL,
    immediacy_indicators JSON NOT NULL,
    code_indicators JSON NOT NULL,

    -- Reasoning
    destination_type TEXT,
    consumer_type TEXT,
    execution_semantics TEXT,
    confidence REAL NOT NULL,

    -- Alternatives considered (for ML training)
    alternatives_considered JSON,

    FOREIGN KEY (operation_block_id) REFERENCES atomic_operations(block_id)
);
```

---

## Agent Mappings

### CAIRN Intent Categories → Atomic Operations

| CAIRN Category | Typical Operations |
|----------------|-------------------|
| `CALENDAR` query | `(stream, human, read)` |
| `CALENDAR` create | `(file, human, execute)` |
| `PLAY` list | `(stream, human, read)` |
| `PLAY` create/update | `(file, human, execute)` |
| `SYSTEM` info | `(stream, human, read)` |
| `CONTACTS` search | `(stream, human, read)` |

### ReOS Parse Gate → Atomic Operations

| Parse Gate Intent | Typical Operations |
|-------------------|-------------------|
| run program | `(process, machine, execute)` |
| install package | `(process, machine, execute)` |
| query status | `(stream, human, read)` |
| service control | `(process, machine, execute)` |

### RIVA Contracts → Atomic Operations

| Contract Step | Typical Operations |
|---------------|-------------------|
| Read file | `(stream, machine, read)` |
| Edit file | `(file, machine, execute)` |
| Run tests | `(process, machine, interpret)` |
| Generate code | `(file, machine, execute)` |

---

## Related Documentation

- [Foundation](./FOUNDATION.md) — Core philosophy
- [Verification Layers](./verification-layers.md) — How operations are verified
- [RLHF Learning](./rlhf-learning.md) — Learning from feedback
- [Classification](./classification.md) — LLM-native classification approach
