"""Execution metrics collection for RIVA optimization analysis.

This module provides metrics collection to understand where time and
tokens are being spent. Measure first, optimize second.

The goal is to identify:
- Where LLM calls are happening
- What decompositions could have been skipped
- What verifications could have been batched
- Overall success/failure patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """Metrics for a single RIVA execution session.

    Tracks timing, counts, and outcomes to inform optimization decisions.
    All fields are optional and only populated when relevant.
    """

    session_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    # Timing (milliseconds)
    total_duration_ms: int = 0
    llm_time_ms: int = 0
    verification_time_ms: int = 0
    execution_time_ms: int = 0

    # LLM call counts
    llm_calls_total: int = 0
    llm_calls_decomposition: int = 0
    llm_calls_action: int = 0
    llm_calls_verification: int = 0
    llm_calls_reflection: int = 0

    # Decomposition tracking
    decomposition_count: int = 0
    max_depth_reached: int = 0

    # Verification tracking
    verifications_total: int = 0
    verifications_high_risk: int = 0
    verifications_medium_risk: int = 0
    verifications_low_risk: int = 0

    # Retry tracking
    retry_count: int = 0
    failure_count: int = 0

    # Outcomes
    success: bool = False
    first_try_success: bool = False

    # Optimization analysis (what COULD have been optimized)
    # These are populated by analyzing the execution after the fact
    skippable_decompositions: int = 0  # Simple tasks that were decomposed
    skippable_verifications: int = 0  # Low-risk actions verified individually
    batchable_verifications: int = 0  # Verifications that could be batched

    # Token usage (if available from provider)
    tokens_input: int = 0
    tokens_output: int = 0

    # Verification layer tracking (detailed breakdown)
    verification_layer_results: list[dict[str, Any]] = field(default_factory=list)
    syntax_layer_passed: int = 0
    syntax_layer_failed: int = 0
    semantic_layer_passed: int = 0
    semantic_layer_failed: int = 0
    behavioral_layer_passed: int = 0
    behavioral_layer_failed: int = 0
    intent_layer_passed: int = 0
    intent_layer_failed: int = 0

    # Confidence calibration (predicted vs actual)
    confidence_predictions: list[float] = field(default_factory=list)
    confidence_actuals: list[bool] = field(default_factory=list)

    # Verification time breakdown
    syntax_layer_time_ms: int = 0
    semantic_layer_time_ms: int = 0
    behavioral_layer_time_ms: int = 0
    intent_layer_time_ms: int = 0

    def record_llm_call(
        self,
        purpose: str,
        duration_ms: int,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record an LLM call."""
        self.llm_calls_total += 1
        self.llm_time_ms += duration_ms
        self.tokens_input += tokens_in
        self.tokens_output += tokens_out

        if purpose == "decomposition":
            self.llm_calls_decomposition += 1
        elif purpose == "action":
            self.llm_calls_action += 1
        elif purpose == "verification":
            self.llm_calls_verification += 1
        elif purpose == "reflection":
            self.llm_calls_reflection += 1

    def record_decomposition(self, depth: int) -> None:
        """Record a decomposition event."""
        self.decomposition_count += 1
        self.max_depth_reached = max(self.max_depth_reached, depth)

    def record_verification(self, risk_level: str) -> None:
        """Record a verification event."""
        self.verifications_total += 1
        if risk_level == "high":
            self.verifications_high_risk += 1
        elif risk_level == "medium":
            self.verifications_medium_risk += 1
        elif risk_level == "low":
            self.verifications_low_risk += 1

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self.retry_count += 1

    def record_failure(self) -> None:
        """Record a failure."""
        self.failure_count += 1

    def record_verification_layers(self, verification_result: Any) -> None:
        """Record results from multi-layer verification.

        Args:
            verification_result: VerificationResult from verify_action_multilayer()
        """
        # Store full result for analysis
        result_dict = {
            "overall_passed": verification_result.overall_passed,
            "overall_confidence": verification_result.overall_confidence,
            "total_duration_ms": verification_result.total_duration_ms,
            "layers": [],
        }

        for layer_result in verification_result.layers:
            layer_name = layer_result.layer.value
            passed = layer_result.passed
            confidence = layer_result.confidence
            duration_ms = layer_result.duration_ms

            # Track per-layer pass/fail counts
            if layer_name == "syntax":
                if passed:
                    self.syntax_layer_passed += 1
                else:
                    self.syntax_layer_failed += 1
                self.syntax_layer_time_ms += duration_ms
            elif layer_name == "semantic":
                if passed:
                    self.semantic_layer_passed += 1
                else:
                    self.semantic_layer_failed += 1
                self.semantic_layer_time_ms += duration_ms
            elif layer_name == "behavioral":
                if passed:
                    self.behavioral_layer_passed += 1
                else:
                    self.behavioral_layer_failed += 1
                self.behavioral_layer_time_ms += duration_ms
            elif layer_name == "intent":
                if passed:
                    self.intent_layer_passed += 1
                else:
                    self.intent_layer_failed += 1
                self.intent_layer_time_ms += duration_ms

            # Store layer details
            result_dict["layers"].append({
                "layer": layer_name,
                "passed": passed,
                "confidence": confidence,
                "duration_ms": duration_ms,
                "reason": layer_result.reason,
            })

        self.verification_layer_results.append(result_dict)
        self.verification_time_ms += verification_result.total_duration_ms

    def record_confidence_prediction(self, predicted_confidence: float, actual_success: bool) -> None:
        """Record a confidence prediction and its actual outcome.

        This allows us to measure confidence calibration:
        - Are high-confidence predictions actually successful?
        - Are low-confidence predictions actually failures?

        Args:
            predicted_confidence: Confidence score (0.0-1.0) from verification
            actual_success: Did the action actually succeed?
        """
        self.confidence_predictions.append(predicted_confidence)
        self.confidence_actuals.append(actual_success)

    def complete(self, success: bool) -> None:
        """Mark execution as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.success = success
        self.total_duration_ms = int(
            (self.completed_at - self.started_at).total_seconds() * 1000
        )
        # First try success = no retries and succeeded
        self.first_try_success = success and self.retry_count == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/analysis."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "timing": {
                "total_ms": self.total_duration_ms,
                "llm_ms": self.llm_time_ms,
                "verification_ms": self.verification_time_ms,
                "execution_ms": self.execution_time_ms,
            },
            "llm_calls": {
                "total": self.llm_calls_total,
                "decomposition": self.llm_calls_decomposition,
                "action": self.llm_calls_action,
                "verification": self.llm_calls_verification,
                "reflection": self.llm_calls_reflection,
            },
            "decomposition": {
                "count": self.decomposition_count,
                "max_depth": self.max_depth_reached,
            },
            "verifications": {
                "total": self.verifications_total,
                "high_risk": self.verifications_high_risk,
                "medium_risk": self.verifications_medium_risk,
                "low_risk": self.verifications_low_risk,
            },
            "retries": self.retry_count,
            "failures": self.failure_count,
            "outcome": {
                "success": self.success,
                "first_try": self.first_try_success,
            },
            "optimization_potential": {
                "skippable_decompositions": self.skippable_decompositions,
                "skippable_verifications": self.skippable_verifications,
                "batchable_verifications": self.batchable_verifications,
            },
            "tokens": {
                "input": self.tokens_input,
                "output": self.tokens_output,
            },
            "verification_layers": {
                "syntax": {
                    "passed": self.syntax_layer_passed,
                    "failed": self.syntax_layer_failed,
                    "time_ms": self.syntax_layer_time_ms,
                },
                "semantic": {
                    "passed": self.semantic_layer_passed,
                    "failed": self.semantic_layer_failed,
                    "time_ms": self.semantic_layer_time_ms,
                },
                "behavioral": {
                    "passed": self.behavioral_layer_passed,
                    "failed": self.behavioral_layer_failed,
                    "time_ms": self.behavioral_layer_time_ms,
                },
                "intent": {
                    "passed": self.intent_layer_passed,
                    "failed": self.intent_layer_failed,
                    "time_ms": self.intent_layer_time_ms,
                },
                "results": self.verification_layer_results,
            },
            "confidence_calibration": {
                "predictions": self.confidence_predictions,
                "actuals": self.confidence_actuals,
                "count": len(self.confidence_predictions),
            },
        }

    def get_layer_catch_rates(self) -> dict[str, float]:
        """Calculate what percentage of errors each layer caught.

        Returns:
            Dictionary with layer names and their catch rates (0.0-1.0)
        """
        catch_rates = {}

        # Syntax layer
        total_syntax = self.syntax_layer_passed + self.syntax_layer_failed
        if total_syntax > 0:
            catch_rates["syntax"] = self.syntax_layer_failed / total_syntax
        else:
            catch_rates["syntax"] = 0.0

        # Semantic layer
        total_semantic = self.semantic_layer_passed + self.semantic_layer_failed
        if total_semantic > 0:
            catch_rates["semantic"] = self.semantic_layer_failed / total_semantic
        else:
            catch_rates["semantic"] = 0.0

        # Behavioral layer
        total_behavioral = self.behavioral_layer_passed + self.behavioral_layer_failed
        if total_behavioral > 0:
            catch_rates["behavioral"] = self.behavioral_layer_failed / total_behavioral
        else:
            catch_rates["behavioral"] = 0.0

        # Intent layer
        total_intent = self.intent_layer_passed + self.intent_layer_failed
        if total_intent > 0:
            catch_rates["intent"] = self.intent_layer_failed / total_intent
        else:
            catch_rates["intent"] = 0.0

        return catch_rates

    def get_confidence_calibration(self) -> dict[str, float]:
        """Calculate how well-calibrated our confidence predictions are.

        Returns:
            Dictionary with calibration metrics:
            - accuracy: Overall accuracy of predictions
            - high_confidence_accuracy: Accuracy when confidence >= 0.9
            - low_confidence_accuracy: Accuracy when confidence < 0.7
            - calibration_error: Mean squared difference between confidence and actual
        """
        if not self.confidence_predictions or not self.confidence_actuals:
            return {
                "accuracy": 0.0,
                "high_confidence_accuracy": 0.0,
                "low_confidence_accuracy": 0.0,
                "calibration_error": 0.0,
                "sample_count": 0,
            }

        n = len(self.confidence_predictions)
        correct_count = sum(1 for pred, actual in zip(self.confidence_predictions, self.confidence_actuals) if (pred >= 0.5 and actual) or (pred < 0.5 and not actual))
        accuracy = correct_count / n if n > 0 else 0.0

        # High confidence accuracy (predictions >= 0.9)
        high_conf_pairs = [(p, a) for p, a in zip(self.confidence_predictions, self.confidence_actuals) if p >= 0.9]
        if high_conf_pairs:
            high_conf_correct = sum(1 for _, actual in high_conf_pairs if actual)
            high_confidence_accuracy = high_conf_correct / len(high_conf_pairs)
        else:
            high_confidence_accuracy = 0.0

        # Low confidence accuracy (predictions < 0.7)
        low_conf_pairs = [(p, a) for p, a in zip(self.confidence_predictions, self.confidence_actuals) if p < 0.7]
        if low_conf_pairs:
            low_conf_correct = sum(1 for _, actual in low_conf_pairs if not actual)  # Should be failures
            low_confidence_accuracy = low_conf_correct / len(low_conf_pairs)
        else:
            low_confidence_accuracy = 0.0

        # Calibration error (mean squared error between confidence and actual)
        squared_errors = [(pred - (1.0 if actual else 0.0)) ** 2 for pred, actual in zip(self.confidence_predictions, self.confidence_actuals)]
        calibration_error = sum(squared_errors) / n if n > 0 else 0.0

        return {
            "accuracy": accuracy,
            "high_confidence_accuracy": high_confidence_accuracy,
            "low_confidence_accuracy": low_confidence_accuracy,
            "calibration_error": calibration_error,
            "sample_count": n,
        }

    def get_verification_impact(self) -> dict[str, Any]:
        """Calculate the impact of verification on success rates.

        Returns:
            Dictionary with impact metrics:
            - total_verifications: Total number of verifications run
            - errors_caught: Number of errors caught by verification
            - avg_verification_time_ms: Average time spent on verification
            - first_try_success: Whether we succeeded on first try
        """
        total_layer_checks = (
            self.syntax_layer_passed + self.syntax_layer_failed +
            self.semantic_layer_passed + self.semantic_layer_failed +
            self.behavioral_layer_passed + self.behavioral_layer_failed +
            self.intent_layer_passed + self.intent_layer_failed
        )

        errors_caught = (
            self.syntax_layer_failed +
            self.semantic_layer_failed +
            self.behavioral_layer_failed +
            self.intent_layer_failed
        )

        avg_verification_time = self.verification_time_ms / total_layer_checks if total_layer_checks > 0 else 0

        return {
            "total_verifications": total_layer_checks,
            "errors_caught": errors_caught,
            "error_catch_rate": errors_caught / total_layer_checks if total_layer_checks > 0 else 0.0,
            "avg_verification_time_ms": avg_verification_time,
            "total_verification_time_ms": self.verification_time_ms,
            "first_try_success": self.first_try_success,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Session {self.session_id}: "
            f"{'SUCCESS' if self.success else 'FAILED'} in {self.total_duration_ms}ms, "
            f"{self.llm_calls_total} LLM calls, "
            f"{self.decomposition_count} decompositions, "
            f"{self.verifications_total} verifications"
        )


def create_metrics(session_id: str) -> ExecutionMetrics:
    """Create a new metrics instance for a session."""
    return ExecutionMetrics(session_id=session_id)


class MetricsStore:
    """Database-backed storage for execution metrics.

    Stores metrics for analysis and baseline measurement.
    """

    def __init__(self, db: Any):
        """Initialize metrics store.

        Args:
            db: Database connection with execute/fetchall methods
        """
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create metrics table if it doesn't exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS riva_metrics (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_duration_ms INTEGER,
                llm_time_ms INTEGER,
                execution_time_ms INTEGER,
                llm_calls_total INTEGER,
                decomposition_count INTEGER,
                max_depth_reached INTEGER,
                verifications_total INTEGER,
                retry_count INTEGER,
                failure_count INTEGER,
                success INTEGER,
                first_try_success INTEGER,
                metrics_json TEXT
            )
        """)

    def save(self, metrics: ExecutionMetrics) -> None:
        """Save metrics to database."""
        import json

        self.db.execute(
            """
            INSERT OR REPLACE INTO riva_metrics (
                session_id, started_at, completed_at,
                total_duration_ms, llm_time_ms, execution_time_ms,
                llm_calls_total, decomposition_count, max_depth_reached,
                verifications_total, retry_count, failure_count,
                success, first_try_success, metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.session_id,
                metrics.started_at.isoformat(),
                metrics.completed_at.isoformat() if metrics.completed_at else None,
                metrics.total_duration_ms,
                metrics.llm_time_ms,
                metrics.execution_time_ms,
                metrics.llm_calls_total,
                metrics.decomposition_count,
                metrics.max_depth_reached,
                metrics.verifications_total,
                metrics.retry_count,
                metrics.failure_count,
                1 if metrics.success else 0,
                1 if metrics.first_try_success else 0,
                json.dumps(metrics.to_dict()),
            ),
        )

    def get_baseline_stats(self, limit: int = 100) -> dict[str, Any]:
        """Calculate baseline statistics from recent executions.

        Returns aggregate stats useful for optimization decisions.
        """
        rows = self.db.fetchall(
            """
            SELECT
                COUNT(*) as total_sessions,
                AVG(total_duration_ms) as avg_duration_ms,
                AVG(llm_time_ms) as avg_llm_time_ms,
                AVG(llm_calls_total) as avg_llm_calls,
                AVG(decomposition_count) as avg_decompositions,
                AVG(verifications_total) as avg_verifications,
                SUM(success) as success_count,
                SUM(first_try_success) as first_try_count,
                AVG(max_depth_reached) as avg_depth
            FROM riva_metrics
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )

        if not rows or not rows[0]:
            return {"error": "No metrics data available"}

        row = rows[0]
        total = row[0] or 0

        return {
            "sample_size": total,
            "avg_duration_ms": round(row[1] or 0, 1),
            "avg_llm_time_ms": round(row[2] or 0, 1),
            "avg_llm_calls": round(row[3] or 0, 2),
            "avg_decompositions": round(row[4] or 0, 2),
            "avg_verifications": round(row[5] or 0, 2),
            "success_rate": round((row[6] or 0) / total * 100, 1) if total > 0 else 0,
            "first_try_rate": round((row[7] or 0) / total * 100, 1) if total > 0 else 0,
            "avg_depth": round(row[8] or 0, 2),
        }

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent metrics for review."""
        rows = self.db.fetchall(
            """
            SELECT session_id, started_at, total_duration_ms,
                   llm_calls_total, decomposition_count, success
            FROM riva_metrics
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )

        return [
            {
                "session_id": row[0],
                "started_at": row[1],
                "duration_ms": row[2],
                "llm_calls": row[3],
                "decompositions": row[4],
                "success": bool(row[5]),
            }
            for row in rows
        ]
