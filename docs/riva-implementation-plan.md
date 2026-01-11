# RIVA Performance Optimization: Implementation Plan

*A realistic, incremental plan to implement the 9 optimization strategies*

## Current State Assessment

### What Already Exists

**Core RIVA Algorithm** (`src/reos/code_mode/intention.py`):
- `can_verify_directly()` - Heuristic check for decomposition need
- `should_decompose()` - Trigger decomposition based on failures/unclear outcomes
- `decompose()` - LLM-based task decomposition
- `WorkContext` - Dependency injection through recursion
- Cycle/Action/Judgment data structures

**Project Memory** (`src/reos/code_mode/project_memory.py`):
- `ProjectDecision` - Stores project-level decisions
- `ProjectPattern` - Tracks recurring patterns
- `ProjectCorrection` - Learns from user modifications
- Database-backed persistence

**Configuration** (`src/reos/config.py`):
- `ExecutionBudgets` - max_iterations, max_operations
- `ContextLimits` - token budgets
- Environment variable overrides

**Quality Tracking** (`src/reos/code_mode/quality.py`):
- `QualityTier` enum (LLM_SUCCESS, HEURISTIC_FALLBACK, etc.)
- `QualityTracker` - Records execution quality events

### What's Missing

1. **Smart Decomposition Thresholds** - Current heuristics are basic
2. **Batch Verification** - Verify each step individually
3. **Confidence-Based Verification** - All actions verified equally
4. **Pattern Success Memory** - Patterns exist but not tied to success rates
5. **Trust Budget** - No session-level trust tracking
6. **Parallel Verification** - All verification is sequential
7. **Fast-Path Patterns** - No optimized handlers for common cases
8. **Model Selection** - Single model for all tasks
9. **Progressive Enhancement** - No two-pass generation

---

## Implementation Strategy

### Principle: Incremental Enhancement

We won't rewrite RIVA. We'll:
1. Add hooks to existing code
2. Create new modules that integrate cleanly
3. Make optimizations opt-in via config
4. Measure before optimizing

### Risk Assessment

| Strategy | Risk | Mitigation |
|----------|------|------------|
| Smart Decomposition | May under-decompose complex tasks | Keep fallback to current behavior |
| Batch Verification | May miss errors caught by individual checks | Log what would have been caught |
| Confidence-Based | May under-verify risky actions | Always verify HIGH risk |
| Pattern Memory | May over-trust failed patterns | Decay trust on failures |
| Trust Budget | May skip needed verification | Hard floor on trust budget |
| Parallel Verification | Race conditions | Use proper async primitives |
| Fast-Path | May misclassify patterns | Fall back to full RIVA |
| Model Selection | Wrong model for task | Default to capable model |
| Progressive Enhancement | User sees incomplete code | Clear "basic → enhanced" UX |

---

## Phase 1: Measurement & Hooks (Week 1-2)

**Goal:** Understand current behavior before optimizing.

### 1.1 Add Metrics Collection

Create `src/reos/code_mode/metrics.py`:

```python
@dataclass
class ExecutionMetrics:
    """Metrics for a single RIVA execution."""

    session_id: str
    started_at: datetime
    completed_at: datetime | None

    # Timing
    total_duration_ms: int
    llm_time_ms: int
    verification_time_ms: int

    # Counts
    llm_calls: int
    decomposition_count: int
    verification_count: int
    retry_count: int

    # Outcomes
    success: bool
    first_try_success: bool
    final_depth: int

    # What we could have skipped (for optimization analysis)
    skippable_decompositions: int  # Simple tasks that were decomposed
    skippable_verifications: int   # Low-risk actions that were verified
```

### 1.2 Add Timing Hooks

Modify `WorkContext` to include metrics collection:

```python
@dataclass
class WorkContext:
    # ... existing fields ...
    metrics: ExecutionMetrics | None = None

    def record_llm_call(self, duration_ms: int) -> None:
        if self.metrics:
            self.metrics.llm_calls += 1
            self.metrics.llm_time_ms += duration_ms
```

### 1.3 Baseline Measurement

