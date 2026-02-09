# LLM-Native Classification

> **How atomic operations are classified using LLMs with few-shot learning.**

Classification in ReOS is LLM-native, not ML/SentenceTransformer-based. The system uses structured prompts with few-shot examples to classify user requests into the 3x2x3 taxonomy.

---

## Architecture

### Classification Flow

```
User Request: "Check memory usage and optimize auth.py"
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LLM CLASSIFICATION                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  1. CONTEXT BUILDING                                       │ │
│  │     • Load few-shot examples from database                 │ │
│  │     • Select similar examples (if available)               │ │
│  │     • Build structured prompt with taxonomy explanation    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  2. LLM INVOCATION                                         │ │
│  │     Submit to Ollama with JSON schema:                     │ │
│  │     {                                                      │ │
│  │       "destination_type": "stream" | "file" | "process",   │ │
│  │       "consumer_type": "human" | "machine",                │ │
│  │       "execution_semantics": "read" | "interpret" | ...    │ │
│  │       "confident": bool,                                   │ │
│  │       "reasoning": str                                     │ │
│  │     }                                                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  3. RESPONSE PARSING                                       │ │
│  │     • Parse JSON response                                  │ │
│  │     • Extract classification dimensions                    │ │
│  │     • Extract confident flag                               │ │
│  │     • Store reasoning for audit trail                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌──────────────────────────┐
              │   Classification         │
              │   destination: file      │
              │   consumer: human        │
              │   semantics: execute     │
              │   confident: true        │
              │   reasoning: "..."       │
              └──────────────────────────┘
```

---

## Few-Shot Context

### Example Selection

The system maintains a database of high-quality classification examples. When classifying a new request:

1. **Load approved examples** — Classifications that were user-approved
2. **Select relevant examples** — (Future) Use similarity search to find related examples
3. **Build few-shot prompt** — Include 5-10 examples in the prompt

### Example Format

```python
EXAMPLE_CLASSIFICATIONS = [
    {
        "request": "show memory usage",
        "destination_type": "stream",
        "consumer_type": "human",
        "execution_semantics": "read",
        "reasoning": "Display system info to user"
    },
    {
        "request": "save notes to file.txt",
        "destination_type": "file",
        "consumer_type": "human",
        "execution_semantics": "execute",
        "reasoning": "Persist data to disk"
    },
    # ... more examples
]
```

### Storage

Examples are stored in the `classification_reasoning` table and retrieved based on user approval feedback.

```sql
-- Query approved classifications for few-shot context
SELECT user_request, destination_type, consumer_type, execution_semantics
FROM atomic_operations
WHERE status = 'complete'
  AND classification_confident = 1
ORDER BY created_at DESC
LIMIT 10;
```

---

## Confidence Detection

### The `confident` Field

Unlike the old `confidence: float` (0.0-1.0), the new system uses `confident: bool`:

- **`confident: true`** — LLM has high certainty, proceed with classification
- **`confident: false`** — LLM is uncertain, may need decomposition or user clarification

### When LLMs Report Low Confidence

The LLM may report `confident: false` when:

- Request is ambiguous ("do the thing")
- Multiple valid interpretations exist ("check the logs" — read or interpret?)
- Complex multi-step request ("analyze code and deploy if tests pass")
- Unfamiliar domain or terminology

### Handling Low Confidence

When `confident: false`:

1. **Attempt decomposition** — Break into simpler sub-operations
2. **Request clarification** — Ask user to disambiguate
3. **Fall back to safe defaults** — Conservative classification (e.g., `stream, human, read`)

---

## Classification Schema

### JSON Response Format

```json
{
  "destination_type": "stream",
  "consumer_type": "human",
  "execution_semantics": "read",
  "confident": true,
  "reasoning": "User is asking to display system information for immediate viewing"
}
```

### Validation

The system validates LLM responses against the schema:

