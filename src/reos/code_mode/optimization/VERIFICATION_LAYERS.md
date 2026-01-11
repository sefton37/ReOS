# Multi-Layer Verification System

**Philosophy**: *"Spend tokens freely to be certain"*

RIVA's multi-layer verification system provides thorough code validation through progressive verification stages. Since we use local inference (free tokens), we can afford multiple verification passes to achieve high confidence.

## Overview

The verification system implements four progressive layers:

1. **SYNTAX** (Fast: ~1ms) - Is the code syntactically valid?
2. **SEMANTIC** (Medium: ~10ms) - Does the code make semantic sense?
3. **BEHAVIORAL** (Slow: ~100ms-1s) - Does the code execute correctly?
4. **INTENT** (Slowest: ~500ms-2s) - Does it match what was requested?

Each layer builds on the previous one, failing fast to save tokens on obvious errors while spending tokens on deeper verification when needed.

## Core Principle

> **"If you can't verify it cheaply, verify it thoroughly."**

Unlike commercial LLMs that optimize for speed, RIVA optimizes for correctness. With free local inference, we can afford to:

- Run multiple verification passes
- Execute tests on every change
- Perform semantic analysis with AST inspection
- Use LLM judges for intent alignment

The cost is time (~1-3 seconds extra), not money. The benefit is confidence.

## Verification Layers

### Layer 1: Syntax Verification

**Purpose**: Catch syntax errors before any deeper analysis

**Methods**:
- Tree-sitter AST parsing (if available)
- Python's `ast.parse()` (fallback)
- Language-specific syntax validators

**Example failures**:
```python
def foo(x  # Missing closing paren
    return x + 1

# SYNTAX LAYER FAILS: "SyntaxError: invalid syntax"
```

**Performance**: ~1ms (tree-sitter), ~5ms (ast.parse)

**Confidence**: 95% (syntax errors are unambiguous)

### Layer 2: Semantic Verification

**Purpose**: Catch logical errors that are syntactically valid

**Methods**:
- Undefined name detection (AST analysis)
- Unresolved import checking
- Function arity validation
- Type inconsistency detection (with Jedi if available)

**Example failures**:
```python
def calculate_total(items):
    return sum(item.price for item in itms)  # Typo: itms vs items

# SEMANTIC LAYER FAILS: "Name 'itms' is not defined"
```

```python
import nonexistent_module  # Module doesn't exist

# SEMANTIC LAYER FAILS: "Unresolved import: nonexistent_module"
```

**Performance**: ~10-50ms depending on code size

**Confidence**: 80-90% (some issues need runtime context)

### Layer 3: Behavioral Verification

**Purpose**: Catch runtime errors through actual execution

**Methods**:
- **For test files**: Run pytest with timeout
- **For regular files**: Compile check + selective execution
- **For scripts**: Safe sandbox execution with resource limits

**Example failures**:
```python
def divide(a, b):
    return a / b

# Test file
def test_divide():
    assert divide(10, 2) == 5
    assert divide(10, 0) == None  # Will fail at runtime

# BEHAVIORAL LAYER FAILS: "1 test failed: ZeroDivisionError"
```

**Performance**:
- Compilation: ~50-100ms
- Test execution: 100ms-5s (with 5s timeout)

**Confidence**: 85-95% (depends on test coverage)

**Safety**:
- 5-second timeout per test file
- 10-second total timeout for subprocess
- No network access in sandbox

### Layer 4: Intent Verification

**Purpose**: Verify the code matches what was actually requested

**Methods**:
- LLM judge comparing code to original intention
- Natural language alignment check
- Requirement checklist validation

**Example failures**:
```python
# User requested: "Add a function to calculate factorial"
# Code generated:
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

# INTENT LAYER FAILS: "Code implements fibonacci, not factorial"
```

**Performance**: ~500ms-2s (LLM inference)

**Confidence**: 70-85% (LLM-dependent, subjective)

**Status**: ⚠️ Currently placeholder - needs LLM integration

## Verification Strategies

Choose verification depth based on risk level:

```python
from reos.code_mode.optimization import (
    VerificationStrategy,
    verify_action_multilayer,
)

# MINIMAL: Syntax only (low-risk changes like imports)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.MINIMAL
)

# STANDARD: Syntax + Semantic (most changes)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.STANDARD
)

# THOROUGH: Syntax + Semantic + Behavioral (test files, critical code)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.THOROUGH
)

# MAXIMUM: All 4 layers (production deployments, security-critical)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.MAXIMUM
)
```

### Strategy Selection

The system can automatically select strategy based on risk:

```python
from reos.code_mode.optimization import get_strategy_for_risk, RiskLevel

# Automatically choose strategy
risk = assess_risk(action)
strategy = get_strategy_for_risk(risk.level)

result = await verify_action_multilayer(action, intention, ctx, strategy=strategy)
```