Run existing test suite and real tasks, collect:
- Average LLM calls per task
- Average decomposition depth
- First-try success rate
- Time breakdown (LLM vs verification vs execution)

**Deliverable:** Dashboard or report showing current performance baseline.

---

## Phase 2: Smart Decomposition (Week 3-4)

**Goal:** Reduce unnecessary decomposition of simple tasks.

### 2.1 Create Task Complexity Analyzer

Create `src/reos/code_mode/complexity.py`:

```python
@dataclass
class TaskComplexity:
    """Analysis of task complexity."""

    score: float  # 0.0 (trivial) to 1.0 (complex)

    # Factors
    estimated_files: int
    estimated_functions: int
    has_external_deps: bool
    requires_tests: bool
    modifies_existing: bool
    scope_ambiguous: bool

    # Recommendation
    should_decompose: bool
    confidence: float
    reason: str

def analyze_complexity(
    what: str,
    acceptance: str,
    codebase_context: str | None = None,
) -> TaskComplexity:
    """Analyze task complexity to decide decomposition."""
    # Implementation uses heuristics + optional LLM
```

### 2.2 Integrate with `can_verify_directly()`

```python
def can_verify_directly(intention: Intention, ctx: WorkContext) -> bool:
    # NEW: Use complexity analyzer if available
    if ctx.complexity_analyzer:
        complexity = ctx.complexity_analyzer.analyze(
            intention.what,
            intention.acceptance,
        )

        # Simple, well-defined tasks: don't decompose
        if complexity.score < 0.3 and complexity.confidence > 0.7:
            ctx.metrics.skippable_decompositions += 1
            return True

    # Existing heuristics as fallback
    # ...
```

### 2.3 Tune Thresholds

- Start conservative (decompose more than needed)
- Track outcomes by complexity score
- Gradually raise threshold as we gain confidence

**Deliverable:** `complexity.py` module, integration with intention.py

---

## Phase 3: Confidence-Based Verification (Week 5-6)

**Goal:** Verify risky actions more, boilerplate less.

### 3.1 Create Risk Classifier

Create `src/reos/code_mode/risk.py`:

```python
class RiskLevel(Enum):
    LOW = "low"      # Boilerplate, well-tested patterns
    MEDIUM = "medium"  # Normal code changes
    HIGH = "high"    # Security, external APIs, destructive

@dataclass
class ActionRisk:
    """Risk assessment for an action."""

    level: RiskLevel
    factors: list[str]
    requires_verification: bool

def assess_risk(action: Action, context: str | None = None) -> ActionRisk:
    """Assess risk level of an action."""

    factors = []

    # HIGH risk indicators
    if action.type == ActionType.DELETE:
        factors.append("destructive_operation")
    if "rm " in action.content or "sudo" in action.content:
        factors.append("system_modification")
    if "password" in action.content.lower() or "secret" in action.content.lower():
        factors.append("security_sensitive")
    if "api" in action.content.lower() or "http" in action.content.lower():
        factors.append("external_dependency")

    # LOW risk indicators
    if action.type == ActionType.QUERY:
        factors.append("read_only")
    if _is_boilerplate(action.content):
        factors.append("boilerplate_pattern")

    # Determine level
    if any(f in ["destructive_operation", "security_sensitive", "system_modification"] for f in factors):
        level = RiskLevel.HIGH
    elif any(f in ["read_only", "boilerplate_pattern"] for f in factors):
        level = RiskLevel.LOW
    else:
        level = RiskLevel.MEDIUM

    return ActionRisk(
        level=level,
        factors=factors,
        requires_verification=(level != RiskLevel.LOW),
    )
```

### 3.2 Integrate with Action Execution

```python
def execute_action(action: Action, ctx: WorkContext) -> str:
    risk = assess_risk(action)

    if risk.level == RiskLevel.LOW and ctx.trust_budget.remaining > 50:
        # Execute without individual verification
        # Batch verify at end of intention
        result = ctx.sandbox.execute(action)
        ctx.deferred_verifications.append((action, result))
        return result

    # Normal verification flow
    result = ctx.sandbox.execute(action)
    verify_result(action, result, ctx)
    return result
```

