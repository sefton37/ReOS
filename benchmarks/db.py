"""Database initialization and access helpers for the ReOS benchmark framework.

Creates and manages reos_benchmark.db (separate from production telemetry DB).
Uses WAL mode for safe concurrent reads during long benchmark runs.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".talkingrock" / "reos_benchmark.db"

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────────
-- benchmark_runs: one row per invocation of the runner
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid            TEXT    NOT NULL UNIQUE,   -- UUID4, identifies the run
    started_at          INTEGER NOT NULL,           -- epoch ms
    completed_at        INTEGER,                    -- epoch ms, NULL if interrupted
    model_name          TEXT    NOT NULL,           -- e.g. "qwen2.5:7b"
    model_family        TEXT,                       -- e.g. "qwen2.5"
    model_param_count   TEXT,                       -- e.g. "7b"
    ollama_url          TEXT    NOT NULL,
    temperature_1       REAL    NOT NULL DEFAULT 0.3,  -- attempt 1 temperature
    temperature_2       REAL    NOT NULL DEFAULT 0.1,  -- attempt 2 temperature
    corpus_version      TEXT,                       -- git hash or version tag of corpus.json
    host_info           TEXT,                       -- JSON: {hostname, cpu, ram_gb, gpu}
    notes               TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- test_cases: the corpus (loaded once, referenced by results)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS test_cases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             TEXT    NOT NULL UNIQUE,    -- stable slug, e.g. "files_ls_basic_001"
    prompt              TEXT    NOT NULL,           -- natural language input to the pipeline
    category            TEXT    NOT NULL,           -- linux domain (see taxonomy)
    subcategory         TEXT,                       -- more specific grouping
    difficulty          TEXT    NOT NULL CHECK (
        difficulty IN ('simple','moderate','complex','expert')
    ),
    expected_behavior   TEXT    NOT NULL CHECK (
        expected_behavior IN ('command','explanation_only','refuse','clarify')
    ),
    expected_command    TEXT,                       -- canonical command (NULL if N/A)
    expected_command_alts TEXT,                     -- JSON array of acceptable alternative commands
    safety_level        TEXT    NOT NULL CHECK (
        safety_level IN ('safe','soft_risky','hard_blocked')
    ),
    soft_risky_reason   TEXT,                       -- if soft_risky, which pattern triggers
    notes               TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- benchmark_results: one row per (run × test_case)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS benchmark_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER NOT NULL REFERENCES benchmark_runs(id),
    case_id                 TEXT    NOT NULL REFERENCES test_cases(case_id),
    executed_at             INTEGER NOT NULL,   -- epoch ms

    -- ── Pipeline outcome ─────────────────────────────────────────────────────
    final_command           TEXT,              -- extracted command (NULL if none)
    final_message           TEXT,              -- conversational response text
    attempt_count           INTEGER NOT NULL,  -- 1 or 2
    pipeline_error          TEXT,              -- exception message if pipeline raised

    -- ── Latency ──────────────────────────────────────────────────────────────
    latency_ms_total        INTEGER,           -- wall clock, attempt 1 start to end
    latency_ms_attempt1     INTEGER,
    latency_ms_attempt2     INTEGER,           -- NULL if no attempt 2

    -- ── Token counts ─────────────────────────────────────────────────────────
    tokens_prompt_1         INTEGER,           -- prompt_eval_count, attempt 1
    tokens_completion_1     INTEGER,           -- eval_count, attempt 1
    tokens_prompt_2         INTEGER,
    tokens_completion_2     INTEGER,

    -- ── Attempt 1: raw LLM output ────────────────────────────────────────────
    raw_response_1          TEXT,              -- verbatim LLM output
    sentinel_found_1        INTEGER,           -- bool: COMMAND: found in response
    command_before_safety_1 TEXT,              -- command extracted before safety check
    safety_passed_1         INTEGER,           -- bool
    safety_block_reason_1   TEXT,
    looks_like_cmd_1        INTEGER,           -- bool: looks_like_command() result

    -- ── Attempt 2: raw LLM output (if fired) ────────────────────────────────
    raw_response_2          TEXT,
    sentinel_found_2        INTEGER,
    command_before_safety_2 TEXT,
    safety_passed_2         INTEGER,
    safety_block_reason_2   TEXT,
    looks_like_cmd_2        INTEGER,

    -- ── Soft-risky detection ─────────────────────────────────────────────────
    is_soft_risky           INTEGER,           -- bool
    soft_risky_reason       TEXT,

    -- ── Context gathering ────────────────────────────────────────────────────
    context_can_verify      INTEGER,           -- bool: ShellContext.can_verify
    context_string          TEXT,              -- what was injected into the prompt

    -- ── Sanitization trace ───────────────────────────────────────────────────
    sanitize_markdown_block INTEGER,           -- stripped ``` wrapper
    sanitize_backtick       INTEGER,           -- stripped single backtick
    sanitize_prefix         INTEGER,           -- stripped "Command:" / "Run:" etc.
    sanitize_multiline      INTEGER,           -- extracted first-line command from multiline
    sanitize_meta_rejection INTEGER,           -- rejected "bash"/"shell"/empty meta-response

    -- ── Accuracy scoring ─────────────────────────────────────────────────────
    match_exact             INTEGER,           -- final_command == expected_command (normalized)
    match_fuzzy             INTEGER,           -- token overlap >= 0.8 (Jaccard on shell tokens)
    match_semantic          INTEGER,           -- cosine similarity >= 0.85 (sentence embeddings)
    behavior_correct        INTEGER,           -- NULL/present matches expected_behavior
    safety_correct          INTEGER,           -- safety handling matches expected safety_level

    UNIQUE (run_id, case_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_results_run    ON benchmark_results (run_id);
CREATE INDEX IF NOT EXISTS idx_results_case   ON benchmark_results (case_id);
CREATE INDEX IF NOT EXISTS idx_results_model  ON benchmark_results (run_id, case_id);
CREATE INDEX IF NOT EXISTS idx_cases_category ON test_cases (category, difficulty);
CREATE INDEX IF NOT EXISTS idx_cases_safety   ON test_cases (safety_level);
CREATE INDEX IF NOT EXISTS idx_runs_model     ON benchmark_runs (model_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- Views (pre-built analysis queries)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE VIEW IF NOT EXISTS v_model_accuracy AS
SELECT
    r.model_name,
    r.model_param_count,
    COUNT(br.id)                                                AS total_cases,
    ROUND(100.0 * SUM(br.match_exact)    / COUNT(br.id), 1)   AS exact_match_pct,
    ROUND(100.0 * SUM(br.match_fuzzy)    / COUNT(br.id), 1)   AS fuzzy_match_pct,
    ROUND(100.0 * SUM(br.behavior_correct) / COUNT(br.id), 1) AS behavior_correct_pct,
    ROUND(100.0 * SUM(br.safety_correct) / COUNT(br.id), 1)   AS safety_correct_pct,
    ROUND(100.0 * SUM(CASE WHEN br.attempt_count = 2 THEN 1 ELSE 0 END)
        / COUNT(br.id), 1)                                     AS retry_rate_pct,
    ROUND(AVG(br.latency_ms_total), 0)                         AS avg_latency_ms,
    ROUND(AVG(br.tokens_completion_1 + COALESCE(br.tokens_completion_2, 0)), 0)
                                                               AS avg_output_tokens
FROM benchmark_runs r
JOIN benchmark_results br ON br.run_id = r.id
GROUP BY r.model_name, r.model_param_count
ORDER BY exact_match_pct DESC;

CREATE VIEW IF NOT EXISTS v_category_accuracy AS
SELECT
    r.model_name,
    tc.category,
    tc.difficulty,
    COUNT(br.id)                                              AS total,
    ROUND(100.0 * SUM(br.match_exact) / COUNT(br.id), 1)    AS exact_pct,
    ROUND(100.0 * SUM(br.match_fuzzy) / COUNT(br.id), 1)    AS fuzzy_pct,
    ROUND(AVG(br.latency_ms_total), 0)                       AS avg_latency_ms
FROM benchmark_runs r
JOIN benchmark_results br ON br.run_id = r.id
JOIN test_cases tc         ON tc.case_id = br.case_id
GROUP BY r.model_name, tc.category, tc.difficulty
ORDER BY r.model_name, tc.category, tc.difficulty;

CREATE VIEW IF NOT EXISTS v_safety_detection AS
SELECT
    r.model_name,
    tc.safety_level,
    COUNT(br.id)                                                  AS total,
    ROUND(100.0 * SUM(br.safety_correct) / COUNT(br.id), 1)      AS correct_pct,
    SUM(CASE WHEN tc.safety_level = 'hard_blocked'
              AND br.final_command IS NOT NULL THEN 1 ELSE 0 END) AS hard_block_escapes,
    SUM(CASE WHEN tc.safety_level = 'safe'
              AND br.final_command IS NULL THEN 1 ELSE 0 END)     AS false_positives
FROM benchmark_runs r
JOIN benchmark_results br ON br.run_id = r.id
JOIN test_cases tc         ON tc.case_id = br.case_id
GROUP BY r.model_name, tc.safety_level
ORDER BY r.model_name, tc.safety_level;

CREATE VIEW IF NOT EXISTS v_sanitization_rates AS
SELECT
    r.model_name,
    COUNT(br.id)                                                        AS total,
    ROUND(100.0 * SUM(br.sanitize_markdown_block) / COUNT(br.id), 1)   AS markdown_block_pct,
    ROUND(100.0 * SUM(br.sanitize_backtick)        / COUNT(br.id), 1)  AS backtick_pct,
    ROUND(100.0 * SUM(br.sanitize_prefix)          / COUNT(br.id), 1)  AS prefix_strip_pct,
    ROUND(100.0 * SUM(br.sanitize_multiline)       / COUNT(br.id), 1)  AS multiline_pct,
    ROUND(100.0 * SUM(br.sanitize_meta_rejection)  / COUNT(br.id), 1)  AS meta_rejection_pct,
    ROUND(100.0 * SUM(
        CASE WHEN br.sanitize_markdown_block = 1
              OR br.sanitize_backtick = 1
              OR br.sanitize_prefix = 1
              OR br.sanitize_multiline = 1 THEN 1 ELSE 0 END
    ) / COUNT(br.id), 1)                                               AS any_sanitization_pct
FROM benchmark_runs r
JOIN benchmark_results br ON br.run_id = r.id
GROUP BY r.model_name
ORDER BY any_sanitization_pct DESC;

CREATE VIEW IF NOT EXISTS v_failure_patterns AS
SELECT
    r.model_name,
    tc.category,
    tc.difficulty,
    br.case_id,
    tc.prompt,
    tc.expected_command,
    br.final_command,
    br.raw_response_1,
    br.pipeline_error
FROM benchmark_runs r
JOIN benchmark_results br ON br.run_id = r.id
JOIN test_cases tc         ON tc.case_id = br.case_id
WHERE br.match_exact = 0
  AND tc.expected_behavior = 'command'
ORDER BY r.model_name, tc.difficulty DESC, tc.category;
"""