**Mapping**:
- `RiskLevel.LOW` → `VerificationStrategy.MINIMAL` (syntax only)
- `RiskLevel.MEDIUM` → `VerificationStrategy.STANDARD` (syntax + semantic)
- `RiskLevel.HIGH` → `VerificationStrategy.THOROUGH` (syntax + semantic + behavioral)
- Critical/Security → `VerificationStrategy.MAXIMUM` (all 4 layers)

## Usage Examples

### Basic Usage

```python
from reos.code_mode.optimization import (
    verify_action_multilayer,
    VerificationStrategy,
)

# Verify a code change
action = Action(
    type=ActionType.WRITE_FILE,
    target="src/calculator.py",
    content="def add(a, b):\n    return a + b",
)

result = await verify_action_multilayer(
    action=action,
    intention=intention,
    ctx=work_context,
    strategy=VerificationStrategy.STANDARD,
)

if result.passed:
    print(f"✓ Verification passed with {result.confidence:.0%} confidence")
    print(f"  Layers: {[r.layer.value for r in result.layer_results]}")
else:
    print(f"✗ Verification failed at layer: {result.failed_layer.value}")
    print(f"  Reason: {result.reason}")
```

### With Early Exit

```python
# Stop at first failure (saves tokens)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.THOROUGH,
    stop_on_failure=True,  # Default: True
)
```

### Running All Layers

```python
# Run all layers even if one fails (for diagnostics)
result = await verify_action_multilayer(
    action, intention, ctx,
    strategy=VerificationStrategy.MAXIMUM,
    stop_on_failure=False,  # Run all layers
)

# Check individual layer results
for layer_result in result.layer_results:
    status = "✓" if layer_result.passed else "✗"
    print(f"{status} {layer_result.layer.value}: {layer_result.reason}")
```

### Integration with Risk Assessment

```python
from reos.code_mode.optimization import assess_risk, get_strategy_for_risk

# Assess risk automatically
action_risk = assess_risk(action)
strategy = get_strategy_for_risk(action_risk.level)

# Verify with appropriate depth
result = await verify_action_multilayer(action, intention, ctx, strategy=strategy)

if not result.passed:
    # High-risk action failed verification - decompose
    if action_risk.level == RiskLevel.HIGH:
        print("High-risk action failed verification - recommending decomposition")
        # Trigger RIVA decomposition...
```

### Custom Layer Selection

```python
# Verify only specific layers
from reos.code_mode.optimization.verification_layers import (
    _verify_syntax_layer,
    _verify_behavioral_layer,
)

# Just syntax
syntax_result = await _verify_syntax_layer(action, ctx)

# Just behavioral (requires syntax to pass first)
behavioral_result = await _verify_behavioral_layer(action, intention, ctx)
```

## Performance Characteristics

**Time Cost by Strategy**:

| Strategy | Layers | Typical Time | Use Case |
|----------|--------|--------------|----------|
| MINIMAL | Syntax | ~1-5ms | Imports, config changes |
| STANDARD | Syntax + Semantic | ~10-50ms | Most code changes |
| THOROUGH | Syntax + Semantic + Behavioral | ~100ms-5s | Tests, critical functions |
| MAXIMUM | All 4 layers | ~500ms-7s | Production deploys |

**Confidence by Strategy**:

| Strategy | Confidence | False Negatives |
|----------|------------|-----------------|
| MINIMAL | ~80% | 20% (semantic/runtime bugs) |
| STANDARD | ~90% | 10% (runtime bugs) |
| THOROUGH | ~95% | 5% (intent misalignment) |
| MAXIMUM | ~98% | 2% (edge cases) |

## Architecture

### Verification Result

```python
@dataclass
class VerificationResult:
    passed: bool
    confidence: float  # 0.0 to 1.0
    reason: str
    layer_results: list[LayerResult]
    failed_layer: VerificationLayer | None
    total_time_ms: float

    def summary(self) -> str:
        """Human-readable summary."""
```

### Layer Result

```python
@dataclass
class LayerResult:
    layer: VerificationLayer
    passed: bool
    confidence: float
    reason: str
    time_ms: float
    details: dict | None = None
```

### Confidence Scoring

Confidence is computed as weighted average of layer confidences:

```python
weights = {
    VerificationLayer.SYNTAX: 0.20,      # 20% weight
    VerificationLayer.SEMANTIC: 0.30,    # 30% weight
    VerificationLayer.BEHAVIORAL: 0.35,  # 35% weight
    VerificationLayer.INTENT: 0.15,      # 15% weight
}

# Only layers that passed contribute to confidence
total_confidence = sum(
    layer.confidence * weights[layer.layer]
    for layer in passed_layers
) / sum(weights[layer.layer] for layer in passed_layers)
```

## Integration Points

### With RIVA work() Loop

```python
# In intention.py work() loop
from reos.code_mode.optimization import (
    verify_action_multilayer,
    get_strategy_for_risk,
)

# After generating action
action_risk = assess_risk(action)
strategy = get_strategy_for_risk(action_risk.level)

# Verify before executing
result = await verify_action_multilayer(action, intention, ctx, strategy=strategy)

if not result.passed:
    # Failed verification - decompose or retry
    if action_risk.level == RiskLevel.HIGH:
        return work(decompose(intention), ctx)
    else:
        # Log and continue with standard verification
        logger.warning(f"Action failed {result.failed_layer.value} verification: {result.reason}")
```