**Deliverable:** `risk.py` module, modified execution flow

---

## Phase 4: Pattern Success Memory (Week 7-8)

**Goal:** Trust patterns that have worked before.

### 4.1 Extend ProjectMemory

Add to `project_memory.py`:

```python
@dataclass
class PatternSuccess:
    """Track success rate of execution patterns."""

    id: str
    pattern_hash: str  # Hash of (action_type, target_pattern, content_pattern)
    description: str

    # Statistics
    attempts: int
    successes: int
    failures: int
    last_success: datetime | None
    last_failure: datetime | None

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.5  # Prior: assume 50%
        return self.successes / self.attempts

    @property
    def trust_level(self) -> float:
        """Trust level based on success rate and recency."""
        base = self.success_rate

        # Decay for lack of recent success
        if self.last_success:
            days_since = (datetime.now(timezone.utc) - self.last_success).days
            decay = max(0.5, 1.0 - (days_since / 30) * 0.1)
            base *= decay

        # Require minimum attempts for high trust
        if self.attempts < 5:
            base *= 0.8

        return min(0.95, base)

class PatternMemory:
    """Track and learn from pattern success/failure."""

    def __init__(self, db: Database, repo_path: str):
        self.db = db
        self.repo_path = repo_path

    def record_outcome(
        self,
        action: Action,
        success: bool,
    ) -> None:
        """Record the outcome of an action."""
        pattern_hash = self._hash_pattern(action)
        # Update or create PatternSuccess record

    def get_trust_level(self, action: Action) -> float:
        """Get trust level for an action based on history."""
        pattern_hash = self._hash_pattern(action)
        record = self._get_pattern(pattern_hash)
        if record:
            return record.trust_level
        return 0.5  # Default: moderate trust

    def should_skip_verification(self, action: Action) -> bool:
        """Should we skip verification for this action?"""
        return self.get_trust_level(action) > 0.9
```

### 4.2 Integration

```python
def execute_action(action: Action, ctx: WorkContext) -> str:
    # Check pattern memory
    if ctx.pattern_memory:
        if ctx.pattern_memory.should_skip_verification(action):
            result = ctx.sandbox.execute(action)
            # Still record outcome for learning
            ctx.pattern_memory.record_outcome(action, _check_basic_success(result))
            return result

    # Normal flow
    # ...
```

**Deliverable:** Extended `project_memory.py`, integration with execution

---

## Phase 5: Trust Budget (Week 9-10)

**Goal:** Dynamic verification cadence based on session history.

### 5.1 Create Trust Budget System

Create `src/reos/code_mode/trust.py`:

```python
@dataclass
class TrustBudget:
    """Session-level trust budget."""

    initial: int = 100
    remaining: int = 100

    # History
    verifications_skipped: int = 0
    verifications_performed: int = 0
    failures_caught: int = 0
    failures_missed: int = 0

    def should_verify(self, risk: ActionRisk) -> bool:
        """Should we verify this action?"""
        cost = self._risk_cost(risk)

        # Always verify high risk
        if risk.level == RiskLevel.HIGH:
            return True

        # Below minimum budget: must verify
        if self.remaining < 30:
            return True

        # Have budget: can skip low risk
        if risk.level == RiskLevel.LOW and self.remaining > 70:
            self.remaining -= cost // 2
            self.verifications_skipped += 1
            return False

        return True

    def replenish(self, amount: int) -> None:
        """Successful execution replenishes trust."""
        self.remaining = min(self.initial, self.remaining + amount)

    def deplete(self, amount: int) -> None:
        """Failed execution depletes trust."""
        self.remaining = max(0, self.remaining - amount)
        self.failures_missed += 1

    def _risk_cost(self, risk: ActionRisk) -> int:
        return {
            RiskLevel.LOW: 5,
            RiskLevel.MEDIUM: 15,
            RiskLevel.HIGH: 30,
        }[risk.level]
```

### 5.2 Integration with WorkContext