```python
class Classification:
    destination_type: Literal["stream", "file", "process"]
    consumer_type: Literal["human", "machine"]
    execution_semantics: Literal["read", "interpret", "execute"]
    confident: bool
    reasoning: str
```

If the LLM returns invalid JSON or missing fields, the system falls back to safe defaults and logs the error.

---

## Database Schema

### Classification Storage (v2)

```sql
CREATE TABLE atomic_operations (
    block_id TEXT PRIMARY KEY,
    user_request TEXT NOT NULL,

    -- Classification result
    destination_type TEXT,
    consumer_type TEXT,
    execution_semantics TEXT,
    classification_confident INTEGER,  -- 0 or 1 (boolean)

    -- ... other fields
);

CREATE TABLE classification_reasoning (
    id TEXT PRIMARY KEY,
    operation_block_id TEXT NOT NULL,
    pass_number INTEGER NOT NULL,

    -- LLM reasoning
    reasoning TEXT NOT NULL,
    destination_type TEXT,
    consumer_type TEXT,
    execution_semantics TEXT,
    confident INTEGER NOT NULL,  -- 0 or 1

    FOREIGN KEY (operation_block_id) REFERENCES atomic_operations(block_id)
);
```

**Note:** The `ml_features` table was removed in schema v2. No embeddings or ML features are extracted.

---

## Learning from Feedback

### Approval Feedback

When users approve a classification, it becomes a candidate for few-shot examples:

```python
# User approves operation
collect_feedback(
    operation_id='op-123',
    feedback_type='approval',
    approved=True
)

# Classification is now eligible for few-shot context
```

### Correction Feedback

When users correct a classification, the system:

1. Stores the correction in `user_feedback` table
2. Uses the corrected classification for future few-shot examples
3. Downgrades the original classification (won't be used in examples)

```python
collect_feedback(
    operation_id='op-123',
    feedback_type='correction',
    corrected_classification={
        'destination_type': 'process',  # Was 'file'
        'consumer_type': 'machine',
        'execution_semantics': 'execute'
    },
    reasoning='This spawns a system process, not a file write'
)
```

### Rejection Feedback

Rejected classifications are flagged and excluded from few-shot examples:

```python
collect_feedback(
    operation_id='op-123',
    feedback_type='rejection'
)
```

---

## Implementation Location

**Key file:** `src/reos/atomic_ops/classification_context.py`

This module handles:
- Loading few-shot examples from the database
- Building structured prompts for the LLM
- Parsing and validating LLM responses
- Storing classification reasoning

---

## Performance

### Classification Time

| Component | Time | Notes |
|-----------|------|-------|
| Context building | < 10ms | Database query for examples |
| LLM inference | ~ 500-1500ms | Depends on model size (1-3B) |
| Response parsing | < 5ms | JSON validation |
| **Total** | ~ 500-1500ms | Acceptable for interactive use |

### Accuracy

LLM-native classification accuracy (estimated):

- **Simple requests:** 95%+ ("show memory", "save to file")
- **Moderate requests:** 85-90% ("check if service is running")
- **Complex requests:** 70-80% ("analyze code and optimize if needed")

Accuracy improves over time as few-shot examples accumulate from user feedback.

---

## Migration from ML-Based Classification

The system previously used:

- **sentence-transformers** for embeddings
- **FeatureExtractor** for lexical/syntactic features
- **cosine_similarity** for example matching
- **confidence: float** scoring

All of this was removed in favor of:

- **LLM-native classification** with structured prompts
- **confident: bool** flag
- **Few-shot learning** from approved examples
- **Direct reasoning** from the LLM

This simplifies the architecture, reduces dependencies, and leverages the LLM's native language understanding.

---

## Related Documentation

- [Atomic Operations](./atomic-operations.md) — The 3x2x3 taxonomy
- [RLHF Learning](./rlhf-learning.md) — How feedback improves classification
- [Verification Layers](./verification-layers.md) — Post-classification verification
