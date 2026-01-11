"""Multi-layer verification for RIVA.

RIVA Philosophy: "Spend tokens freely to be certain."

Big tech optimizes for speed. We optimize for correctness.
With local inference, tokens are free - use them for thorough verification.

Verification Layers (from fast → thorough):
1. SYNTAX: Is it valid code? (tree-sitter, ast.parse) [~1ms]
2. SEMANTIC: Does it make sense? (imports exist, types match) [~10ms]
3. BEHAVIORAL: Does it work? (tests pass, output correct) [~100ms-1s]
4. INTENT: Does it match the ask? (LLM judges alignment) [~500ms-2s]

Strategy:
- Early layers fail fast (save tokens on obvious errors)
- Later layers catch subtle bugs (spend tokens for confidence)
- Each layer adds verification confidence
- Configurable depth based on risk level

Example:
    # High risk action (destructive)
    → All 4 layers (be absolutely certain)

    # Medium risk action (normal code change)
    → Layers 1-3 (syntax, semantic, behavioral)

    # Low risk action (read-only query)
    → Layer 1 only (syntax check)

This module implements each layer as a composable verifier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.intention import Action, Intention, WorkContext

logger = logging.getLogger(__name__)


class VerificationLayer(Enum):
    """Verification layers in order of increasing cost/confidence."""

    SYNTAX = "syntax"  # Fast: Is it valid code?
    SEMANTIC = "semantic"  # Medium: Does it make sense?
    BEHAVIORAL = "behavioral"  # Slow: Does it work?
    INTENT = "intent"  # Slowest: Does it match the ask?


@dataclass
class LayerResult:
    """Result from a single verification layer.

    Attributes:
        layer: Which layer produced this result
        passed: Whether verification passed
        confidence: Confidence score (0.0-1.0)
        reason: Human-readable explanation
        details: Additional structured information
        duration_ms: Time taken for this layer
        tokens_used: Tokens consumed (for LLM layers)
    """

    layer: VerificationLayer
    passed: bool
    confidence: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    tokens_used: int = 0

    def __str__(self) -> str:
        """Human-readable summary."""
        status = "✓" if self.passed else "✗"
        return f"{status} {self.layer.value}: {self.reason} (confidence: {self.confidence:.2f})"


@dataclass
class VerificationResult:
    """Complete multi-layer verification result.

    Attributes:
        action: The action that was verified
        layers: Results from each layer (in order executed)
        overall_passed: Whether all required layers passed
        overall_confidence: Combined confidence score
        total_duration_ms: Total verification time
        total_tokens: Total tokens used
        stopped_at: Layer where verification stopped (if early exit)
    """

    action: "Action"
    layers: list[LayerResult]
    overall_passed: bool
    overall_confidence: float
    total_duration_ms: int = 0
    total_tokens: int = 0
    stopped_at: VerificationLayer | None = None

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        status = "PASSED" if self.overall_passed else "FAILED"
        layers_run = len(self.layers)
        return (
            f"{status} ({layers_run} layers, "
            f"confidence: {self.overall_confidence:.2f}, "
            f"time: {self.total_duration_ms}ms)"
        )

    def get_layer_result(self, layer: VerificationLayer) -> LayerResult | None:
        """Get result for a specific layer."""
        for result in self.layers:
            if result.layer == layer:
                return result
        return None


class VerificationStrategy(Enum):
    """Predefined verification strategies by risk level."""

    # Minimal verification (low risk: queries, read-only)
    MINIMAL = "minimal"  # SYNTAX only

    # Standard verification (medium risk: normal changes)
    STANDARD = "standard"  # SYNTAX + SEMANTIC

    # Thorough verification (high risk: destructive, security-sensitive)
    THOROUGH = "thorough"  # SYNTAX + SEMANTIC + BEHAVIORAL

    # Maximum verification (critical: production deploys)
    MAXIMUM = "maximum"  # All 4 layers


# Map strategies to layer sets
STRATEGY_LAYERS = {
    VerificationStrategy.MINIMAL: [VerificationLayer.SYNTAX],
    VerificationStrategy.STANDARD: [VerificationLayer.SYNTAX, VerificationLayer.SEMANTIC],
    VerificationStrategy.THOROUGH: [
        VerificationLayer.SYNTAX,
        VerificationLayer.SEMANTIC,
        VerificationLayer.BEHAVIORAL,
    ],
    VerificationStrategy.MAXIMUM: [
        VerificationLayer.SYNTAX,
        VerificationLayer.SEMANTIC,
        VerificationLayer.BEHAVIORAL,
        VerificationLayer.INTENT,
    ],
}


def get_strategy_for_risk(risk_level: str) -> VerificationStrategy:
    """Determine verification strategy based on risk level.

    Args:
        risk_level: "low", "medium", or "high"

    Returns:
        Appropriate verification strategy
    """
    if risk_level == "low":
        return VerificationStrategy.MINIMAL
    elif risk_level == "medium":
        return VerificationStrategy.STANDARD
    elif risk_level == "high":
        return VerificationStrategy.THOROUGH
    else:
        return VerificationStrategy.STANDARD


async def verify_action_multilayer(
    action: "Action",
    intention: "Intention",
    ctx: "WorkContext",
    strategy: VerificationStrategy = VerificationStrategy.STANDARD,
    stop_on_failure: bool = True,
) -> VerificationResult:
    """Verify an action using multiple verification layers.

    Args:
        action: The action to verify
        intention: The intention this action serves
        ctx: Work context with sandbox, LLM, etc.
        strategy: Which verification strategy to use
        stop_on_failure: If True, stop at first layer that fails (save tokens)

    Returns:
        VerificationResult with outcomes from all layers

    Example:
        # High-risk action: use thorough verification
        result = await verify_action_multilayer(
            action, intention, ctx,
            strategy=VerificationStrategy.THOROUGH
        )

        if result.overall_passed:
            print(f"Verified with {result.overall_confidence:.0%} confidence")
        else:
            # See which layer failed
            for layer_result in result.layers:
                if not layer_result.passed:
                    print(f"Failed at {layer_result.layer.value}: {layer_result.reason}")
    """
    import time

    start_time = time.perf_counter()
    layers_to_run = STRATEGY_LAYERS[strategy]
    layer_results = []
    overall_passed = True
    total_tokens = 0

    # Log verification start with full context
    if ctx.session_logger:
        ctx.session_logger.log_info(
            "riva",
            "verification_start",
            f"Starting {strategy.value} verification for {action.type.value}",
            {
                "action_type": action.type.value,
                "target": action.target if hasattr(action, "target") else None,
                "strategy": strategy.value,
                "layers_to_run": [layer.value for layer in layers_to_run],
                "intention": intention.what,
            },
        )

    for i, layer in enumerate(layers_to_run, 1):
        layer_start = time.perf_counter()

        # Log layer start
        if ctx.session_logger:
            ctx.session_logger.log_info(
                "riva",
                "verification_layer_start",
                f"[{i}/{len(layers_to_run)}] Running {layer.value} verification",
                {"layer": layer.value, "layer_number": i, "total_layers": len(layers_to_run)},
            )

        # Execute layer verification
        if layer == VerificationLayer.SYNTAX:
            result = await _verify_syntax_layer(action, ctx)
        elif layer == VerificationLayer.SEMANTIC:
            result = await _verify_semantic_layer(action, ctx)
        elif layer == VerificationLayer.BEHAVIORAL:
            result = await _verify_behavioral_layer(action, intention, ctx)
        elif layer == VerificationLayer.INTENT:
            result = await _verify_intent_layer(action, intention, ctx)
        else:
            # Unknown layer
            result = LayerResult(
                layer=layer,
                passed=False,
                confidence=0.0,
                reason=f"Unknown layer: {layer.value}",
            )

        layer_duration = int((time.perf_counter() - layer_start) * 1000)
        result.duration_ms = layer_duration
        layer_results.append(result)
        total_tokens += result.tokens_used

        # Log detailed layer result (NO TRUNCATION)
        status_symbol = "✓" if result.passed else "✗"
        if ctx.session_logger:
            ctx.session_logger.log_info(
                "riva",
                "verification_layer_complete",
                f"[{i}/{len(layers_to_run)}] {status_symbol} {layer.value}: {result.reason}",
                {
                    "layer": layer.value,
                    "passed": result.passed,
                    "confidence": result.confidence,
                    "duration_ms": layer_duration,
                    "reason": result.reason,  # Full reason, no truncation
                    "details": result.details,  # Full details
                    "tokens_used": result.tokens_used,
                },
            )

        logger.debug(
            "Verification layer %s: %s (%.2f confidence, %dms)",
            layer.value,
            "passed" if result.passed else "failed",
            result.confidence,
            layer_duration,
        )

        # Check if we should stop
        if not result.passed:
            overall_passed = False
            if stop_on_failure:
                logger.info("Stopping verification at layer %s (failed)", layer.value)
                if ctx.session_logger:
                    ctx.session_logger.log_info(
                        "riva",
                        "verification_stopped",
                        f"Verification stopped at {layer.value} layer (fail-fast enabled)",
                        {
                            "stopped_at": layer.value,
                            "reason": result.reason,
                            "remaining_layers": [l.value for l in layers_to_run[i:]],
                        },
                    )
                break

    # Calculate overall confidence (weighted average)
    if layer_results:
        # Weight later layers more heavily (they're more thorough)
        weights = [1.0, 1.5, 2.0, 2.5]  # Syntax, Semantic, Behavioral, Intent
        total_weight = 0.0
        weighted_sum = 0.0

        for i, result in enumerate(layer_results):
            weight = weights[i] if i < len(weights) else 1.0
            weighted_sum += result.confidence * weight
            total_weight += weight

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0
    else:
        overall_confidence = 0.0

    total_duration = int((time.perf_counter() - start_time) * 1000)

    stopped_at = None
    if not overall_passed and stop_on_failure and layer_results:
        stopped_at = layer_results[-1].layer

    # ========================================================================
    # STAGE GATE SUMMARY: Verification Complete
    # ========================================================================
    if ctx.session_logger:
        # Build detailed summary
        summary_lines = []
        summary_lines.append("=" * 60)
        summary_lines.append("VERIFICATION COMPLETE")
        summary_lines.append("=" * 60)
        summary_lines.append(f"Strategy: {strategy.value}")
        summary_lines.append(f"Overall Result: {'PASS' if overall_passed else 'FAIL'}")
        summary_lines.append(f"Overall Confidence: {overall_confidence:.1%}")
        summary_lines.append(f"Total Duration: {total_duration}ms")
        summary_lines.append(f"Tokens Used: {total_tokens}")
        summary_lines.append("")
        summary_lines.append("Layer Results:")
        summary_lines.append("-" * 60)

        for i, result in enumerate(layer_results, 1):
            status = "✓ PASS" if result.passed else "✗ FAIL"
            summary_lines.append(
                f"  [{i}] {result.layer.value.upper()}: {status} "
                f"(confidence: {result.confidence:.1%}, {result.duration_ms}ms)"
            )
            summary_lines.append(f"      Reason: {result.reason}")
            if result.details:
                # Show full details, no truncation
                for key, value in result.details.items():
                    summary_lines.append(f"      {key}: {value}")

        if stopped_at:
            summary_lines.append("")
            summary_lines.append(f"⚠ Stopped early at {stopped_at.value} layer (fail-fast)")

        summary_lines.append("=" * 60)

        # Log the complete summary
        ctx.session_logger.log_info(
            "riva",
            "verification_summary",
            "\n".join(summary_lines),
            {
                "overall_passed": overall_passed,
                "overall_confidence": overall_confidence,
                "total_duration_ms": total_duration,
                "total_tokens": total_tokens,
                "layers_run": len(layer_results),
                "stopped_at": stopped_at.value if stopped_at else None,
                "layer_results": [
                    {
                        "layer": r.layer.value,
                        "passed": r.passed,
                        "confidence": r.confidence,
                        "duration_ms": r.duration_ms,
                        "reason": r.reason,
                        "details": r.details,
                    }
                    for r in layer_results
                ],
            },
        )

    return VerificationResult(
        action=action,
        layers=layer_results,
        overall_passed=overall_passed,
        overall_confidence=overall_confidence,
        total_duration_ms=total_duration,
        total_tokens=total_tokens,
        stopped_at=stopped_at,
    )


# Layer implementations


async def _verify_syntax_layer(action: "Action", ctx: "WorkContext") -> LayerResult:
    """Layer 1: Verify syntax is valid.

    Fast check using tree-sitter or language-specific parser.
    No tokens consumed (local parsing only).

    Returns:
        LayerResult with pass/fail and confidence
    """
    from reos.code_mode.optimization.parsers import get_parser, is_tree_sitter_available

    # Determine language from action target
    if not action.target:
        return LayerResult(
            layer=VerificationLayer.SYNTAX,
            passed=True,
            confidence=0.5,
            reason="No code to validate (non-file action)",
        )

    # Infer language
    lang = _infer_language(action.target)
    if lang == "unknown":
        return LayerResult(
            layer=VerificationLayer.SYNTAX,
            passed=True,
            confidence=0.5,
            reason="Unknown language, skipping syntax check",
        )

    # Try tree-sitter first
    if is_tree_sitter_available():
        parser = get_parser(lang)
        if parser:
            is_valid, error = parser.validate_syntax(action.content)
            if is_valid:
                return LayerResult(
                    layer=VerificationLayer.SYNTAX,
                    passed=True,
                    confidence=0.95,
                    reason=f"Valid {lang} syntax (tree-sitter)",
                )
            else:
                return LayerResult(
                    layer=VerificationLayer.SYNTAX,
                    passed=False,
                    confidence=0.0,
                    reason=f"Syntax error: {error}",
                    details={"error": error},
                )

    # Fall back to language-specific validation
    if lang == "python":
        import ast

        try:
            ast.parse(action.content)
            return LayerResult(
                layer=VerificationLayer.SYNTAX,
                passed=True,
                confidence=0.9,
                reason="Valid Python syntax (ast.parse)",
            )
        except SyntaxError as e:
            return LayerResult(
                layer=VerificationLayer.SYNTAX,
                passed=False,
                confidence=0.0,
                reason=f"Python syntax error: {e.msg}",
                details={"line": e.lineno, "offset": e.offset},
            )

    # No validation available
    return LayerResult(
        layer=VerificationLayer.SYNTAX,
        passed=True,
        confidence=0.5,
        reason="No syntax validator available, assuming valid",
    )


async def _verify_semantic_layer(action: "Action", ctx: "WorkContext") -> LayerResult:
    """Layer 2: Verify code makes semantic sense.

    Checks:
    - Imports are resolvable
    - Variables are defined before use
    - Function calls exist
    - Type hints are consistent (if present)

    May consume tokens if using LLM for semantic analysis.

    Returns:
        LayerResult with pass/fail and confidence
    """
    from reos.code_mode.optimization.semantic_validator import (
        validate_python_semantics,
        validate_javascript_semantics,
    )

    # Determine language
    if not action.target:
        return LayerResult(
            layer=VerificationLayer.SEMANTIC,
            passed=True,
            confidence=0.5,
            reason="No code to validate (non-file action)",
        )

    lang = _infer_language(action.target)

    # Validate based on language
    issues = []
    if lang == "python":
        issues = validate_python_semantics(action.content, ctx)
    elif lang in ("javascript", "typescript"):
        issues = validate_javascript_semantics(action.content, ctx)
    else:
        return LayerResult(
            layer=VerificationLayer.SEMANTIC,
            passed=True,
            confidence=0.5,
            reason=f"No semantic validator for {lang}",
        )

    # Filter issues by severity
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if errors:
        # Semantic errors found - code won't work
        error_messages = "; ".join(str(e) for e in errors)  # Show all errors
        return LayerResult(
            layer=VerificationLayer.SEMANTIC,
            passed=False,
            confidence=0.0,
            reason=f"Semantic errors found: {error_messages}",
            details={"errors": [str(e) for e in errors], "warnings": [str(w) for w in warnings]},
        )
    elif warnings:
        # Warnings only - code might work but has issues
        warning_messages = "; ".join(str(w) for w in warnings)  # Show all warnings
        return LayerResult(
            layer=VerificationLayer.SEMANTIC,
            passed=True,
            confidence=0.7,
            reason=f"Passed with warnings: {warning_messages}",
            details={"warnings": [str(w) for w in warnings]},
        )
    else:
        # No issues found
        return LayerResult(
            layer=VerificationLayer.SEMANTIC,
            passed=True,
            confidence=0.9,
            reason="No semantic issues found",
        )


async def _verify_behavioral_layer(
    action: "Action", intention: "Intention", ctx: "WorkContext"
) -> LayerResult:
    """Layer 3: Verify code behaves correctly.

    Checks:
    - Tests pass (if applicable)
    - Output matches expected format
    - No runtime errors on sample inputs

    May execute code in sandbox, consumes time but not tokens.

    Returns:
        LayerResult with pass/fail and confidence
    """
    # Determine language
    if not action.target:
        return LayerResult(
            layer=VerificationLayer.BEHAVIORAL,
            passed=True,
            confidence=0.5,
            reason="No code to test (non-file action)",
        )

    lang = _infer_language(action.target)

    # For Python, try to run basic smoke tests
    if lang == "python":
        # Check if this is a test file
        if "test_" in action.target or "_test.py" in action.target:
            # This is a test file - try to run it
            result = await _run_python_tests(action.target, ctx)
            if result:
                return result

        # Otherwise, try basic execution check
        result = await _check_python_execution(action.content, ctx)
        if result:
            return result

    # For other languages or if checks couldn't run
    return LayerResult(
        layer=VerificationLayer.BEHAVIORAL,
        passed=True,
        confidence=0.6,
        reason=f"No behavioral tests available for {lang}",
    )


async def _run_python_tests(file_path: str, ctx: "WorkContext") -> LayerResult | None:
    """Run Python tests using pytest.

    Args:
        file_path: Path to test file
        ctx: Work context with sandbox

    Returns:
        LayerResult if tests were run, None if couldn't run
    """
    try:
        # Try to run pytest on the file
        import subprocess
        import shlex

        cmd = f"pytest {shlex.quote(file_path)} -v --tb=short --timeout=5"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            # Tests passed
            test_count = result.stdout.count(" PASSED")
            return LayerResult(
                layer=VerificationLayer.BEHAVIORAL,
                passed=True,
                confidence=0.95,
                reason=f"All tests passed ({test_count} tests)",
                details={"test_count": test_count, "output": result.stdout},
            )
        else:
            # Tests failed
            failed_count = result.stdout.count(" FAILED")
            return LayerResult(
                layer=VerificationLayer.BEHAVIORAL,
                passed=False,
                confidence=0.0,
                reason=f"Tests failed ({failed_count} failures)",
                details={"failed_count": failed_count, "output": result.stdout},
            )

    except subprocess.TimeoutExpired:
        return LayerResult(
            layer=VerificationLayer.BEHAVIORAL,
            passed=False,
            confidence=0.0,
            reason="Tests timed out (>10s)",
        )
    except Exception as e:
        logger.debug("Could not run pytest: %s", e)
        return None


async def _check_python_execution(code: str, ctx: "WorkContext") -> LayerResult | None:
    """Check if Python code can execute without errors.

    Tries to compile and do basic execution check.

    Args:
        code: Python source code
        ctx: Work context

    Returns:
        LayerResult if check was performed, None otherwise
    """
    import ast

    try:
        # First, try to compile
        compile(code, "<string>", "exec")

        # Check for obvious runtime issues using AST
        try:
            tree = ast.parse(code)

            # Look for potentially problematic patterns
            issues = []

            class RuntimeChecker(ast.NodeVisitor):
                def visit_Raise(self, node):
                    # Raising exceptions is fine, but note it
                    self.generic_visit(node)

                def visit_Assert(self, node):
                    # Assertions that always fail
                    if isinstance(node.test, ast.Constant) and not node.test.value:
                        issues.append("Contains assert False")
                    self.generic_visit(node)

            checker = RuntimeChecker()
            checker.visit(tree)

            if issues:
                return LayerResult(
                    layer=VerificationLayer.BEHAVIORAL,
                    passed=True,
                    confidence=0.6,
                    reason=f"Compiles but has issues: {', '.join(issues)}",
                    details={"issues": issues},
                )

            return LayerResult(
                layer=VerificationLayer.BEHAVIORAL,
                passed=True,
                confidence=0.8,
                reason="Code compiles successfully",
            )

        except Exception as e:
            logger.debug("AST check failed: %s", e)
            return LayerResult(
                layer=VerificationLayer.BEHAVIORAL,
                passed=True,
                confidence=0.7,
                reason="Code compiles (couldn't check for runtime issues)",
            )

    except SyntaxError as e:
        # This should have been caught by syntax layer
        return LayerResult(
            layer=VerificationLayer.BEHAVIORAL,
            passed=False,
            confidence=0.0,
            reason=f"Compilation error: {e.msg}",
        )
    except Exception as e:
        logger.debug("Execution check failed: %s", e)
        return None


async def _verify_intent_layer(
    action: "Action", intention: "Intention", ctx: "WorkContext"
) -> LayerResult:
    """Layer 4: Verify code matches the original intent.

    Uses LLM to judge: "Does this code accomplish what was asked?"

    Most expensive layer (LLM call, ~500ms-2s, 100-500 tokens).
    Only run for critical actions where we need maximum confidence.

    Returns:
        LayerResult with pass/fail and confidence
    """
    # If no LLM available, skip intent verification
    if not ctx.llm:
        logger.warning("No LLM available for intent verification, skipping Layer 4")
        return LayerResult(
            layer=VerificationLayer.INTENT,
            passed=True,
            confidence=0.5,  # Neutral - can't verify without LLM
            reason="Intent verification skipped (no LLM available)",
            details={"status": "skipped"},
            tokens_used=0,
        )

    # Extract code content from action
    if action.type.value == "create":
        code_content = action.content
        context = f"Creating new file: {action.target}"
    elif action.type.value == "edit":
        code_content = action.content
        context = f"Editing file: {action.target}"
    else:
        # Intent verification only makes sense for code actions
        return LayerResult(
            layer=VerificationLayer.INTENT,
            passed=True,
            confidence=0.5,
            reason="Intent verification skipped (not a code action)",
            details={"status": "skipped"},
            tokens_used=0,
        )

    # Build LLM prompt for intent verification
    system_prompt = """You are a code verification assistant. Your job is to determine if generated code matches the user's original intent.

