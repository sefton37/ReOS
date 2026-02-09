# RLHF Learning System

> **How Talking Rock learns from user feedback at multiple levels.**

The RLHF (Reinforcement Learning from Human Feedback) system captures user feedback to continuously improve classification accuracy and operation quality.

---

## Feedback Hierarchy

Feedback is collected at three levels, each with different reliability:

```
┌─────────────────────────────────────────────────────────────────┐
│                    FEEDBACK HIERARCHY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                    ▲ Correction                                 │
│                   /│\   (Highest Value)                         │
│                  / │ \  • User provides correct classification  │
│                 /  │  \ • Optional reasoning                    │
│                /   │   \• Becomes training data                 │
│               ──────────────────────                             │
│              /     │     \                                      │
│             /   Approval   \                                    │
│            /  (Medium Value) \                                  │
│           /    • Accept/reject \                                │
│          /     • Quick signal   \                               │
│         /      • Time to decision \                             │
│        ──────────────────────────                               │
│       /          │              \                               │
│      /       Rejection          \                               │
│     /      (Low Value)           \                              │
│    /       • Simple no            \                             │
│   /        • No detail             \                            │
│  ──────────────────────────────────                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Feedback Types

### 1. Correction

User corrects a classification error. **Most valuable feedback.**

```python
collect_correction(
    operation_id: str,
    user_id: str,
    system_classification: dict,    # What system chose
    user_corrected_classification: dict,  # What it should be
    reasoning: str = None           # Why user made this correction
)
```

**Value:** Highest
- Direct signal about classification error
- Becomes training data for few-shot examples
- Reasoning provides context for future classifications

**Example:**
```python
collector.collect_correction(
    operation_id='op-123',
    user_id='user-1',
    system_classification={
        'destination': 'file',
        'consumer': 'human',
        'semantics': 'read'
    },
    user_corrected_classification={
        'destination': 'process',
        'consumer': 'machine',
        'semantics': 'execute'
    },
    reasoning='This was checking memory, not reading a file'
)
```

### 2. Approval

User approves the proposed operation.

```python
collect_approval(
    operation_id: str,
    user_id: str,
    approved: bool
)
```

**Value:** Medium
- Positive signal that classification was acceptable
- Can be used to populate few-shot examples
- Quick feedback loop (immediate)

### 3. Rejection

User rejects the proposed operation.

```python
collect_rejection(
    operation_id: str,
    user_id: str
)
```

**Value:** Low
- Negative signal, but no corrective information
- Indicates classification may be wrong, but doesn't specify how
- Should prompt for correction feedback if possible

---

## Feedback Collection Flow

```
Operation Execution
        │
        ▼
┌───────────────────┐
│ Awaiting Approval │ ──────────────────────────────────────┐
└─────────┬─────────┘                                       │
          │                                                 │
          ▼                                                 │
    ┌─────────────┐     ┌────────────────────┐              │
    │   Approve   │────▶│ collect_approval() │              │
    │   [y/n]     │     │ time_to_decision   │              │
    └──────┬──────┘     └────────────────────┘              │
           │                                                │
           ▼                                                │
    ┌──────────────┐                                        │
    │ Executed     │                                        │
    └──────┬───────┘                                        │
           │                                                │
     ┌─────┴─────┐                                          │
     │           │                                          │
     ▼           ▼                                          │
┌─────────┐ ┌─────────┐    ┌─────────────────────────┐      │
│  Undo   │ │  Retry  │───▶│ collect_behavioral()    │      │
│         │ │         │    └─────────────────────────┘      │
└────┬────┘ └────┬────┘                                     │
     │           │                                          │
     ▼           ▼                                          │
┌─────────────────────────────────────────────────┐         │
│              Days/Weeks Later                    │         │
│  ┌─────────────────────────────────────────┐    │         │
│  │ collect_long_term_outcome()             │    │         │
│  │ - operation_persisted                    │    │         │
│  │ - reused_pattern                         │    │         │
│  └─────────────────────────────────────────┘    │         │
└─────────────────────────────────────────────────┘         │
                                                            │