### With Fast Paths

```python
# In fast_path.py
from reos.code_mode.optimization import verify_action_multilayer, VerificationStrategy

async def execute_fast_path(pattern, intention, ctx):
    # Generate code via fast path
    action = _generate_fast_path_action(pattern, intention, ctx)

    # Fast paths use MINIMAL verification (syntax only)
    result = await verify_action_multilayer(
        action, intention, ctx,
        strategy=VerificationStrategy.MINIMAL,
    )

    if result.passed:
        return action  # Execute immediately
    else:
        # Fall back to standard RIVA flow
        return None
```

### With Trust Budget

```python
# Trust budget can skip lighter verification layers
if trust_budget.should_skip_verification(action):
    # Skip MINIMAL/STANDARD verification
    # Still run THOROUGH/MAXIMUM for high-risk actions
    if action_risk.level >= RiskLevel.HIGH:
        result = await verify_action_multilayer(action, intention, ctx,
                                                strategy=VerificationStrategy.THOROUGH)
    else:
        # Trust the action
        result = VerificationResult(passed=True, confidence=0.85, reason="Trusted by budget")
```

## Dependencies

**Required**:
- `ast` (Python stdlib) - Syntax and semantic analysis

**Optional** (graceful degradation):
- `tree-sitter` + `tree-sitter-python` - Better syntax parsing
- `tree-sitter-javascript` - JavaScript/TypeScript support
- `pytest` - Test execution (behavioral layer)
- `jedi` - Advanced Python semantic analysis

Install optional dependencies:
```bash
pip install -e ".[parsing]"  # tree-sitter support
pip install jedi              # semantic analysis
```

## Limitations

### Current Limitations

1. **Intent Layer**: Currently placeholder, needs LLM integration
2. **Test Coverage**: Behavioral layer confidence depends on test quality
3. **Language Support**: Semantic analysis only for Python currently
4. **Sandbox Safety**: Behavioral tests run in subprocess with timeouts, not full sandbox

### Future Enhancements

- [ ] Integrate LLM judge for intent verification
- [ ] Add semantic validators for JavaScript/TypeScript
- [ ] Property-based testing integration (Hypothesis)
- [ ] Mutation testing for test quality assessment
- [ ] Full sandbox integration for behavioral layer
- [ ] Caching of verification results by content hash
- [ ] Parallel layer execution (when independent)

## Best Practices

### When to Use Each Strategy

**Use MINIMAL when**:
- Adding imports
- Modifying config files
- Changing docstrings/comments
- Trust budget is high

**Use STANDARD when**:
- Writing new functions
- Modifying existing logic
- Refactoring code
- Default for most changes

**Use THOROUGH when**:
- Writing tests
- Modifying core algorithms
- Security-sensitive code
- Integration with external systems

**Use MAXIMUM when**:
- Production deployments
- Public API changes
- Security/compliance requirements
- Final validation before merge

### Optimization Tips

1. **Fail Fast**: Use `stop_on_failure=True` (default) to save tokens
2. **Cache Results**: Verification results can be cached by content hash
3. **Parallel Execution**: Independent layers can run concurrently (future)
4. **Skip Intent**: Intent layer is expensive and subjective - only use for critical changes

### Debugging Failures

```python
result = await verify_action_multilayer(action, intention, ctx,
                                        strategy=VerificationStrategy.MAXIMUM,
                                        stop_on_failure=False)

# Print detailed breakdown
print(result.summary())

# Check each layer
for layer_result in result.layer_results:
    print(f"\n{layer_result.layer.value.upper()}:")
    print(f"  Passed: {layer_result.passed}")
    print(f"  Confidence: {layer_result.confidence:.0%}")
    print(f"  Time: {layer_result.time_ms:.1f}ms")
    print(f"  Reason: {layer_result.reason}")
    if layer_result.details:
        print(f"  Details: {layer_result.details}")
```

## References

- [RIVA Architecture](../../../README.md)
- [Fast Path Patterns](./fast_path.py)
- [Risk Assessment](./risk.py)
- [Tree-sitter Parsers](./parsers/README.md)
- [Trust Budget](./trust.py)

## Philosophy

> "Big tech optimizes for speed because tokens cost money. RIVA optimizes for correctness because tokens are free. We'll happily spend 3 seconds verifying a change that takes 1 second to generate. The alternative is spending 3 hours debugging a bug that slipped through."

The multi-layer verification system embodies this philosophy:
- Each layer adds time but increases confidence
- Failures save tokens by stopping early
- Successes spend tokens to verify thoroughly
- The result is code you can trust

**Token cost**: ~0 (local inference)
**Time cost**: ~1-7 seconds
**Confidence gain**: 80% → 98%

*Worth it.*
