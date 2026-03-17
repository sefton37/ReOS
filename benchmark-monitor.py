#!/usr/bin/env python3
"""Live monitor for the ReOS benchmark full run.

Usage:
    python benchmark-monitor.py          # one-shot summary
    python benchmark-monitor.py --watch  # refresh every 30s
"""

import sqlite3
import time
import sys
import os
from pathlib import Path
from datetime import timedelta

DB_PATH = Path.home() / ".talkingrock" / "reos_benchmark.db"

MODELS = [
    "qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "gemma2:2b",
    "qwen2.5:3b", "llama3.2:3b", "phi3:mini-128k",
    "qwen2.5:7b", "llama3.1:8b-instruct-q5_K_M", "mistral:latest",
    "codellama:7b", "gemma2:9b",
    "codellama:13b", "qwen2.5:14b", "phi3:medium-128k", "deepseek-coder-v2:16b",
]

MODES = ["reactive", "reactive_rag", "conversational", "conversational_rag"]
TOTAL_CASES = 415
TOTAL_CELLS = len(MODELS) * len(MODES) * TOTAL_CASES  # 26,560


def get_progress(conn):
    """Return dict of {(model, mode): (count, avg_ms, last_ts)}."""
    rows = conn.execute("""
        SELECT r.model_name, r.pipeline_mode,
               COUNT(br.id),
               ROUND(AVG(br.latency_ms_total), 0),
               MAX(br.executed_at)
        FROM benchmark_runs r
        JOIN benchmark_results br ON br.run_id = r.id
        GROUP BY r.model_name, r.pipeline_mode
    """).fetchall()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def get_recent_rate(conn, window_min=5):
    """Cases completed in the last N minutes → cases/min."""
    cutoff = int((time.time() - window_min * 60) * 1000)
    row = conn.execute("""
        SELECT COUNT(*) FROM benchmark_results WHERE executed_at > ?
    """, (cutoff,)).fetchone()
    count = row[0]
    if count == 0:
        return 0.0
    return count / window_min


def get_accuracy_snapshot(conn):
    """Quick accuracy by mode (across all models)."""
    rows = conn.execute("""
        SELECT r.pipeline_mode,
               COUNT(br.id),
               ROUND(100.0 * SUM(br.match_exact) / COUNT(br.id), 1),
               ROUND(100.0 * SUM(br.match_fuzzy) / COUNT(br.id), 1),
               ROUND(100.0 * SUM(br.safety_correct) / COUNT(br.id), 1),
               ROUND(100.0 * SUM(COALESCE(br.rag_retrieved, 0)) / COUNT(br.id), 1)
        FROM benchmark_runs r
        JOIN benchmark_results br ON br.run_id = r.id
        GROUP BY r.pipeline_mode
        ORDER BY r.pipeline_mode
    """).fetchall()
    return rows


def print_report(conn):
    progress = get_progress(conn)
    rate = get_recent_rate(conn)

    total_done = sum(c for c, _, _ in progress.values())
    total_remaining = TOTAL_CELLS - total_done
    pct = 100.0 * total_done / TOTAL_CELLS if TOTAL_CELLS else 0

    # ETA
    if rate > 0:
        eta_min = total_remaining / rate
        eta_str = str(timedelta(minutes=int(eta_min)))
    else:
        eta_str = "calculating..."

    # Header
    print("\033[2J\033[H", end="")  # clear screen
    print("=" * 80)
    print(f"  ReOS Benchmark Monitor")
    print(f"  {total_done:,} / {TOTAL_CELLS:,} cases  ({pct:.1f}%)  |  "
          f"Rate: {rate:.1f} cases/min  |  ETA: {eta_str}")
    print("=" * 80)

    # Per-model grid
    # Header row
    hdr = f"{'Model':<30}"
    for m in MODES:
        short = m.replace("conversational", "conv").replace("reactive", "react")
        hdr += f" {short:>10}"
    hdr += f" {'Total':>8}"
    print(f"\n{hdr}")
    print("-" * len(hdr))

    for model in MODELS:
        row = f"{model:<30}"
        model_total = 0
        for mode in MODES:
            key = (model, mode)
            if key in progress:
                count, avg_ms, _ = progress[key]
                model_total += count
                if count >= TOTAL_CASES:
                    row += f"  {'DONE':>8}"
                else:
                    row += f" {count:>4}/{TOTAL_CASES}"
            else:
                row += f" {'-':>10}"
        # Model completion
        model_pct = 100.0 * model_total / (TOTAL_CASES * 4)
        row += f" {model_pct:>6.0f}%"
        print(row)

    # Currently active (most recent result in last 2 min)
    cutoff = int((time.time() - 120) * 1000)
    active = conn.execute("""
        SELECT r.model_name, r.pipeline_mode, COUNT(*), MAX(br.executed_at)
        FROM benchmark_runs r
        JOIN benchmark_results br ON br.run_id = r.id
        WHERE br.executed_at > ?
        GROUP BY r.model_name, r.pipeline_mode
        ORDER BY MAX(br.executed_at) DESC
        LIMIT 1
    """, (cutoff,)).fetchone()

    print()
    if active:
        print(f"  Active: {active[0]} [{active[1]}] — {active[2]} cases in last 2min")
    else:
        print("  Active: (idle or finished)")

    # Accuracy snapshot
    acc = get_accuracy_snapshot(conn)
    if acc:
        print(f"\n{'Mode':<25} {'Cases':>7} {'Exact%':>7} {'Fuzzy%':>7} {'Safety%':>8} {'RAG%':>6}")
        print("-" * 62)
        for mode, cases, exact, fuzzy, safety, rag_pct in acc:
            short = mode.replace("conversational", "conv").replace("reactive", "react")
            print(f"{short:<25} {cases:>7} {exact:>7} {fuzzy:>7} {safety:>8} {rag_pct:>6}")

    # RAG delta (if both reactive and reactive_rag exist)
    rag_data = {r[0]: r for r in acc} if acc else {}
    if "reactive_rag" in rag_data and "reactive" in rag_data:
        r_rag = rag_data["reactive_rag"]
        r_no = rag_data["reactive"]
        delta_exact = r_rag[2] - r_no[2]
        delta_fuzzy = r_rag[3] - r_no[3]
        print(f"\n  RAG Lift (reactive): exact {delta_exact:+.1f}%, fuzzy {delta_fuzzy:+.1f}%")

    if "conversational_rag" in rag_data and "conversational" in rag_data:
        c_rag = rag_data["conversational_rag"]
        c_no = rag_data["conversational"]
        delta_exact = c_rag[2] - c_no[2]
        delta_fuzzy = c_rag[3] - c_no[3]
        print(f"  RAG Lift (conv):     exact {delta_exact:+.1f}%, fuzzy {delta_fuzzy:+.1f}%")

    print(f"\n  Last updated: {time.strftime('%H:%M:%S')}")


def main():
    if not DB_PATH.exists():
        print(f"No benchmark DB at {DB_PATH}")
        sys.exit(1)

    watch = "--watch" in sys.argv or "-w" in sys.argv

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    if watch:
        try:
            while True:
                # Reopen connection each cycle to see new data
                conn.close()
                conn = sqlite3.connect(str(DB_PATH))
                print_report(conn)
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print_report(conn)

    conn.close()


if __name__ == "__main__":
    main()