┌───────────────────────────────────────────────────────────┘
│ Optional: User provides correction or rating
│  ┌─────────────────────────────────────────┐
│  │ collect_correction()                    │
│  │ collect_explicit_rating()               │
│  └─────────────────────────────────────────┘
└───────────────────────────────────────────────────────────
```

---

## Learning Metrics

### Classification Accuracy

Tracks how often system classifications match user expectations.

```python
def compute_learning_metrics(user_id: str, window_days: int = 7) -> dict:
    """Compute metrics over time window."""

    return {
        'approval_rate': approvals / total,
        'correction_rate': corrections / total,
        'rejection_rate': rejections / total,
        'by_destination_type': {
            'stream': 0.92,
            'file': 0.85,
            'process': 0.78
        },
        'by_consumer_type': {...},
        'by_execution_semantics': {...}
    }
```

### Improvement Tracking

Compares current window to previous window:

```python
{
    'approval_rate': 0.85,
    'previous_value': 0.80,
    'improvement': 0.05,  # +5%
}
```

---

## Feedback Quality Evaluation

### Informativeness Score

How detailed is the feedback?

```python
informativeness_score = corrections_with_reasoning / total_corrections
```

**Higher is better** — corrections with reasoning are more valuable for training.

---

## Database Schema

### User Feedback Table

```sql
CREATE TABLE user_feedback (
    id TEXT PRIMARY KEY,
    operation_block_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Feedback type
    feedback_type TEXT NOT NULL,        -- 'correction', 'approval', 'rejection'

    -- Correction feedback
    system_classification JSON,
    user_corrected_classification JSON,
    correction_reasoning TEXT,

    -- Approval/rejection feedback
    approved BOOLEAN,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (operation_block_id) REFERENCES atomic_operations(block_id),

    CHECK (feedback_type IN ('correction', 'approval', 'rejection'))
);
```

### Learning Metrics Table

```sql
CREATE TABLE rlhf_learning_metrics (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,          -- 'approval_rate', 'correction_rate', etc.

    -- Time window
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    window_size_days INTEGER NOT NULL,

    -- Metric value
    metric_value REAL NOT NULL,
    sample_size INTEGER NOT NULL,

    -- Breakdown by category
    by_destination_type JSON,
    by_consumer_type JSON,
    by_execution_semantics JSON,

    -- Comparison to previous window
    previous_value REAL,
    improvement REAL,

    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Few-Shot Example Generation

Feedback is used to generate few-shot examples for LLM classification:

### Example Selection View

```sql
CREATE VIEW few_shot_examples AS
SELECT
    ao.user_request,
    ao.destination_type,
    ao.consumer_type,
    ao.execution_semantics,
    cr.reasoning,
    uf.approved,
    uf.user_corrected_classification

FROM atomic_operations ao
LEFT JOIN classification_reasoning cr
    ON ao.block_id = cr.operation_block_id
LEFT JOIN user_feedback uf
    ON ao.block_id = uf.operation_block_id

WHERE
    -- Approved classifications
    (uf.feedback_type = 'approval' AND uf.approved = 1)
    OR
    -- Corrected classifications (use the correction, not original)
    (uf.feedback_type = 'correction')

ORDER BY ao.created_at DESC;
```

### Example Quality

High-quality few-shot examples have:

1. **User approval** — Explicitly approved by user
2. **Reasoning** — LLM provided clear reasoning
3. **Confident classification** — `classification_confident = 1`
4. **No corrections** — User didn't need to fix it

Lower-quality but still useful:

1. **Corrected classifications** — Use the corrected version, not original
2. **Reasoning from user** — User provided explanation during correction

---

## Privacy Considerations

All learning happens **locally**:
- Feedback never leaves the user's machine
- No aggregation across users
- User can delete all feedback data
- Models trained on user's own data only

---

## Related Documentation

- [Foundation](./FOUNDATION.md) — Core philosophy (privacy by architecture)
- [Atomic Operations](./atomic-operations.md) — What gets classified
- [Classification](./classification.md) — LLM-native classification approach
- [Verification Layers](./verification-layers.md) — Verification that produces feedback opportunities