```python
@dataclass
class WorkContext:
    # ... existing fields ...
    trust_budget: TrustBudget = field(default_factory=TrustBudget)
```

**Deliverable:** `trust.py` module, integration with WorkContext

---

## Phase 6: Batch Verification (Week 11-12)

**Goal:** Verify plans, not individual micro-decisions.

### 6.1 Create Verification Batcher

Create `src/reos/code_mode/verification.py`:

```python
@dataclass
class DeferredVerification:
    """A verification to run later in batch."""
    action: Action
    result: str
    expected_outcome: str

class VerificationBatcher:
    """Batch multiple verifications together."""

    def __init__(self, ctx: WorkContext):
        self.ctx = ctx
        self.deferred: list[DeferredVerification] = []

    def defer(self, action: Action, result: str, expected: str) -> None:
        """Defer a verification for later batch processing."""
        self.deferred.append(DeferredVerification(action, result, expected))

    def flush(self) -> list[tuple[DeferredVerification, bool]]:
        """Run all deferred verifications in batch."""
        if not self.deferred:
            return []

        # Build single verification prompt
        prompt = self._build_batch_prompt()

        # Single LLM call for all verifications
        results = self._verify_batch(prompt)

        outcomes = list(zip(self.deferred, results))
        self.deferred = []
        return outcomes

    def _build_batch_prompt(self) -> str:
        """Build a single prompt to verify multiple actions."""
        items = []
        for i, d in enumerate(self.deferred):
            items.append(f"{i+1}. Action: {d.action.type.value}")
            items.append(f"   Expected: {d.expected_outcome}")
            items.append(f"   Result: {d.result[:200]}")

        return "\n".join(items)
```

### 6.2 Integration

Modify intention execution to use batcher for LOW risk actions.

**Deliverable:** `verification.py` module

---

## Phase 7: Fast-Path Patterns (Week 13-14)

**Goal:** Optimized handlers for common requests.

### 7.1 Create Pattern Detector

Create `src/reos/code_mode/fast_path.py`:

```python
class FastPathPattern(Enum):
    CREATE_FUNCTION = "create_function"
    CREATE_CLASS = "create_class"
    ADD_TEST = "add_test"
    FIX_IMPORT = "fix_import"
    ADD_DOCSTRING = "add_docstring"
    # ... more patterns

def detect_pattern(what: str, acceptance: str) -> FastPathPattern | None:
    """Detect if this is a well-known pattern."""
    what_lower = what.lower()

    if "create" in what_lower and "function" in what_lower:
        return FastPathPattern.CREATE_FUNCTION
    if "add" in what_lower and "test" in what_lower:
        return FastPathPattern.ADD_TEST
    # ... more detection logic

    return None

def execute_fast_path(
    pattern: FastPathPattern,
    intention: Intention,
    ctx: WorkContext,
) -> bool:
    """Execute optimized path for known pattern.

    Returns True if handled, False to fall back to full RIVA.
    """
    handler = FAST_PATH_HANDLERS.get(pattern)
    if handler:
        try:
            return handler(intention, ctx)
        except Exception as e:
            logger.warning("Fast path failed, falling back: %s", e)
            return False
    return False
```

### 7.2 Pattern Handlers

```python
def _handle_create_function(intention: Intention, ctx: WorkContext) -> bool:
    """Optimized handler for creating a single function."""
    # Extract function name, file, signature from intention
    # Generate code with minimal verification
    # Single verification at end
    pass

FAST_PATH_HANDLERS = {
    FastPathPattern.CREATE_FUNCTION: _handle_create_function,
    FastPathPattern.ADD_TEST: _handle_add_test,
    # ...
}
```

**Deliverable:** `fast_path.py` module

---

## Phase 8: Model Selection (Week 15-16)

**Goal:** Right-size model to task complexity.

### 8.1 Model Selector

Create `src/reos/code_mode/model_selector.py`:

