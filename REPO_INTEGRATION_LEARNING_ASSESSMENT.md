# Repository Integration Learning Assessment

## Executive Summary

**Current State:** 🟡 **Partial - Standalone Code Learning Only**

We're learning whether **individual code snippets are correct**, but NOT whether they **integrate well with the whole repository**. This is the difference between "compiles" and "makes the codebase better."

## What We Currently Track

### ✅ Standalone Code Correctness

**Verification Layers (per action):**
1. **Syntax Layer**: Does this code parse?
2. **Semantic Layer**: Are variables defined? Imports present?
3. **Behavioral Layer**: Does THIS file's tests pass?
4. **Intent Layer**: Does code match the request?

**Metrics Tracked:**
- Success/failure of individual actions
- Verification layer results for each code change
- LLM calls, timing, token usage
- Model used (provider + model name)

**Learning Enabled:**
- "Import statements fail 20% of the time with Claude Sonnet"
- "Syntax errors caught 5% faster with tree-sitter"
- "Intent verification has 85% confidence with GPT-4"

### ❌ Repository Integration Quality

**What's MISSING:**
1. **Repo Context**: Which repository? What's its architecture?
2. **Integration Testing**: Did this break OTHER files?
3. **Full Test Suite**: We only run tests on the changed file
4. **Regression Detection**: Did this break existing functionality?
5. **Pattern Consistency**: Does this follow THIS repo's conventions?
6. **Cross-file Coherence**: Are types, imports, styles consistent?
7. **Architecture Alignment**: Does this fit the repo's design patterns?
8. **Long-term Success**: Did this change survive or get reverted?

## Concrete Example: "Make a CRM"

### Current Learning Capability

**Session 1: Make a CRM**
```
Action: Create user.py
Verification:
  ✓ Syntax: Valid Python
  ✓ Semantic: All imports defined
  ✓ Behavioral: user_test.py passes
  ✓ Intent: Has User class as requested
Result: SUCCESS

Action: Create database.py
Verification:
  ✓ Syntax: Valid Python
  ✓ Semantic: All imports defined
  ✓ Behavioral: database_test.py passes
  ✓ Intent: Has Database class as requested
Result: SUCCESS
```

**Metrics Learned:**
- 2 actions, both succeeded
- Verification caught 0 errors
- 100% first-try success

### What We're NOT Learning

**Integration Issues Missed:**
```python
# user.py
from models import User  # ❌ But database.py expects from database import User

# database.py
class User:
    id: int  # ❌ But user.py expects id: str

# api.py (created later)
from user import User  # ❌ Conflicts with database.User
```

**Problems:**
1. **Type Inconsistency**: User.id is `int` in one file, `str` in another
2. **Import Conflicts**: Multiple `User` definitions, circular imports
3. **Architecture Misalignment**: MVC structure started in user.py, but database.py uses different pattern
4. **Test Coverage Gap**: Individual file tests pass, but integration tests would fail
5. **Style Drift**: user.py uses dataclasses, database.py uses attrs, api.py uses plain classes

**Current Verdict:** ✅ SUCCESS (both files work standalone)
**Reality:** ❌ FAILURE (codebase is inconsistent and broken)

## The Gap in Learning

### What We Think We Learned
- "CRM creation succeeded with Claude Sonnet"
- "Verification caught 0 errors"
- "100% first-try success rate"

### What Actually Happened
- Types are inconsistent across files
- Imports create circular dependencies
- Architecture patterns conflict
- Integration is broken

### What We SHOULD Learn
- "Claude Sonnet creates type inconsistencies in multi-file codebases"
- "Need cross-file type checking for CRM projects"
- "Import verification should check for circular dependencies"
- "Pattern consistency verification needed for repos with >3 files"

## Repository-Specific Learning Needed

### 1. Repo Context Tracking

**Missing Fields in ExecutionMetrics:**
```python
repo_path: str | None = None           # Which repo?
repo_name: str | None = None           # friendly name
repo_architecture: str | None = None   # MVC, Clean Architecture, etc.
repo_language_primary: str | None = None  # Python, TypeScript, etc.
```

**Why Critical:**
- Patterns that work in one repo might not work in another
- A FastAPI repo has different conventions than a Django repo
- Learning should be per-repo, not global

### 2. Integration Verification Layer (Layer 5)

