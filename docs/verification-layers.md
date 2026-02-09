# Verification Layers

> **The five-layer verification system for atomic operations.**

Every atomic operation must pass through verification layers before execution. This extends RIVA's original 4-layer system (Syntax, Semantic, Behavioral, Intent) with an explicit Safety layer.

---

## Overview

```
Atomic Operation
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VERIFICATION PIPELINE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 1: SYNTAX ──────────────────────────────────────────────▶│
│           Is the command/code structurally valid?                │
│           ├─ Shell syntax (bash/sh)                              │
│           ├─ Python syntax (AST parse)                           │
│           └─ File path validity                                  │
│                                                                  │
│  Layer 2: SEMANTIC ────────────────────────────────────────────▶│
│           Does it make logical sense in context?                 │
│           ├─ Referenced files exist                              │
│           ├─ Dependencies available                              │
│           └─ Arguments valid for operation type                  │
│                                                                  │
│  Layer 3: BEHAVIORAL ──────────────────────────────────────────▶│
│           Will it produce expected side effects?                 │
│           ├─ Dry-run where possible                              │
│           ├─ Output prediction                                   │
│           └─ Resource requirements check                         │
│                                                                  │
│  Layer 4: SAFETY ──────────────────────────────────────────────▶│
│           Is it safe to execute?                                 │
│           ├─ Dangerous pattern blocklist                         │
│           ├─ Permission requirements                             │
│           └─ Resource limit checks                               │
│                                                                  │
│  Layer 5: INTENT ──────────────────────────────────────────────▶│
│           Does it match what the user actually wanted?           │
│           ├─ Classification confidence threshold                 │
│           ├─ User feedback history                               │
│           └─ Semantic similarity to request                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
   Execution (if all layers pass)
```

---

## Layer 1: Syntax Verification

**Purpose:** Ensure the command or code is structurally valid before attempting execution.

### Checks by Operation Type

| Operation Type | Syntax Check | Tool |
|----------------|--------------|------|
| Shell command | Valid bash/sh syntax | `bash -n` |
| Python code | Valid Python AST | `ast.parse()` |
| File path | Valid path format | Regex + OS check |
| JSON/YAML | Valid structure | Parser |

### Implementation

```python
def _verify_syntax(content: str, destination: str, consumer: str) -> VerificationResult:
    """Layer 1: Syntax verification."""

    if destination == 'process' or consumer == 'machine':
        if _looks_like_shell(content):
            valid, issues = _verify_shell_syntax(content)
        elif _looks_like_python(content):
            valid, issues = _verify_python_syntax(content)
        else:
            valid, issues = True, []  # Fallback: assume valid

    elif destination == 'file':
        valid, issues = _verify_file_path_syntax(content)

    else:
        valid, issues = True, []  # Stream content: any syntax OK

    return VerificationResult(
        layer='syntax',
        passed=valid,
        confidence=1.0 if valid else 0.0,
        issues_found=issues
    )
```

### Failure Response

If syntax verification fails:
- Operation is **rejected immediately**
- No further layers are checked
- User receives specific syntax error feedback

---

## Layer 2: Semantic Verification

**Purpose:** Ensure the operation makes logical sense given the current system state.

### Checks

| Check | Description | Example |
|-------|-------------|---------|
| File existence | Referenced files exist | `edit auth.py` → `auth.py` exists? |
| Dependency availability | Required tools/packages present | `pytest` → pytest installed? |
| Argument validity | Arguments match expected types | File path vs. directory |
| Context consistency | Operation fits current context | Edit function that exists |

### Implementation

```python
def _verify_semantic(content: str, destination: str, consumer: str, context: dict) -> VerificationResult:
    """Layer 2: Semantic verification."""
    issues = []

    # Check referenced files
    files = _extract_file_references(content)
    for f in files:
        if not os.path.exists(f):
            issues.append(f"File not found: {f}")

    # Check commands exist
    commands = _extract_commands(content)
    for cmd in commands:
        if not shutil.which(cmd):
            issues.append(f"Command not found: {cmd}")

    # Check context-specific requirements
    if destination == 'file':
        parent = os.path.dirname(_extract_target_path(content))
        if parent and not os.path.isdir(parent):
            issues.append(f"Parent directory does not exist: {parent}")

    return VerificationResult(
        layer='semantic',
        passed=len(issues) == 0,
        confidence=1.0 - (len(issues) * 0.2),
        issues_found=issues
    )
```

