"""Verification pipeline that runs all 5 layers.

The pipeline orchestrates verification across all layers:
1. Syntax (fast, no LLM)
2. Semantic (fast, no LLM)
3. Behavioral (fast, no LLM)
4. Safety (fast, no LLM) - MUST PASS
5. Intent (may use LLM)

The pipeline can run in different modes:
- Full: All 5 layers
- Fast: Only syntax, safety (minimum required)
- Standard: All layers except intent (no LLM)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time

from ..models import AtomicOperation, OperationStatus, VerificationLayer, VerificationResult
from .base import BaseVerifier, VerificationContext
from .syntax import SyntaxVerifier
from .semantic import SemanticVerifier
from .behavioral import BehavioralVerifier
from .safety import SafetyVerifier
from .intent import IntentVerifier, LLMProvider


class VerificationMode(str, Enum):
    """Verification pipeline modes."""
    FAST = "fast"        # Only syntax and safety
    STANDARD = "standard"  # All except intent (no LLM)
    FULL = "full"        # All 5 layers including LLM intent


@dataclass
class PipelineResult:
    """Result of running the verification pipeline."""
    passed: bool
    status: OperationStatus
    results: dict[str, VerificationResult]
    blocking_layer: Optional[str] = None
    overall_confidence: float = 0.0
    total_time_ms: int = 0
    warnings: list[str] = field(default_factory=list)


class VerificationPipeline:
    """Orchestrates the 5-layer verification system.

    The pipeline runs verifiers in order and can stop early
    if a critical failure is detected (e.g., safety failure).
    """

    def __init__(
        self,
        mode: VerificationMode = VerificationMode.STANDARD,
        llm_provider: Optional[LLMProvider] = None,
    ):
        """Initialize verification pipeline.

        Args:
            mode: Verification mode (fast, standard, full).
            llm_provider: Optional LLM provider for intent verification.
        """
        self.mode = mode

        # Initialize verifiers
        self.syntax = SyntaxVerifier()
        self.semantic = SemanticVerifier()
        self.behavioral = BehavioralVerifier()
        self.safety = SafetyVerifier()
        self.intent = IntentVerifier(llm_provider)

        # Layer order (safety is checked after syntax but results are critical)
        self._layer_order: list[tuple[VerificationLayer, BaseVerifier]] = [
            (VerificationLayer.SYNTAX, self.syntax),
            (VerificationLayer.SAFETY, self.safety),
            (VerificationLayer.SEMANTIC, self.semantic),
            (VerificationLayer.BEHAVIORAL, self.behavioral),
            (VerificationLayer.INTENT, self.intent),
        ]

    def set_mode(self, mode: VerificationMode):
        """Change verification mode."""
        self.mode = mode

    def set_llm_provider(self, provider: LLMProvider):
        """Set LLM provider for intent verification."""
        self.intent.set_llm_provider(provider)

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> PipelineResult:
        """Run verification pipeline on an operation.

        Args:
            operation: Operation to verify.
            context: Verification context.

        Returns:
            PipelineResult with all verification results.
        """
        start_time = time.time()
        results: dict[str, VerificationResult] = {}
        warnings: list[str] = []
        blocking_layer = None

        # Determine which layers to run
        layers_to_run = self._get_layers_for_mode(context)

        for layer, verifier in layers_to_run:
            # Run verification with timing
            result = verifier._timed_verify(operation, context)
            results[layer.value] = result

            # Collect warnings
            if result.issues:
                for issue in result.issues:
                    warnings.append(f"[{layer.value}] {issue}")

            # Check for blocking failures
            if not result.passed:
                if layer == VerificationLayer.SAFETY:
                    # Safety failure is always blocking
                    blocking_layer = layer.value
                    break
                elif layer == VerificationLayer.SYNTAX:
                    # Syntax failure prevents further verification
                    blocking_layer = layer.value
                    break
                # Other layers can fail without blocking

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(results)

        # Determine final status
        passed = blocking_layer is None
        if passed:
            # Check if any layer failed (non-blocking)
            failed_layers = [l for l, r in results.items() if not r.passed]
            if failed_layers:
                passed = False
                blocking_layer = failed_layers[0]

        # Determine operation status
        if passed:
            if warnings:
                status = OperationStatus.AWAITING_APPROVAL
            else:
                status = OperationStatus.EXECUTING
        else:
            status = OperationStatus.FAILED

        total_time = int((time.time() - start_time) * 1000)

        return PipelineResult(
            passed=passed,
            status=status,
            results=results,
            blocking_layer=blocking_layer,
            overall_confidence=overall_confidence,
            total_time_ms=total_time,
            warnings=warnings,
        )

    def _get_layers_for_mode(
        self,
        context: VerificationContext,
    ) -> list[tuple[VerificationLayer, BaseVerifier]]:
        """Get layers to run based on mode."""
        if self.mode == VerificationMode.FAST:
            # Only syntax and safety
            return [
                (VerificationLayer.SYNTAX, self.syntax),
                (VerificationLayer.SAFETY, self.safety),
            ]

        elif self.mode == VerificationMode.STANDARD:
            # All except intent
            return [
                (VerificationLayer.SYNTAX, self.syntax),
                (VerificationLayer.SAFETY, self.safety),
                (VerificationLayer.SEMANTIC, self.semantic),
                (VerificationLayer.BEHAVIORAL, self.behavioral),
            ]

        else:  # FULL
            # All layers (intent only if LLM available)
            layers = [
                (VerificationLayer.SYNTAX, self.syntax),
                (VerificationLayer.SAFETY, self.safety),
                (VerificationLayer.SEMANTIC, self.semantic),
                (VerificationLayer.BEHAVIORAL, self.behavioral),
            ]

            if context.llm_available:
                layers.append((VerificationLayer.INTENT, self.intent))

            return layers

    def _calculate_overall_confidence(
        self,
        results: dict[str, VerificationResult],
    ) -> float:
        """Calculate weighted overall confidence."""
        if not results:
            return 0.0

        # Weights for each layer
        weights = {
            VerificationLayer.SYNTAX.value: 0.15,
            VerificationLayer.SEMANTIC.value: 0.20,
            VerificationLayer.BEHAVIORAL.value: 0.20,
            VerificationLayer.SAFETY.value: 0.25,
            VerificationLayer.INTENT.value: 0.20,
        }

        total_weight = 0.0
        weighted_confidence = 0.0

        for layer, result in results.items():
            weight = weights.get(layer, 0.1)
            total_weight += weight

            # Failed layers contribute 0 to confidence
            if result.passed:
                weighted_confidence += result.confidence * weight
            else:
                weighted_confidence += 0.0

        if total_weight == 0:
            return 0.0

        return weighted_confidence / total_weight

    def verify_batch(
        self,
        operations: list[AtomicOperation],
        context: VerificationContext,
    ) -> list[PipelineResult]:
        """Verify multiple operations.

        Args:
            operations: Operations to verify.
            context: Shared verification context.

        Returns:
            List of PipelineResults in same order as input.
        """
        return [self.verify(op, context) for op in operations]

    def reset(self):
        """Reset verifier state (e.g., rate limit counters)."""
        self.safety.reset_counters()