**What It Should Check:**
```python
class IntegrationVerificationResult:
    # Cross-file consistency
    type_conflicts: list[str]           # User.id: int vs str
    import_cycles: list[str]            # A imports B imports A
    naming_inconsistencies: list[str]   # UserModel vs User vs user

    # Full test suite
    all_tests_passed: bool              # Run ENTIRE test suite
    new_test_failures: list[str]        # Tests that broke
    coverage_delta: float               # Did coverage go up or down?

    # Architecture alignment
    pattern_consistency_score: float    # Matches existing patterns?
    follows_conventions: bool           # Naming, structure, style
    technical_debt_added: bool          # Created inconsistencies?

    # Long-term health
    integration_confidence: float       # 0.0-1.0
```

**Current Status:** ❌ **Does Not Exist**

### 3. Full Repo Test Suite Execution

**Current Behavioral Layer:**
```python
# Only runs tests for the changed file
cmd = f"pytest {file_path} -v"
```

**Should Be:**
```python
# Run full test suite to catch regressions
cmd = "pytest . -v"  # All tests

# Track which tests broke
newly_failed = current_failures - previous_failures
```

**Why Critical:**
- Catch regressions in other parts of the codebase
- Measure true integration impact
- Learn "this pattern breaks auth tests 30% of the time"

### 4. Pattern Consistency Verification

**We Have PatternSuccessTracker (Per-Repo):**
```python
# pattern_success.py tracks:
- pattern_hash
- repo_path  ✅
- success_count / failure_count
- trust_score
```

**But It's Not Connected to Integration:**
- Patterns tracked for fast-path optimization
- NOT tracked for consistency verification
- Doesn't check "does new code match existing patterns?"

**Should Track:**
```sql
CREATE TABLE repo_patterns (
    repo_path TEXT,
    pattern_type TEXT,  -- import_style, class_naming, error_handling
    pattern_example TEXT,
    file_count INTEGER,  -- How many files use this pattern
    is_dominant BOOLEAN  -- Most common pattern in repo
);
```

**Learning:**
- "This repo uses `from typing import` not `import typing`"
- "This repo names models like `UserModel` not `User`"
- "This repo uses dataclasses, not attrs"
- **Verification:** Does new code follow dominant patterns?

### 5. Regression Detection

**Current Approach:**
```python
# Per-action verification
verify_action_multilayer(action, intention, ctx, strategy)
```

**Missing: Baseline Comparison**
```python
class RepoBaseline:
    test_results_before: TestResults
    import_graph_before: ImportGraph
    type_consistency_before: TypeMap

def verify_integration(action, baseline):
    test_results_after = run_all_tests()

    # Detect regressions
    new_failures = test_results_after.failed - baseline.test_results_before.failed

    # Detect new conflicts
    new_cycles = detect_import_cycles(import_graph_after) - baseline.cycles

    return IntegrationResult(
        regressions_introduced=len(new_failures),
        new_import_cycles=len(new_cycles),
        ...
    )
```

**Why Critical:**
- Learn "adding auth.py broke 3 existing tests"
- Track "this pattern creates circular imports 40% of the time"
- Measure "changes to models.py affect 12 other files on average"

## Proposed Implementation

### Priority 1: Repo Context Tracking (CRITICAL)

**Add to ExecutionMetrics:**
```python
@dataclass
class ExecutionMetrics:
    # ... existing fields ...

    # Repository context
    repo_path: str | None = None
    repo_name: str | None = None
    files_changed: list[str] = field(default_factory=list)
    lines_changed: int = 0
```

**Capture in intention.py:**
```python
if depth == 0 and ctx.metrics:
    ctx.metrics.repo_path = ctx.sandbox.repo_path
    ctx.metrics.repo_name = Path(ctx.sandbox.repo_path).name
```

**Database Schema:**
```sql
ALTER TABLE riva_metrics ADD COLUMN repo_path TEXT;
ALTER TABLE riva_metrics ADD COLUMN repo_name TEXT;
CREATE INDEX idx_repo ON riva_metrics(repo_path, llm_model);
```

**Enables:**
- "Show me all CRM attempts in THIS repo"
- "How does Claude Sonnet perform on talking_rock vs other repos?"
- "Which repos have highest success rates?"

**Effort:** ~2 hours
**Impact:** HIGH - Enables repo-specific learning

### Priority 2: Full Test Suite Verification (CRITICAL)

