#!/usr/bin/env python3
"""Analyze verification metrics from RIVA sessions.

This script analyzes metrics collected from real RIVA sessions to validate
the verification value proposition.

Usage:
    python scripts/analyze_verification_metrics.py --db path/to/riva.db --output report.md
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def analyze_verification_effectiveness(db_path: Path) -> dict[str, Any]:
    """Analyze verification effectiveness from metrics database.

    Args:
        db_path: Path to SQLite database with metrics

    Returns:
        Dictionary with analysis results
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Access columns by name
    cursor = conn.cursor()

    # Get all completed sessions
    cursor.execute("""
        SELECT * FROM riva_metrics
        WHERE completed_at IS NOT NULL
        ORDER BY started_at DESC
    """)

    # Note: To filter by model, use:
    # WHERE completed_at IS NOT NULL AND llm_provider = 'anthropic' AND llm_model = 'claude-sonnet-4'

    rows = cursor.fetchall()

    if not rows:
        return {"error": "No completed sessions found in database"}

    # Parse metrics JSON for detailed analysis
    import json

    sessions = []
    for row in rows:
        metrics_json = json.loads(row["metrics_json"])
        sessions.append({
            "session_id": row["session_id"],
            "llm_provider": row.get("llm_provider"),
            "llm_model": row.get("llm_model"),
            "success": bool(row["success"]),
            "first_try_success": bool(row["first_try_success"]),
            "total_time_ms": row["total_duration_ms"],
            "verification_time_ms": metrics_json["timing"]["verification_ms"],
            "verification_layers": metrics_json.get("verification_layers", {}),
            "confidence_calibration": metrics_json.get("confidence_calibration", {}),
        })

    # Calculate aggregate statistics
    total_sessions = len(sessions)
    success_count = sum(1 for s in sessions if s["success"])
    first_try_success_count = sum(1 for s in sessions if s["first_try_success"])

    success_rate = success_count / total_sessions
    first_try_rate = first_try_success_count / total_sessions

    # Analyze verification layer effectiveness
    syntax_passed = sum(
        s["verification_layers"].get("syntax", {}).get("passed", 0)
        for s in sessions
    )
    syntax_failed = sum(
        s["verification_layers"].get("syntax", {}).get("failed", 0)
        for s in sessions
    )

    semantic_passed = sum(
        s["verification_layers"].get("semantic", {}).get("passed", 0)
        for s in sessions
    )
    semantic_failed = sum(
        s["verification_layers"].get("semantic", {}).get("failed", 0)
        for s in sessions
    )

    behavioral_passed = sum(
        s["verification_layers"].get("behavioral", {}).get("passed", 0)
        for s in sessions
    )
    behavioral_failed = sum(
        s["verification_layers"].get("behavioral", {}).get("failed", 0)
        for s in sessions
    )

    intent_passed = sum(
        s["verification_layers"].get("intent", {}).get("passed", 0)
        for s in sessions
    )
    intent_failed = sum(
        s["verification_layers"].get("intent", {}).get("failed", 0)
        for s in sessions
    )

    # Calculate catch rates
    def catch_rate(passed: int, failed: int) -> float:
        total = passed + failed
        return failed / total if total > 0 else 0.0

    layer_catch_rates = {
        "syntax": catch_rate(syntax_passed, syntax_failed),
        "semantic": catch_rate(semantic_passed, semantic_failed),
        "behavioral": catch_rate(behavioral_passed, behavioral_failed),
        "intent": catch_rate(intent_passed, intent_failed),
    }

    # Total errors caught
    total_errors_caught = (
        syntax_failed + semantic_failed + behavioral_failed + intent_failed
    )

    # Average verification time
    avg_verification_time = (
        sum(s["verification_time_ms"] for s in sessions) / total_sessions
    )

    # Confidence calibration analysis
    all_predictions = []
    all_actuals = []
    for s in sessions:
        calibration = s["confidence_calibration"]
        if calibration.get("predictions") and calibration.get("actuals"):
            all_predictions.extend(calibration["predictions"])
            all_actuals.extend(calibration["actuals"])

    if all_predictions and all_actuals:
        # Calculate calibration metrics
        n = len(all_predictions)
        correct = sum(
            1
            for pred, actual in zip(all_predictions, all_actuals)
            if (pred >= 0.5 and actual) or (pred < 0.5 and not actual)
        )
        accuracy = correct / n

        # High confidence accuracy
        high_conf = [(p, a) for p, a in zip(all_predictions, all_actuals) if p >= 0.9]
        if high_conf:
            high_conf_correct = sum(1 for _, a in high_conf if a)
            high_conf_accuracy = high_conf_correct / len(high_conf)
        else:
            high_conf_accuracy = 0.0

        # Calibration error
        squared_errors = [
            (pred - (1.0 if actual else 0.0)) ** 2
            for pred, actual in zip(all_predictions, all_actuals)
        ]
        calibration_error = sum(squared_errors) / n

        confidence_metrics = {
            "accuracy": accuracy,
            "high_confidence_accuracy": high_conf_accuracy,
            "calibration_error": calibration_error,
            "sample_count": n,
        }
    else:
        confidence_metrics = {
            "accuracy": 0.0,
            "high_confidence_accuracy": 0.0,
            "calibration_error": 0.0,
            "sample_count": 0,
        }

    # Group by model for model-specific insights
    models_used = {}
    for s in sessions:
        model_key = f"{s['llm_provider'] or 'unknown'}/{s['llm_model'] or 'unknown'}"
        if model_key not in models_used:
            models_used[model_key] = 0
        models_used[model_key] += 1

    conn.close()

    return {
        "summary": {
            "total_sessions": total_sessions,
            "success_rate": success_rate,
            "first_try_success_rate": first_try_rate,
            "models_used": models_used,
        },
        "verification_impact": {
            "total_errors_caught": total_errors_caught,
            "avg_verification_time_ms": avg_verification_time,
            "layer_catch_rates": layer_catch_rates,
            "layer_stats": {
                "syntax": {"passed": syntax_passed, "failed": syntax_failed},
                "semantic": {"passed": semantic_passed, "failed": semantic_failed},
                "behavioral": {"passed": behavioral_passed, "failed": behavioral_failed},
                "intent": {"passed": intent_passed, "failed": intent_failed},
            },
        },
        "confidence_calibration": confidence_metrics,
    }


