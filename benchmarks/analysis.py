"""Analysis functions for the ReOS benchmark database.

Provides named SQL query wrappers and a human-readable summary printer.
All functions accept an open sqlite3.Connection returned by db.get_connection()
or db.init_db().

Usage:
    from benchmarks.db import get_connection
    from benchmarks import analysis

    conn = get_connection()
    analysis.print_summary(conn, model_name="qwen2.5:7b")
"""

from __future__ import annotations

import sqlite3

# ─────────────────────────────────────────────────────────────────────────────
# Named query wrappers
# ─────────────────────────────────────────────────────────────────────────────


def model_accuracy_summary(conn: sqlite3.Connection) -> list[dict]:
    """Return per-model accuracy metrics from v_model_accuracy.

    Args:
        conn: Open benchmark database connection.

    Returns:
        List of dicts with keys: model_name, model_param_count, total_cases,
        exact_match_pct, fuzzy_match_pct, behavior_correct_pct,
        safety_correct_pct, retry_rate_pct, avg_latency_ms, avg_output_tokens.
    """
    rows = conn.execute("SELECT * FROM v_model_accuracy").fetchall()
    return [dict(row) for row in rows]


def category_accuracy(conn: sqlite3.Connection, model_name: str) -> list[dict]:
    """Return per-category accuracy for a specific model from v_category_accuracy.

    Args:
        conn: Open benchmark database connection.
        model_name: Ollama model name to filter by (e.g. "qwen2.5:7b").

    Returns:
        List of dicts with keys: model_name, category, difficulty, total,
        exact_pct, fuzzy_pct, avg_latency_ms.
    """
    rows = conn.execute(
        "SELECT * FROM v_category_accuracy WHERE model_name = ?",
        (model_name,),
    ).fetchall()
    return [dict(row) for row in rows]


def safety_report(conn: sqlite3.Connection) -> list[dict]:
    """Return safety detection rates from v_safety_detection.

    Args:
        conn: Open benchmark database connection.

    Returns:
        List of dicts with keys: model_name, safety_level, total, correct_pct,
        hard_block_escapes, false_positives.
    """
    rows = conn.execute("SELECT * FROM v_safety_detection").fetchall()
    return [dict(row) for row in rows]


def sanitization_report(conn: sqlite3.Connection) -> list[dict]:
    """Return sanitization transform rates from v_sanitization_rates.

    Args:
        conn: Open benchmark database connection.

    Returns:
        List of dicts with keys: model_name, total, markdown_block_pct,
        backtick_pct, prefix_strip_pct, multiline_pct, meta_rejection_pct,
        any_sanitization_pct.
    """
    rows = conn.execute("SELECT * FROM v_sanitization_rates").fetchall()
    return [dict(row) for row in rows]


def failure_patterns(
    conn: sqlite3.Connection,
    model_name: str,
    limit: int = 20,
) -> list[dict]:
    """Return failure pattern rows for a specific model from v_failure_patterns.

    Args:
        conn: Open benchmark database connection.
        model_name: Ollama model name to filter by.
        limit: Maximum number of rows to return.

    Returns:
        List of dicts with keys: model_name, category, difficulty, case_id,
        prompt, expected_command, final_command, raw_response_1, pipeline_error.
    """
    rows = conn.execute(
        "SELECT * FROM v_failure_patterns WHERE model_name = ? LIMIT ?",
        (model_name, limit),
    ).fetchall()
    return [dict(row) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Human-readable summary printer
# ─────────────────────────────────────────────────────────────────────────────


def _table(headers: list[str], rows: list[list[str]], col_widths: list[int] | None = None) -> None:
    """Print a simple fixed-width ASCII table to stdout.

    Args:
        headers: Column header strings.
        rows: List of row value lists (all already converted to str).
        col_widths: Optional explicit column widths.  If None, auto-computed.
    """
    if col_widths is None:
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(cell)))
    else:
        widths = col_widths

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    fmt = "|" + "|".join(f" {{:<{w}}} " for w in widths) + "|"

    print(sep)
    print(fmt.format(*[h[:widths[i]] for i, h in enumerate(headers)]))
    print(sep)
    for row in rows:
        padded = [str(v)[:widths[i]] if i < len(widths) else str(v) for i, v in enumerate(row)]
        print(fmt.format(*padded))
    print(sep)