**Enhance Behavioral Layer:**
```python
async def _verify_behavioral_layer_with_integration(
    action: Action,
    intention: Intention,
    ctx: WorkContext,
    baseline: RepoBaseline | None = None
) -> LayerResult:
    """Run full test suite to catch regressions."""

    # Run ALL tests, not just the changed file
    result = subprocess.run(
        "pytest . -v --tb=short",
        capture_output=True,
        text=True,
        timeout=60
    )

    # Compare with baseline
    if baseline:
        new_failures = parse_new_failures(result.stdout, baseline.test_output)
        return LayerResult(
            layer=VerificationLayer.BEHAVIORAL,
            passed=len(new_failures) == 0,
            confidence=0.95 if len(new_failures) == 0 else 0.3,
            reason=f"Introduced {len(new_failures)} regressions" if new_failures else "All tests pass",
            details={
                "regressions": new_failures,
                "total_tests": result.stdout.count("PASSED"),
            }
        )
```

**Track in Metrics:**
```python
# New fields
regressions_introduced: int = 0
tests_broken: list[str] = field(default_factory=list)
full_suite_pass_rate: float = 0.0
```

**Enables:**
- "Adding auth.py broke test_user.py 30% of the time"
- "Changes to models/ introduce regressions 15% of the time"
- "GPT-4 introduces fewer regressions than Claude (8% vs 12%)"

**Effort:** ~1 day
**Impact:** HIGH - Catches integration failures

### Priority 3: Integration Verification Layer (Layer 5)

**New Verification Layer:**
```python
@dataclass
class IntegrationLayerResult:
    """Results from cross-file integration verification."""

    type_conflicts: list[str]
    import_cycles: list[str]
    pattern_inconsistencies: list[str]
    architecture_violations: list[str]

    integration_score: float  # 0.0-1.0

async def _verify_integration_layer(
    action: Action,
    ctx: WorkContext,
    repo_baseline: RepoBaseline
) -> LayerResult:
    """Verify integration with existing codebase.

    Checks:
    1. Type consistency across files
    2. Import cycle detection
    3. Pattern consistency
    4. Architecture alignment
    """

    # Type consistency check
    type_conflicts = check_type_consistency(action, ctx.sandbox)

    # Import cycle detection
    import_cycles = detect_import_cycles(ctx.sandbox.repo_path)

    # Pattern consistency
    pattern_score = check_pattern_consistency(action, repo_baseline.patterns)

    # Overall integration score
    integration_score = calculate_integration_score(
        type_conflicts, import_cycles, pattern_score
    )

    return LayerResult(
        layer=VerificationLayer.INTEGRATION,
        passed=integration_score > 0.7,
        confidence=integration_score,
        reason=f"Integration score: {integration_score:.1%}",
        details={
            "type_conflicts": type_conflicts,
            "import_cycles": import_cycles,
            "pattern_score": pattern_score,
        }
    )
```

**Update Verification Strategy:**
```python
# Add Layer 5 to THOROUGH and MAXIMUM strategies
THOROUGH = [
    VerificationLayer.SYNTAX,
    VerificationLayer.SEMANTIC,
    VerificationLayer.BEHAVIORAL,
    VerificationLayer.INTENT,
    VerificationLayer.INTEGRATION,  # NEW
]
```

**Effort:** ~1 week
**Impact:** VERY HIGH - True holistic verification

### Priority 4: Repo-Specific Pattern Learning

**Enhance PatternSuccessTracker:**
```python
class RepoPatternAnalyzer:
    """Analyze and enforce repo-specific patterns."""

    def analyze_repo_patterns(self, repo_path: str) -> RepoPatterns:
        """Extract dominant patterns from existing code."""
        return RepoPatterns(
            import_style=self._analyze_import_style(),
            naming_conventions=self._analyze_naming(),
            class_structure=self._analyze_classes(),
            error_handling=self._analyze_error_patterns(),
        )

    def verify_pattern_consistency(
        self,
        new_code: str,
        repo_patterns: RepoPatterns
    ) -> float:
        """Score how well new code matches repo patterns."""
        ...
```

**Track in Metrics:**
```python
pattern_consistency_score: float = 0.0
pattern_violations: list[str] = field(default_factory=list)
```

**Enables:**
- "New code uses dataclasses, but repo uses attrs (inconsistent)"
- "Import style matches repo conventions (consistent)"
- Learn "Claude Sonnet respects repo patterns 78% of the time"

**Effort:** ~1 week
**Impact:** HIGH - Maintains codebase coherence

## Learning Comparison: Before vs After