def generate_markdown_report(analysis: dict[str, Any]) -> str:
    """Generate a markdown report from analysis results.

    Args:
        analysis: Analysis results from analyze_verification_effectiveness()

    Returns:
        Markdown-formatted report string
    """
    if "error" in analysis:
        return f"# Error\n\n{analysis['error']}\n"

    summary = analysis["summary"]
    impact = analysis["verification_impact"]
    calibration = analysis["confidence_calibration"]
    layer_stats = impact["layer_stats"]
    catch_rates = impact["layer_catch_rates"]

    models_table = "\n".join([
        f"| {model} | {count} |"
        for model, count in sorted(summary.get('models_used', {}).items())
    ])

    report = f"""# RIVA Verification Impact Report

Generated from {summary['total_sessions']} real RIVA sessions.

## Summary

| Metric | Value |
|--------|-------|
| Total Sessions | {summary['total_sessions']} |
| Overall Success Rate | {summary['success_rate']:.1%} |
| First-Try Success Rate | {summary['first_try_success_rate']:.1%} |

### Models Used

| Model | Sessions |
|-------|----------|
{models_table}

## Verification Impact

**Total Errors Caught:** {impact['total_errors_caught']}

**Average Verification Time:** {impact['avg_verification_time_ms']:.0f}ms per session

### Layer Effectiveness

| Layer | Passed | Failed | Catch Rate |
|-------|--------|--------|------------|
| **Syntax** | {layer_stats['syntax']['passed']} | {layer_stats['syntax']['failed']} | {catch_rates['syntax']:.1%} |
| **Semantic** | {layer_stats['semantic']['passed']} | {layer_stats['semantic']['failed']} | {catch_rates['semantic']:.1%} |
| **Behavioral** | {layer_stats['behavioral']['passed']} | {layer_stats['behavioral']['failed']} | {catch_rates['behavioral']:.1%} |
| **Intent** | {layer_stats['intent']['passed']} | {layer_stats['intent']['failed']} | {catch_rates['intent']:.1%} |

**Interpretation:**
- **Catch Rate**: Percentage of checks that failed (higher = more errors caught)
- **Syntax Layer**: Catches {catch_rates['syntax']:.1%} of syntax checks → saves {layer_stats['syntax']['failed']} manual fixes
- **Semantic Layer**: Catches {catch_rates['semantic']:.1%} of semantic checks → saves {layer_stats['semantic']['failed']} runtime errors
- **Behavioral Layer**: Catches {catch_rates['behavioral']:.1%} of behavioral checks → saves {layer_stats['behavioral']['failed']} test failures
- **Intent Layer**: Catches {catch_rates['intent']:.1%} of intent checks → saves {layer_stats['intent']['failed']} wrong implementations

## Confidence Calibration

| Metric | Value |
|--------|-------|
| Overall Accuracy | {calibration['accuracy']:.1%} |
| High-Confidence Accuracy (≥0.9) | {calibration['high_confidence_accuracy']:.1%} |
| Calibration Error (MSE) | {calibration['calibration_error']:.3f} |
| Sample Count | {calibration['sample_count']} |

**Interpretation:**
- When RIVA predicts high confidence (≥0.9), it's correct {calibration['high_confidence_accuracy']:.1%} of the time
- Lower calibration error = better calibrated predictions
- Sample count: {calibration['sample_count']} confidence predictions analyzed

## Value Proposition

### The Tradeoff

**Time Cost:** {impact['avg_verification_time_ms']:.0f}ms average verification overhead

**Benefit:**
- {impact['total_errors_caught']} errors caught before reaching user
- {summary['first_try_success_rate']:.1%} first-try success rate
- {calibration['high_confidence_accuracy']:.1%} accuracy on high-confidence predictions

### Is It Worth It?

**Without verification:**
- User sees errors immediately
- Must manually debug and fix
- Lower confidence in generated code

**With verification:**
- Errors caught in {impact['avg_verification_time_ms']:.0f}ms
- User only sees validated code
- {calibration['high_confidence_accuracy']:.1%} confidence when RIVA says "I'm sure"

**Verdict:** Trade {impact['avg_verification_time_ms']/1000:.1f}s for {impact['total_errors_caught']/summary['total_sessions']:.1f} errors caught per session.

---

*This report validates RIVA's verification value proposition with real usage data.*
"""

    return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze RIVA verification metrics from database"
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to SQLite database with metrics",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("verification_report.md"),
        help="Output file for markdown report",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: Database not found: {args.db}")
        sys.exit(1)

    print(f"Analyzing metrics from: {args.db}")

    # Analyze
    analysis = analyze_verification_effectiveness(args.db)

    # Generate report
    report = generate_markdown_report(analysis)

    # Save report
    with open(args.output, "w") as f:
        f.write(report)

    # Print to stdout
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)
    print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