```python
class ModelTier(Enum):
    SMALL = "small"    # Fast, cheap, good for boilerplate
    MEDIUM = "medium"  # Balanced
    LARGE = "large"    # Capable, for complex tasks

@dataclass
class ModelSelection:
    tier: ModelTier
    model_name: str
    reason: str

def select_model(
    complexity: TaskComplexity,
    available_models: list[str],
) -> ModelSelection:
    """Select appropriate model for task."""

    if complexity.score < 0.3:
        tier = ModelTier.SMALL
        reason = "Simple task, small model sufficient"
    elif complexity.score > 0.7:
        tier = ModelTier.LARGE
        reason = "Complex task, needs capable model"
    else:
        tier = ModelTier.MEDIUM
        reason = "Moderate complexity"

    model_name = _get_model_for_tier(tier, available_models)

    return ModelSelection(tier, model_name, reason)
```

**Deliverable:** `model_selector.py` module

---

## Phase 9: Progressive Enhancement (Week 17-18)

**Goal:** Ship basic code fast, enhance iteratively.

### 9.1 Two-Pass Generation

```python
async def generate_with_enhancement(
    intention: Intention,
    ctx: WorkContext,
) -> str:
    """Generate code in two passes: basic then enhanced."""

    # Pass 1: Basic implementation (fast)
    basic = await generate_basic(intention, ctx)

    # Quick verification: does it work at all?
    if not await verify_basic(basic, intention, ctx):
        return await full_riva_fallback(intention, ctx)

    # If user requested basic only, done
    if ctx.quality_level == "basic":
        return basic

    # Pass 2: Enhancement (can be async/background)
    enhanced = await enhance_code(basic, intention, ctx)

    return enhanced

async def generate_basic(intention: Intention, ctx: WorkContext) -> str:
    """Generate minimal working implementation."""
    # Use smaller model
    # Skip edge cases
    # Minimal error handling
    pass

async def enhance_code(basic: str, intention: Intention, ctx: WorkContext) -> str:
    """Enhance basic code with:
    - Error handling
    - Edge cases
    - Documentation
    - Type hints
    """
    pass
```

**Deliverable:** Modified generation flow with enhancement pass

---

## Success Metrics

### What We'll Measure

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| LLM calls per task | TBD | -30% | Metrics collection |
| Average response time | TBD | <45s | Timing hooks |
| First-try success | TBD | 85-90% | Quality tracker |
| Decomposition ratio | TBD | <20% simple | Metrics |
| Token usage | TBD | -20% | Provider tracking |

### What We Won't Promise

- "Never fails" - We optimize for correctness, not perfection
- "Always faster" - Some complex tasks need full verification
- "Works for everything" - Fast paths only cover common patterns

---

## Honest Assessment

### What's Realistic

1. **Phase 1-2 (Metrics + Smart Decomposition)**: High confidence. Adds measurement and improves existing heuristics.

2. **Phase 3-5 (Risk + Pattern + Trust)**: Medium confidence. Clear design, but tuning thresholds will take iteration.

3. **Phase 6-7 (Batch + Fast-Path)**: Medium confidence. Architecturally simple, but getting patterns right is hard.

4. **Phase 8-9 (Model Selection + Progressive)**: Lower confidence. Depends on model availability and user expectations.

### What We Don't Know Yet

- Optimal thresholds for decomposition
- How much trust budget actually helps
- Which patterns are worth fast-pathing
- User tolerance for "basic then enhanced" UX

### How We'll Learn

- Measure everything before optimizing
- A/B test new strategies against baseline
- Listen to user feedback about "felt" speed vs accuracy
- Be willing to roll back optimizations that don't help

---

## Getting Started

### Immediate Next Steps

1. Create `src/reos/code_mode/optimization/` directory
2. Scaffold module files with interfaces (not implementations)
3. Add metrics hooks to existing code
4. Run baseline measurements

### First PR Should Include

- `optimization/__init__.py` - Module exports
- `optimization/metrics.py` - Metrics collection (Phase 1)
- `optimization/complexity.py` - Task complexity analysis (Phase 2)
- Tests for new modules
- Documentation updates

This is not a sprint. It's a marathon. We'll ship incremental improvements and learn as we go.