### Scenario: "Make a CRM" with 5 files created

**Current Learning (Standalone):**
```
Session: make_crm_001
Model: claude-sonnet-4
Actions: 5 (all SUCCESS)
Verification layers:
  Syntax: 5/5 passed
  Semantic: 5/5 passed
  Behavioral: 5/5 passed (only per-file tests)
  Intent: 5/5 passed
Overall: SUCCESS ✓
```

**Lesson Learned:** "Claude Sonnet is great at CRM creation (100% success)"

**Reality:**
- Types inconsistent across files
- Circular import between user.py and database.py
- 3 different patterns for error handling
- Integration tests would fail

---

**With Integration Learning (Proposed):**
```
Session: make_crm_001
Repo: ~/projects/my_crm
Model: claude-sonnet-4
Actions: 5

Verification layers:
  Syntax: 5/5 passed
  Semantic: 5/5 passed
  Behavioral: 3/5 passed ❌ (full suite: 2 regressions)
  Intent: 5/5 passed
  Integration: 2/5 passed ❌

Integration failures:
  - user.py: Type conflict (User.id: int vs str in database.py)
  - database.py: Creates circular import with user.py
  - api.py: Pattern inconsistency (uses attrs, repo uses dataclasses)

Regressions introduced:
  - test_auth.py::test_login FAILED (broken import)
  - test_database.py::test_connection FAILED (type mismatch)

Overall: PARTIAL SUCCESS (code works standalone, fails integration)
```

**Lesson Learned:**
- "Claude Sonnet creates type inconsistencies in 40% of multi-file sessions"
- "Circular imports introduced when creating >3 related classes"
- "Pattern consistency violations in 30% of CRM attempts"
- "Need to prompt for type consistency explicitly"

**Actionable:**
- Update prompts to emphasize type consistency
- Add integration layer for multi-file changes
- Increase verification strategy to THOROUGH for >3 files
- Learn repo-specific patterns first, enforce during generation

## Impact on Real-World Scenarios

### "Make a CRM for my business"

**Current:**
- Individual files work
- Integration likely broken
- Learn "100% success" (false positive)

**With Integration Learning:**
- Catch type conflicts early
- Detect circular imports
- Enforce pattern consistency
- Learn "60% success standalone, 40% success integrated"
- **Actually improve over time**

### "Make an RPG based on open source databases"

**Current:**
- Game mechanics code works
- Database integration might be broken
- Imports might conflict with existing game code
- Learn "RPG creation succeeded"

**With Integration Learning:**
- Verify database schema consistency
- Check game loop integration
- Ensure no conflicts with existing systems
- Track "RPG sessions need THOROUGH strategy"
- **Learn integration patterns specific to game repos**

### "Make a sophisticated Command & Conquer game"

**Current:**
- 100+ files created
- Each file might work standalone
- Integration chaos likely
- No learning about architectural coherence

**With Integration Learning:**
- Catch architecture violations early
- Detect when new systems break existing ones
- Track pattern drift over 100+ changes
- Learn "complex games need Layer 5 verification"
- **Accumulate knowledge about THIS specific game's architecture**

## Recommendations

### Immediate (This Week)

1. **Add repo_path to ExecutionMetrics** ✅ Easy win
2. **Capture repo context at session start** ✅ 2-hour task
3. **Update database schema with repo fields** ✅ Enable repo-specific queries

### Short-term (Next 2 Weeks)

4. **Implement full test suite in Behavioral Layer** 🔥 Critical for regression detection
5. **Track regressions introduced per session** 🔥 Learn integration impact

### Medium-term (Next Month)

6. **Design Integration Verification Layer (Layer 5)** 🚀 Game changer
7. **Implement basic integration checks** (types, imports, patterns)
8. **Connect PatternSuccessTracker to integration verification**

### Long-term (Next Quarter)

9. **Full repo pattern analysis and enforcement**
10. **Architecture-aware verification**
11. **Long-term success tracking** (did changes survive?)

## Conclusion

**Current State:** We're learning if **code compiles**, not if it **integrates well**.

**With Integration Learning:** We'll learn:
- Which models respect repo architecture
- What patterns cause integration failures
- How to improve over time in THIS specific codebase
- True success rates, not false positives

**Bottom Line:** Right now we're learning to write good **sentences**, but we need to learn to write good **stories** (coherent, integrated codebases).

The difference is critical for real-world usage where code doesn't exist in isolation - it's part of a living, evolving repository.
