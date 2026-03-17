"""CLI entry point for the ReOS benchmark framework.

Usage:
    python -m benchmarks run --model MODEL [--category CAT] [--resume] [--no-context]
    python -m benchmarks run --all-models
    python -m benchmarks analyze [--model MODEL] [--compare-all]
    python -m benchmarks export --output FILE.csv
    python -m benchmarks list-cases [--category CAT]

Examples:
    python -m benchmarks list-cases --category dangerous
    python -m benchmarks run --model qwen2.5:7b --category files
    python -m benchmarks analyze --model qwen2.5:7b
    python -m benchmarks export --output results.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from benchmarks.corpus import load_corpus, summarize_corpus
from benchmarks.db import DEFAULT_DB_PATH, get_connection
from benchmarks.models import MODEL_MATRIX


def _cmd_list_cases(args: argparse.Namespace) -> None:
    """List corpus test cases, optionally filtered by category."""
    cases = load_corpus(
        category=args.category if args.category else None,
        difficulty=args.difficulty if args.difficulty else None,
    )
    if not cases:
        print("No cases found matching the given filters.")
        return

    # Header
    print(f"{'CASE_ID':<40} {'CAT':<20} {'DIFF':<10} {'BEHAVIOR':<18} {'SAFETY':<12} PROMPT")
    print("-" * 120)
    for c in cases:
        prompt_preview = c.prompt[:60] + "…" if len(c.prompt) > 60 else c.prompt
        print(
            f"{c.case_id:<40} {c.category:<20} {c.difficulty:<10} "
            f"{c.expected_behavior:<18} {c.safety_level:<12} {prompt_preview}"
        )

    print(f"\nTotal: {len(cases)} case(s)")

    # Print corpus summary by category
    if not args.category:
        print("\nCorpus summary by category:")
        for cat, count in summarize_corpus().items():
            print(f"  {cat:<25} {count} cases")


def _cmd_run(args: argparse.Namespace) -> None:
    """Run the benchmark for one or all models."""
    from benchmarks.runner import BenchmarkRunner

    db_path = args.db or str(DEFAULT_DB_PATH)
    ollama_url = args.ollama_url or None

    models_to_run: list[str]
    if args.all_models:
        models_to_run = [m["name"] for m in MODEL_MATRIX]
    elif args.model:
        models_to_run = [args.model]
    else:
        print("Error: specify --model MODEL or --all-models", file=sys.stderr)
        sys.exit(1)

    for model in models_to_run:
        runner = BenchmarkRunner(
            model_name=model,
            corpus_filter=args.category if args.category else None,
            resume=args.resume,
            db_path=db_path,
            ollama_url=ollama_url,
            no_context=args.no_context,
            timeout=args.timeout,
        )
        try:
            run_uuid = runner.run()
            print(f"Run complete: {run_uuid}")
        except KeyboardInterrupt:
            print(f"\nInterrupted. Partial results saved (run UUID: {runner.run_uuid})")
            break
        except Exception as exc:
            print(f"Error running {model}: {exc}", file=sys.stderr)
            if not args.all_models:
                sys.exit(1)


def _cmd_analyze(args: argparse.Namespace) -> None:
    """Print analysis summary tables."""
    from benchmarks import analysis

    db_path = args.db or str(DEFAULT_DB_PATH)
    conn = get_connection(db_path)

    model_name: str | None = args.model if args.model else None

    if args.compare_all:
        # Print all models in the accuracy table
        analysis.print_summary(conn)
    else:
        analysis.print_summary(conn, model_name=model_name)

    if model_name:
        failures = analysis.failure_patterns(conn, model_name, limit=args.failures)
        if failures:
            print(f"\n=== Failure Patterns: {model_name} (top {args.failures}) ===")
            for row in failures:
                print(f"\n  [{row['category']} / {row['difficulty']}] {row['case_id']}")
                print(f"  Prompt:    {row['prompt']}")
                print(f"  Expected:  {row['expected_command']}")
                print(f"  Got:       {row['final_command']}")
                if row["pipeline_error"]:
                    print(f"  Error:     {row['pipeline_error']}")


def _cmd_export(args: argparse.Namespace) -> None:
    """Export benchmark_results joined with benchmark_runs and test_cases to CSV."""
    db_path = args.db or str(DEFAULT_DB_PATH)
    output = Path(args.output)

    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT
            r.run_uuid,
            r.model_name,
            r.model_param_count,
            r.started_at,
            tc.case_id,
            tc.category,
            tc.difficulty,
            tc.expected_behavior,
            tc.safety_level,
            br.final_command,
            br.attempt_count,
            br.latency_ms_total,
            br.tokens_prompt_1,
            br.tokens_completion_1,
            br.match_exact,
            br.match_fuzzy,
            br.behavior_correct,
            br.safety_correct,
            br.is_soft_risky,
            br.pipeline_error
        FROM benchmark_results br
        JOIN benchmark_runs r  ON r.id  = br.run_id
        JOIN test_cases tc     ON tc.case_id = br.case_id
        ORDER BY r.started_at, tc.case_id
        """
    ).fetchall()

    if not rows:
        print("No results to export.")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        col_names = [
            "run_uuid", "model_name", "model_param_count", "started_at",
            "case_id", "category", "difficulty", "expected_behavior", "safety_level",
            "final_command", "attempt_count", "latency_ms_total",
            "tokens_prompt_1", "tokens_completion_1",
            "match_exact", "match_fuzzy", "behavior_correct", "safety_correct",
            "is_soft_risky", "pipeline_error",
        ]
        writer.writerow(col_names)
        for row in rows:
            writer.writerow(list(row))

    print(f"Exported {len(rows)} rows to {output}")


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="ReOS NL→shell pipeline benchmark framework",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── list-cases ────────────────────────────────────────────────────────────
    p_list = sub.add_parser("list-cases", help="List corpus test cases")
    p_list.add_argument("--category", metavar="CAT", help="Filter by category")
    p_list.add_argument("--difficulty", metavar="DIFF", help="Filter by difficulty")

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Run the benchmark")
    model_group = p_run.add_mutually_exclusive_group()
    model_group.add_argument("--model", metavar="MODEL", help="Ollama model name (e.g. qwen2.5:7b)")
    model_group.add_argument(
        "--all-models",
        action="store_true",
        default=False,
        help="Run all models in the model matrix",
    )
    p_run.add_argument("--category", metavar="CAT", help="Restrict to one corpus category")
    p_run.add_argument(
        "--resume", action="store_true", default=False, help="Skip already-done cases"
    )
    p_run.add_argument(
        "--no-context",
        action="store_true",
        default=False,
        help="Disable shell context gathering",
    )
    p_run.add_argument(
        "--timeout",
        type=int,
        default=120,
        metavar="SECS",
        help="Per-case timeout in seconds (default: 120)",
    )
    p_run.add_argument("--db", metavar="PATH", help="Path to benchmark database")
    p_run.add_argument("--ollama-url", metavar="URL", help="Ollama server URL")

    # ── analyze ───────────────────────────────────────────────────────────────
    p_ana = sub.add_parser("analyze", help="Print analysis tables")
    p_ana.add_argument("--model", metavar="MODEL", help="Focus on a specific model")
    p_ana.add_argument(
        "--compare-all",
        action="store_true",
        default=False,
        help="Show all models side-by-side",
    )
    p_ana.add_argument(
        "--failures",
        type=int,
        default=20,
        metavar="N",
        help="Number of failure patterns to show (default: 20)",
    )
    p_ana.add_argument("--db", metavar="PATH", help="Path to benchmark database")

    # ── export ────────────────────────────────────────────────────────────────
    p_exp = sub.add_parser("export", help="Export results to CSV")
    p_exp.add_argument("--output", required=True, metavar="FILE", help="Output CSV path")
    p_exp.add_argument("--db", metavar="PATH", help="Path to benchmark database")

    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "list-cases":
        _cmd_list_cases(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "export":
        _cmd_export(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
