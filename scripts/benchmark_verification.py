#!/usr/bin/env python3
"""Benchmark script to measure verification system impact.

This script runs RIVA with and without multi-layer verification to measure:
- First-try success rate improvement
- Errors caught by each verification layer
- Time overhead from verification
- Confidence calibration accuracy

Usage:
    python scripts/benchmark_verification.py --scenarios 10 --output results.json
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode import (
    Action,
    ActionType,
    AutoCheckpoint,
    CodeSandbox,
    Intention,
    IntentionStatus,
    Judgment,
    WorkContext,
    riva_work,
)
from reos.code_mode.optimization.metrics import create_metrics


@dataclass
class TestScenario:
    """A test scenario for benchmarking."""

    name: str
    description: str
    intention_what: str
    intention_acceptance: str
    expected_action_type: ActionType
    has_intentional_error: bool = False
    error_type: str | None = None  # "syntax", "semantic", "behavioral", "intent"


# Define realistic test scenarios
TEST_SCENARIOS = [
    # ===== Simple scenarios (should succeed quickly) =====
    TestScenario(
        name="simple_function_creation",
        description="Create a simple hello() function",
        intention_what="Create a hello() function that returns 'Hello, World!'",
        intention_acceptance="Function exists and returns correct string",
        expected_action_type=ActionType.CREATE,
    ),
    TestScenario(
        name="simple_file_creation",
        description="Create a basic Python module",
        intention_what="Create a new file math_utils.py with an add() function",
        intention_acceptance="File exists with add function that adds two numbers",
        expected_action_type=ActionType.CREATE,
    ),
    # ===== Scenarios with syntax errors (Layer 1 should catch) =====
    TestScenario(
        name="syntax_error_missing_colon",
        description="Code with missing colon",
        intention_what="Create function with syntax error (missing colon)",
        intention_acceptance="Should fail syntax validation",
        expected_action_type=ActionType.CREATE,
        has_intentional_error=True,
        error_type="syntax",
    ),
    # ===== Scenarios with semantic errors (Layer 2 should catch) =====
    TestScenario(
        name="semantic_error_undefined_var",
        description="Code using undefined variable",
        intention_what="Create function that uses undefined variable",
        intention_acceptance="Should fail semantic validation",
        expected_action_type=ActionType.CREATE,
        has_intentional_error=True,
        error_type="semantic",
    ),
    TestScenario(
        name="semantic_error_missing_import",
        description="Code using module without import",
        intention_what="Create function using json without importing it",
        intention_acceptance="Should fail semantic validation",
        expected_action_type=ActionType.CREATE,
        has_intentional_error=True,
        error_type="semantic",
    ),
    # ===== Scenarios with behavioral errors (Layer 3 should catch) =====
    TestScenario(
        name="behavioral_error_division_by_zero",
        description="Code that divides by zero",
        intention_what="Create divide() function with test that divides by zero",
        intention_acceptance="Should fail when tests run",
        expected_action_type=ActionType.CREATE,
        has_intentional_error=True,
        error_type="behavioral",
    ),
    # ===== Scenarios with intent misalignment (Layer 4 should catch) =====
    TestScenario(
        name="intent_error_wrong_function",
        description="Implement wrong function (fibonacci instead of factorial)",
        intention_what="Create a factorial() function",
        intention_acceptance="Should detect fibonacci was implemented instead",
        expected_action_type=ActionType.CREATE,
        has_intentional_error=True,
        error_type="intent",
    ),
]


@dataclass
class BenchmarkResult:
    """Result from running a benchmark scenario."""

    scenario_name: str
    mode: str  # "with_verification" or "without_verification"
    intention_status: str
    first_try_success: bool
    total_cycles: int
    total_time_ms: int
    verification_time_ms: int
    errors_caught: int
    layer_results: dict[str, Any]
    confidence_scores: list[float]


class VerificationBenchmark:
    """Benchmark harness for measuring verification impact."""

    def __init__(self, sandbox_dir: Path):
        """Initialize benchmark.

        Args:
            sandbox_dir: Directory to use as sandbox (will be cleaned)
        """
        self.sandbox_dir = sandbox_dir
        self.results: list[BenchmarkResult] = []

    def run_scenario(
        self,
        scenario: TestScenario,
        enable_verification: bool,
    ) -> BenchmarkResult:
        """Run a single scenario with or without verification.

        Args:
            scenario: Test scenario to run
            enable_verification: Whether to enable multi-layer verification

        Returns:
            BenchmarkResult with outcome and metrics
        """
        # Create clean sandbox
        sandbox = CodeSandbox(self.sandbox_dir)
        (self.sandbox_dir / "src").mkdir(exist_ok=True)
        (self.sandbox_dir / "tests").mkdir(exist_ok=True)

        # Create intention
        intention = Intention.create(
            what=scenario.intention_what,
            acceptance=scenario.intention_acceptance,
        )

        # Create checkpoint (auto for now, no LLM needed for simple scenarios)
        checkpoint = AutoCheckpoint(sandbox=sandbox)

        # Create metrics
        metrics = create_metrics(f"benchmark_{scenario.name}")

        # Create context with verification enabled/disabled
        ctx = WorkContext(
            sandbox=sandbox,
            llm=None,  # Use heuristics for simple scenarios
            checkpoint=checkpoint,
            metrics=metrics,
            max_depth=3,
            max_cycles_per_intention=5,
            enable_multilayer_verification=enable_verification,
        )

        start_time = time.perf_counter()

        # Run RIVA
        try:
            riva_work(intention, ctx)
        except Exception as e:
            print(f"Error running scenario {scenario.name}: {e}")

        end_time = time.perf_counter()
        total_time_ms = int((end_time - start_time) * 1000)

        # Mark metrics as complete
        metrics.complete(intention.status == IntentionStatus.VERIFIED)

        # Extract results
        result = BenchmarkResult(
            scenario_name=scenario.name,
            mode="with_verification" if enable_verification else "without_verification",
            intention_status=intention.status.value,
            first_try_success=metrics.first_try_success,
            total_cycles=len(intention.trace),
            total_time_ms=total_time_ms,
            verification_time_ms=metrics.verification_time_ms,
            errors_caught=metrics.get_verification_impact()["errors_caught"],
            layer_results=metrics.get_layer_catch_rates(),
            confidence_scores=metrics.confidence_predictions,
        )

        self.results.append(result)
        return result

    def run_all_scenarios(self) -> None:
        """Run all test scenarios in both modes."""
        print("Running verification benchmarks...")
        print(f"Total scenarios: {len(TEST_SCENARIOS)}")
        print()

        for i, scenario in enumerate(TEST_SCENARIOS, 1):
            print(f"[{i}/{len(TEST_SCENARIOS)}] {scenario.name}")
            print(f"  Description: {scenario.description}")

            # Run with verification
            print("  Running WITH verification...")
            result_with = self.run_scenario(scenario, enable_verification=True)
            print(f"    → Status: {result_with.intention_status}, Time: {result_with.total_time_ms}ms")

            # Run without verification
            print("  Running WITHOUT verification...")
            result_without = self.run_scenario(scenario, enable_verification=False)
            print(f"    → Status: {result_without.intention_status}, Time: {result_without.total_time_ms}ms")

            print()

    def generate_report(self) -> dict[str, Any]:
        """Generate comparison report from collected results.

        Returns:
            Dictionary with analysis of verification impact
        """
        # Separate results by mode
        with_verification = [r for r in self.results if r.mode == "with_verification"]
        without_verification = [r for r in self.results if r.mode == "without_verification"]

        def calculate_stats(results: list[BenchmarkResult]) -> dict[str, Any]:
            if not results:
                return {}

            total = len(results)
            first_try_successes = sum(1 for r in results if r.first_try_success)
            avg_time = sum(r.total_time_ms for r in results) / total
            avg_verification_time = sum(r.verification_time_ms for r in results) / total
            total_errors_caught = sum(r.errors_caught for r in results)

            return {
                "total_scenarios": total,
                "first_try_success_rate": first_try_successes / total if total > 0 else 0,
                "avg_total_time_ms": avg_time,
                "avg_verification_time_ms": avg_verification_time,
                "total_errors_caught": total_errors_caught,
                "avg_errors_per_scenario": total_errors_caught / total if total > 0 else 0,
            }

        report = {
            "summary": {
                "total_scenarios_run": len(self.results),
                "scenarios": [s.name for s in TEST_SCENARIOS],
            },
            "with_verification": calculate_stats(with_verification),
            "without_verification": calculate_stats(without_verification),
            "comparison": {},
        }

        # Calculate improvement metrics if we have both modes
        if with_verification and without_verification:
            with_stats = report["with_verification"]
            without_stats = report["without_verification"]

            success_rate_with = with_stats["first_try_success_rate"]
            success_rate_without = without_stats["first_try_success_rate"]
            success_improvement = success_rate_with - success_rate_without

            time_with = with_stats["avg_total_time_ms"]
            time_without = without_stats["avg_total_time_ms"]
            time_overhead = time_with - time_without

            report["comparison"] = {
                "success_rate_improvement": success_improvement,
                "success_rate_improvement_pct": success_improvement * 100,
                "time_overhead_ms": time_overhead,
                "time_overhead_pct": (time_overhead / time_without * 100) if time_without > 0 else 0,
                "errors_caught_by_verification": with_stats["total_errors_caught"],
            }

        return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark RIVA verification system")
    parser.add_argument(
        "--sandbox",
        type=Path,
        default=Path("/tmp/riva_benchmark_sandbox"),
        help="Directory to use as sandbox",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark_results.json"),
        help="Output file for results",
    )
    args = parser.parse_args()

    # Create sandbox directory
    args.sandbox.mkdir(parents=True, exist_ok=True)

    # Run benchmarks
    benchmark = VerificationBenchmark(args.sandbox)
    benchmark.run_all_scenarios()

    # Generate report
    report = benchmark.generate_report()

    # Save results
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(json.dumps(report, indent=2))
    print()
    print(f"Full results saved to: {args.output}")


if __name__ == "__main__":
    main()