---

## Layer 3: Behavioral Verification

**Purpose:** Predict and verify the side effects of the operation.

### Checks

| Check | Description | Method |
|-------|-------------|--------|
| Dry-run | Execute without side effects | `--dry-run` flags |
| Output prediction | Expected output format | Pattern matching |
| Resource estimation | CPU/memory/disk requirements | Heuristics |
| Duration estimate | Expected execution time | Historical data |

### Applicable Operations

Behavioral verification applies primarily to:
- `interpret` semantics — analysis operations
- `execute` semantics — side-effecting operations

Read-only operations (`read` semantics) may skip this layer.

### Implementation

```python
def _verify_behavioral(content: str, destination: str, consumer: str, context: dict) -> VerificationResult:
    """Layer 3: Behavioral verification."""
    issues = []

    # Try dry-run if available
    if destination == 'process':
        dry_run_result = _attempt_dry_run(content)
        if dry_run_result.exit_code != 0:
            issues.append(f"Dry-run failed: {dry_run_result.stderr}")

    # Check resource requirements
    estimated_resources = _estimate_resources(content)
    available = _get_available_resources()

    if estimated_resources.memory > available.memory * 0.8:
        issues.append("Operation may exceed available memory")

    if estimated_resources.duration > context.get('timeout', 120):
        issues.append(f"Operation may exceed timeout ({context.get('timeout')}s)")

    return VerificationResult(
        layer='behavioral',
        passed=len(issues) == 0,
        confidence=0.8 if len(issues) == 0 else 0.5,
        issues_found=issues
    )
```

---

## Layer 4: Safety Verification

**Purpose:** Prevent dangerous or destructive operations.

### Blocked Patterns

```python
BLOCKED_PATTERNS = [
    # Destructive file operations
    r"rm\s+-rf\s+/\s*$",           # rm -rf /
    r"rm\s+-rf\s+/\*",              # rm -rf /*
    r"rm\s+-rf\s+~\s*$",            # rm -rf ~

    # Disk operations
    r"dd\s+if=.*of=/dev/sd",        # dd to disk
    r"mkfs\s+/dev/sd",              # format disk

    # Fork bombs and system damage
    r":\(\)\s*\{.*\}",              # fork bombs
    r"chmod\s+-R\s+777\s+/",        # world-writable root

    # Credential theft
    r"cat\s+.*\.ssh/",              # SSH key access
    r"cat\s+/etc/shadow",           # Password file
]
```

### Permission Checks

| Permission Level | Requires | Example |
|------------------|----------|---------|
| Normal | No special | `ls`, `cat file.txt` |
| Elevated | User confirmation | `sudo apt install` |
| Dangerous | Explicit approval + reason | `rm -rf directory/` |
| Blocked | Never allowed | `rm -rf /` |

### Rate Limits

| Resource | Default Limit | Tunable Range |
|----------|---------------|---------------|
| Sudo commands/session | 10 | 1-20 |
| Auth attempts/minute | 5 | N/A |
| Command max length | 8KB | 1-16KB |
| Max run time | 5 minutes | 1-30 minutes |
| Max iterations/task | 10 | 3-50 |

### Implementation

```python
def _verify_safety(content: str, destination: str, consumer: str, semantics: str, context: dict) -> VerificationResult:
    """Layer 4: Safety verification."""
    issues = []

    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, content):
            issues.append(f"Blocked pattern detected: {pattern}")

    # Check permission requirements
    if 'sudo' in content:
        session_sudo_count = context.get('session_sudo_count', 0)
        if session_sudo_count >= 10:
            issues.append("Sudo limit reached for this session")

    # Check resource limits
    if semantics == 'execute' and destination == 'process':
        if len(content) > 8192:
            issues.append("Command exceeds maximum length")

    return VerificationResult(
        layer='safety',
        passed=len(issues) == 0,
        confidence=1.0 if len(issues) == 0 else 0.0,
        issues_found=issues
    )
```