def print_summary(
    conn: sqlite3.Connection,
    model_name: str | None = None,
) -> None:
    """Print a human-readable benchmark summary to stdout.

    Prints four sections: model accuracy, safety detection, sanitization rates,
    and (if model_name is given) category accuracy for that model.

    Args:
        conn: Open benchmark database connection.
        model_name: If provided, also print category breakdown for that model.
    """
    # ── Model accuracy ────────────────────────────────────────────────────────
    summary = model_accuracy_summary(conn)
    if not summary:
        print("No benchmark results found in database.")
        return

    print("\n=== Model Accuracy Summary ===")
    headers = [
        "Model", "Params", "Cases", "Exact%", "Fuzzy%", "Behavior%", "Safety%", "Retry%", "Avg ms",
    ]
    rows = [
        [
            r["model_name"],
            r["model_param_count"] or "—",
            str(r["total_cases"]),
            f"{r['exact_match_pct'] or 0:.1f}",
            f"{r['fuzzy_match_pct'] or 0:.1f}",
            f"{r['behavior_correct_pct'] or 0:.1f}",
            f"{r['safety_correct_pct'] or 0:.1f}",
            f"{r['retry_rate_pct'] or 0:.1f}",
            str(int(r["avg_latency_ms"] or 0)),
        ]
        for r in summary
    ]
    _table(headers, rows)

    # ── Safety detection ──────────────────────────────────────────────────────
    safety = safety_report(conn)
    if safety:
        print("\n=== Safety Detection ===")
        headers = ["Model", "Safety Level", "Total", "Correct%", "Hard Escapes", "False Pos"]
        rows = [
            [
                r["model_name"],
                r["safety_level"],
                str(r["total"]),
                f"{r['correct_pct'] or 0:.1f}",
                str(r["hard_block_escapes"] or 0),
                str(r["false_positives"] or 0),
            ]
            for r in safety
        ]
        _table(headers, rows)

    # ── Sanitization rates ────────────────────────────────────────────────────
    sanit = sanitization_report(conn)
    if sanit:
        print("\n=== Sanitization Rates ===")
        headers = [
            "Model", "Cases", "Markdown%", "Backtick%", "Prefix%", "Multiline%", "Meta%", "Any%",
        ]
        rows = [
            [
                r["model_name"],
                str(r["total"]),
                f"{r['markdown_block_pct'] or 0:.1f}",
                f"{r['backtick_pct'] or 0:.1f}",
                f"{r['prefix_strip_pct'] or 0:.1f}",
                f"{r['multiline_pct'] or 0:.1f}",
                f"{r['meta_rejection_pct'] or 0:.1f}",
                f"{r['any_sanitization_pct'] or 0:.1f}",
            ]
            for r in sanit
        ]
        _table(headers, rows)

    # ── Category breakdown (per model if requested) ───────────────────────────
    if model_name:
        cats = category_accuracy(conn, model_name)
        if cats:
            print(f"\n=== Category Accuracy: {model_name} ===")
            headers = ["Category", "Difficulty", "Total", "Exact%", "Fuzzy%", "Avg ms"]
            rows = [
                [
                    r["category"],
                    r["difficulty"],
                    str(r["total"]),
                    f"{r['exact_pct'] or 0:.1f}",
                    f"{r['fuzzy_pct'] or 0:.1f}",
                    str(int(r["avg_latency_ms"] or 0)),
                ]
                for r in cats
            ]
            _table(headers, rows)

    print()
