"""One-time idempotent migration: add pipeline_mode and conversational columns.

Adds four columns to the live reos_benchmark.db:
    benchmark_runs.pipeline_mode          TEXT NOT NULL DEFAULT 'reactive'
    benchmark_results.turn_type           TEXT
    benchmark_results.classification_intent   TEXT
    benchmark_results.classification_confident INTEGER

All changes use ALTER TABLE ... ADD COLUMN, which is the safest possible SQLite
schema change — it never rewrites existing rows.  Existing data is never touched.

The script is idempotent: it checks PRAGMA table_info before each ALTER and
skips any column that already exists.

Usage:
    python benchmarks/migrate_add_pipeline_mode.py [DB_PATH]

    DB_PATH defaults to ~/.talkingrock/reos_benchmark.db
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

# Import DEFAULT_DB_PATH from db.py so we share a single source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchmarks.db import DEFAULT_DB_PATH  # noqa: E402


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists in *table*."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _maybe_alter(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_def: str,
) -> None:
    """Run ALTER TABLE ... ADD COLUMN unless the column already exists.

    Args:
        conn: Open connection to the benchmark DB.
        table: Table name to modify.
        column: Column name to add.
        column_def: Full column definition string, e.g. "TEXT NOT NULL DEFAULT 'reactive'".
    """
    if _column_exists(conn, table, column):
        print(f"  SKIP   {table}.{column} (already exists)")
    else:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
        conn.commit()
        print(f"  ADDED  {table}.{column}")


def main(db_path: Path) -> None:
    """Run the migration against *db_path*.

    Args:
        db_path: Path to the benchmark database file.
    """
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # Create a backup before making any changes.
    backup_path = Path(str(db_path) + ".pre-pipeline-mode-backup")
    if backup_path.exists():
        print(f"Backup already exists: {backup_path} (skipping re-backup)")
    else:
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    print("\nApplying migrations …")
    _maybe_alter(
        conn,
        "benchmark_runs",
        "pipeline_mode",
        "TEXT NOT NULL DEFAULT 'reactive'",
    )
    _maybe_alter(conn, "benchmark_results", "turn_type", "TEXT")
    _maybe_alter(conn, "benchmark_results", "classification_intent", "TEXT")
    _maybe_alter(conn, "benchmark_results", "classification_confident", "INTEGER")

    # Verify row counts are intact.
    runs_count = conn.execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]
    results_count = conn.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0]
    print("\nRow counts after migration:")
    print(f"  benchmark_runs    : {runs_count}")
    print(f"  benchmark_results : {results_count}")

    # Confirm pipeline_mode values.
    mode_counts = conn.execute(
        "SELECT pipeline_mode, COUNT(*) FROM benchmark_runs GROUP BY pipeline_mode"
    ).fetchall()
    print("\npipeline_mode distribution in benchmark_runs:")
    for mode, count in mode_counts:
        print(f"  {mode!r:20s}: {count} run(s)")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    main(path)
