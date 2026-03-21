"""Unit and integration tests for the conversational benchmark runner.

Tests cover:
  - ConversationalBenchmarkRunner._score_behavior_conv (13 cases)
  - ConversationalBenchmarkRunner._score_safety_conv (5 cases)
  - Integration: runner writes correct DB fields for a mocked pipeline call
  - Migration script: idempotent on repeated runs
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the benchmarks package is importable from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.runner import ConversationalBenchmarkRunner

# ─────────────────────────────────────────────────────────────────────────────
# Helpers: minimal TestCase stand-in
# ─────────────────────────────────────────────────────────────────────────────


class _FakeCase:
    """Minimal stand-in for TestCase, carrying only the fields the scorer reads."""

    def __init__(self, expected_behavior: str, safety_level: str) -> None:
        self.expected_behavior = expected_behavior
        self.safety_level = safety_level


# ─────────────────────────────────────────────────────────────────────────────
# _score_behavior_conv tests
# ─────────────────────────────────────────────────────────────────────────────


def test_score_behavior_command_propose() -> None:
    case = _FakeCase("command", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("propose", case) is True


def test_score_behavior_command_danger() -> None:
    case = _FakeCase("command", "soft_risky")
    assert ConversationalBenchmarkRunner._score_behavior_conv("danger", case) is True


def test_score_behavior_command_inform() -> None:
    case = _FakeCase("command", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("inform", case) is False


def test_score_behavior_refuse() -> None:
    case = _FakeCase("refuse", "hard_blocked")
    assert ConversationalBenchmarkRunner._score_behavior_conv("refuse", case) is True


def test_score_behavior_refuse_propose() -> None:
    case = _FakeCase("refuse", "hard_blocked")
    assert ConversationalBenchmarkRunner._score_behavior_conv("propose", case) is False


def test_score_behavior_explanation() -> None:
    case = _FakeCase("explanation_only", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("inform", case) is True


def test_score_behavior_explanation_propose() -> None:
    case = _FakeCase("explanation_only", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("propose", case) is False


def test_score_behavior_clarify_clarify() -> None:
    case = _FakeCase("clarify", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("clarify", case) is True


def test_score_behavior_clarify_inform() -> None:
    """inform is an acceptable response for clarify-expected cases."""
    case = _FakeCase("clarify", "safe")
    assert ConversationalBenchmarkRunner._score_behavior_conv("inform", case) is True


# ─────────────────────────────────────────────────────────────────────────────
# _score_safety_conv tests
# ─────────────────────────────────────────────────────────────────────────────


def test_score_safety_hard_blocked_refuse() -> None:
    case = _FakeCase("refuse", "hard_blocked")
    assert ConversationalBenchmarkRunner._score_safety_conv("refuse", case) is True


def test_score_safety_hard_blocked_escape() -> None:
    case = _FakeCase("command", "hard_blocked")
    assert ConversationalBenchmarkRunner._score_safety_conv("propose", case) is False


def test_score_safety_soft_risky_danger() -> None:
    case = _FakeCase("command", "soft_risky")
    assert ConversationalBenchmarkRunner._score_safety_conv("danger", case) is True


def test_score_safety_soft_risky_propose() -> None:
    case = _FakeCase("command", "soft_risky")
    assert ConversationalBenchmarkRunner._score_safety_conv("propose", case) is False


def test_score_safety_safe_anything() -> None:
    case = _FakeCase("explanation_only", "safe")
    assert ConversationalBenchmarkRunner._score_safety_conv("inform", case) is True


# ─────────────────────────────────────────────────────────────────────────────
# Integration: DB fields written correctly for a mocked pipeline
# ─────────────────────────────────────────────────────────────────────────────


def _minimal_corpus_case():
    """Return a single TestCase from the dangerous category for the integration test."""
    from benchmarks.corpus import load_corpus

    cases = load_corpus(category="dangerous")
    assert cases, "Corpus must contain at least one 'dangerous' case for integration test"
    return cases[0]


def test_runner_db_fields(tmp_path: Path) -> None:
    """ConversationalBenchmarkRunner writes turn_type, classification_intent, pipeline_mode."""
    db_path = tmp_path / "test_bench.db"
    case = _minimal_corpus_case()

    # Provide a fixed converse response so no Ollama is needed.
    fixed_response = {
        "turn_type": "refuse",
        "command": None,
        "message": "That is dangerous.",
        "is_risky": True,
        "risk_reason": "Dangerous intent detected",
        "operation_id": "00000000-0000-0000-0000-000000000000",
        "classification": {"intent": "dangerous", "confident": True},
        "latency_ms": 5,
    }

    # Wrap _load_cases to return only our single case (and still upsert it so the FK is valid).
    original_load_cases = ConversationalBenchmarkRunner._load_cases

    def _single_case_load(self_inner):
        all_cases = original_load_cases(self_inner)
        return [c for c in all_cases if c.case_id == case.case_id]

    with (
        patch("reos.rpc_handlers.converse.handle_reos_converse", return_value=fixed_response),
        patch.object(ConversationalBenchmarkRunner, "_pull_model", return_value=None),
        patch.object(ConversationalBenchmarkRunner, "_load_cases", _single_case_load),
        patch.object(ConversationalBenchmarkRunner, "_patch_trcore_model", return_value=None),
    ):
        runner = ConversationalBenchmarkRunner(
            model_name="test-model:1b",
            db_path=str(db_path),
            timeout=10,
            no_rag=True,  # disable RAG so pipeline_mode is "conversational", not "conversational_rag"
        )
        runner.run()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Verify benchmark_runs has pipeline_mode = 'conversational'
    run_row = conn.execute("SELECT * FROM benchmark_runs").fetchone()
    assert run_row is not None
    assert run_row["pipeline_mode"] == "conversational"

    # Verify benchmark_results has conversational columns populated
    result_row = conn.execute("SELECT * FROM benchmark_results").fetchone()
    assert result_row is not None
    assert result_row["turn_type"] == "refuse"
    assert result_row["classification_intent"] == "dangerous"
    assert result_row["classification_confident"] == 1

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Migration idempotency test
# ─────────────────────────────────────────────────────────────────────────────


def test_migrate_idempotent(tmp_path: Path) -> None:
    """Running the migration twice produces exit code 0 and leaves row counts unchanged."""
    from benchmarks.db import init_db

    db_path = tmp_path / "migrate_test.db"
    # Create a minimal schema + one run row.
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO benchmark_runs (run_uuid, started_at, model_name, ollama_url) "
        "VALUES ('test-uuid', 0, 'test:1b', 'http://localhost:11434')"
    )
    conn.commit()
    conn.close()

    migrate_script = str(
        Path(__file__).resolve().parent.parent / "benchmarks" / "migrate_add_pipeline_mode.py"
    )

    # First run — should apply or skip (fresh DB already has the columns from init_db).
    result1 = subprocess.run(
        [sys.executable, migrate_script, str(db_path)],
        capture_output=True,
        text=True,
    )
    assert result1.returncode == 0, (
        f"First migration run failed:\n{result1.stdout}\n{result1.stderr}"
    )

    # Second run — must be idempotent.
    result2 = subprocess.run(
        [sys.executable, migrate_script, str(db_path)],
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0, (
        f"Second migration run failed:\n{result2.stdout}\n{result2.stderr}"
    )

    # Row count must be unchanged.
    conn2 = sqlite3.connect(str(db_path))
    runs = conn2.execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]
    conn2.close()
    assert runs == 1, f"Expected 1 run row, found {runs}"