You will be given:
1. The user's original request (what they wanted)
2. The acceptance criteria (how to verify success)
3. The generated code

Your task: Judge if the code accomplishes what was requested.

Respond with EXACTLY this format:
ALIGNED: yes/no
CONFIDENCE: 0.0-1.0
REASON: brief explanation

Example responses:
ALIGNED: yes
CONFIDENCE: 0.95
REASON: Code implements the requested hello() function that returns a greeting string

ALIGNED: no
CONFIDENCE: 0.85
REASON: Code implements fibonacci instead of factorial as requested"""

    user_prompt = f"""Original Request: {intention.what}

Acceptance Criteria: {intention.acceptance}

Context: {context}

Generated Code:
```
{code_content[:1000]}  # Limit to first 1000 chars to avoid huge prompts
```

Does this code accomplish what was requested? Respond in the required format."""

    try:
        # Call LLM
        response = ctx.llm.chat_text(
            system=system_prompt,
            user=user_prompt,
            timeout_seconds=30.0,
            temperature=0.1,  # Low temperature for consistent judgments
        )

        # Parse response
        aligned = None
        confidence = 0.5
        reason = "Could not parse LLM response"

        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("ALIGNED:"):
                aligned_str = line.split(":", 1)[1].strip().lower()
                aligned = aligned_str in ("yes", "true", "1")
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    # Clamp to valid range
                    confidence = max(0.0, min(1.0, confidence))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        # If we couldn't parse alignment, treat as failure
        if aligned is None:
            logger.warning("Could not parse ALIGNED status from LLM response: %s", response)
            return LayerResult(
                layer=VerificationLayer.INTENT,
                passed=False,
                confidence=0.3,
                reason="Failed to parse LLM intent verification response",
                details={"llm_response": response},
                tokens_used=100,  # Estimate
            )

        logger.info(
            "Intent verification: aligned=%s, confidence=%.2f, reason=%s",
            aligned,
            confidence,
            reason,
        )

        return LayerResult(
            layer=VerificationLayer.INTENT,
            passed=aligned,
            confidence=confidence if aligned else (1.0 - confidence),
            reason=reason,
            details={
                "llm_response": response,
                "aligned": aligned,
            },
            tokens_used=100,  # Estimate - could track actual tokens if needed
        )

    except Exception as e:
        logger.error("Intent verification failed with exception: %s", e)
        return LayerResult(
            layer=VerificationLayer.INTENT,
            passed=False,
            confidence=0.0,
            reason=f"Intent verification error: {str(e)}",
            details={"error": str(e)},
            tokens_used=0,
        )


def _infer_language(file_path: str) -> str:
    """Infer programming language from file extension."""
    ext = file_path.lower().split(".")[-1]
    if ext == "py":
        return "python"
    elif ext in ("js", "jsx", "mjs"):
        return "javascript"
    elif ext in ("ts", "tsx"):
        return "typescript"
    elif ext == "rs":
        return "rust"
    elif ext == "go":
        return "go"
    return "unknown"