def get_connection(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and foreign keys enabled.

    Args:
        path: Path to the benchmark database file.

    Returns:
        Open sqlite3.Connection with WAL mode active.
    """
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create the benchmark database schema if it does not already exist.

    Idempotent — safe to call on an existing database (all DDL uses IF NOT EXISTS).

    Args:
        path: Path where the database file should be created.

    Returns:
        Open sqlite3.Connection to the initialized database.
    """
    conn = get_connection(path)
    # Execute each statement individually to avoid issues with multi-statement execute
    for statement in _DDL.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions for inserting rows
# ─────────────────────────────────────────────────────────────────────────────


def insert_run(
    conn: sqlite3.Connection,
    *,
    run_uuid: str,
    started_at: int,
    model_name: str,
    ollama_url: str,
    model_family: str | None = None,
    model_param_count: str | None = None,
    temperature_1: float = 0.3,
    temperature_2: float = 0.1,
    corpus_version: str | None = None,
    host_info: str | None = None,
    notes: str | None = None,
) -> int:
    """Insert a new benchmark_runs row and return the assigned id.

    Args:
        conn: Active database connection.
        run_uuid: UUID4 string identifying this run.
        started_at: Epoch milliseconds when the run started.
        model_name: Ollama model name (e.g. "qwen2.5:7b").
        ollama_url: Base URL of the Ollama instance.
        model_family: Extracted family (e.g. "qwen2.5").
        model_param_count: Extracted param count (e.g. "7b").
        temperature_1: LLM temperature for attempt 1.
        temperature_2: LLM temperature for attempt 2.
        corpus_version: Git hash or tag for corpus.json.
        host_info: JSON string with host hardware info.
        notes: Optional free-text notes for this run.

    Returns:
        The auto-assigned integer id of the inserted row.
    """
    cur = conn.execute(
        """
        INSERT INTO benchmark_runs
            (run_uuid, started_at, model_name, model_family, model_param_count,
             ollama_url, temperature_1, temperature_2, corpus_version, host_info, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uuid,
            started_at,
            model_name,
            model_family,
            model_param_count,
            ollama_url,
            temperature_1,
            temperature_2,
            corpus_version,
            host_info,
            notes,
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def insert_test_case(conn: sqlite3.Connection, case: "TestCase") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Upsert a TestCase into the test_cases table.

    Uses INSERT OR IGNORE to skip cases that already exist with the same case_id.

    Args:
        conn: Active database connection.
        case: TestCase dataclass to persist.
    """
    import json as _json

    conn.execute(
        """
        INSERT OR IGNORE INTO test_cases
            (case_id, prompt, category, subcategory, difficulty, expected_behavior,
             expected_command, expected_command_alts, safety_level, soft_risky_reason, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case.case_id,
            case.prompt,
            case.category,
            case.subcategory,
            case.difficulty,
            case.expected_behavior,
            case.expected_command,
            _json.dumps(case.expected_command_alts) if case.expected_command_alts else None,
            case.safety_level,
            case.soft_risky_reason,
            case.notes,
        ),
    )
    conn.commit()


def insert_result(conn: sqlite3.Connection, *, run_id: int, **fields) -> int:
    """Insert a benchmark_results row from keyword arguments.

    Only the required fields (run_id, case_id, executed_at, attempt_count) must
    be provided; all other columns default to NULL.

    Args:
        conn: Active database connection.
        run_id: FK to benchmark_runs.id.
        **fields: Any additional benchmark_results column values.

    Returns:
        The auto-assigned integer id of the inserted row.
    """
    fields["run_id"] = run_id
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO benchmark_results ({columns}) VALUES ({placeholders})",
        list(fields.values()),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def finalize_run(conn: sqlite3.Connection, run_id: int, completed_at: int) -> None:
    """Set the completed_at timestamp on a benchmark_runs row.

    Args:
        conn: Active database connection.
        run_id: The run to finalize.
        completed_at: Epoch milliseconds when the run finished.
    """
    conn.execute(
        "UPDATE benchmark_runs SET completed_at = ? WHERE id = ?",
        (completed_at, run_id),
    )
    conn.commit()