---

## Layer 5: Intent Verification

**Purpose:** Verify the operation matches what the user actually wanted.

### Checks

| Check | Method | Threshold |
|-------|--------|-----------|
| Classification confidence | ML classifier output | > 0.7 |
| Semantic similarity | Embedding cosine distance | > 0.8 |
| User feedback history | Historical corrections | Pattern match |
| Coherence with identity | CAIRN coherence kernel | > 0.0 |

### Implementation

```python
def _verify_intent(operation_id: str, content: str, context: dict) -> VerificationResult:
    """Layer 5: Intent verification."""
    issues = []

    # Get classification confidence
    classification = _get_classification(operation_id)
    if not classification.confident:
        issues.append("Classification marked as uncertain by LLM")

    # Check semantic similarity to original request
    original_request = _get_original_request(operation_id)
    similarity = _compute_semantic_similarity(original_request, content)
    if similarity < 0.8:
        issues.append(f"Low semantic similarity to request: {similarity}")

    # Check against user feedback patterns
    user_id = context.get('user_id')
    if _matches_correction_pattern(user_id, classification):
        issues.append("Similar classifications were corrected by user")

    # Compute confidence based on similarity and classification confidence
    confidence = similarity if classification.confident else similarity * 0.5

    return VerificationResult(
        layer='intent',
        passed=len(issues) == 0,
        confidence=confidence,
        issues_found=issues
    )
```

---

## Verification Flow Control

### Early Exit

Verification stops on first critical failure:

1. **Syntax failure** → Reject immediately
2. **Safety failure** → Reject immediately
3. **Semantic/Behavioral/Intent failure** → Continue with warnings

### Confidence Aggregation

Overall verification confidence is computed as:

```python
def aggregate_confidence(results: dict[str, VerificationResult]) -> float:
    """Aggregate verification confidence across layers."""

    # Critical layers must pass
    if not results.get('syntax', {}).passed:
        return 0.0
    if not results.get('safety', {}).passed:
        return 0.0

    # Other layers contribute to confidence
    weights = {
        'syntax': 0.2,
        'semantic': 0.2,
        'behavioral': 0.2,
        'safety': 0.2,
        'intent': 0.2
    }

    total = sum(
        results[layer].confidence * weight
        for layer, weight in weights.items()
        if layer in results
    )

    return total
```

### User Approval Thresholds

| Confidence | Action |
|------------|--------|
| > 0.9 | Auto-execute (if user preference allows) |
| 0.7 - 0.9 | Execute with notification |
| 0.5 - 0.7 | Request user confirmation |
| < 0.5 | Reject with explanation |

---

## Database Schema

```sql
CREATE TABLE operation_verification (
    id TEXT PRIMARY KEY,
    operation_block_id TEXT NOT NULL,

    verification_layer TEXT NOT NULL,   -- 'syntax', 'semantic', 'behavioral', 'safety', 'intent'
    required BOOLEAN NOT NULL,

    passed BOOLEAN,
    confidence REAL,
    issues_found JSON,
    execution_time_ms INTEGER,

    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (operation_block_id) REFERENCES atomic_operations(block_id),

    CHECK (verification_layer IN ('syntax', 'semantic', 'behavioral', 'safety', 'intent'))
);
```

---

## Relationship to RIVA's 4-Layer System

This 5-layer system extends RIVA's original verification approach:

| RIVA Layer | V2 Layer | Notes |
|------------|----------|-------|
| Syntax | Syntax | Same: tree-sitter parsing |
| Semantic | Semantic | Same: static analysis |
| Behavioral | Behavioral | Same: pytest/runtime checks |
| Intent | Intent | Same: LLM judge (when active) |
| — | **Safety** | **New**: Explicit safety checks |

The addition of an explicit Safety layer makes dangerous operation blocking a first-class concern rather than embedding it within other layers.

---

## Related Documentation

- [Foundation](./FOUNDATION.md) — Core philosophy
- [Atomic Operations](./atomic-operations.md) — Classification system
- [RLHF Learning](./rlhf-learning.md) — Learning from verification failures
- [Execution Engine](./execution-engine.md) — Post-verification execution
