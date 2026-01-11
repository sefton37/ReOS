#!/usr/bin/env python3
"""Simple direct test of metrics database persistence."""

import sqlite3
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode.optimization.metrics import MetricsStore, create_metrics


def test_metrics_store_save_and_load():
    """Test that metrics can be saved to and loaded from database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create database
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))

        # Create wrapper that provides both execute() and fetchall()
        class DBWrapper:
            def __init__(self, connection):
                self.conn = connection
                self.cursor = connection.cursor()

            def execute(self, sql, params=None):
                if params:
                    return self.cursor.execute(sql, params)
                return self.cursor.execute(sql)

            def fetchall(self, sql=None, params=None):
                if sql:
                    # Execute first, then fetchall
                    self.execute(sql, params)
                return self.cursor.fetchall()

        # Create store
        db = DBWrapper(conn)
        store = MetricsStore(db)

        # Create metrics
        metrics = create_metrics("test_session_123")
        metrics.set_llm_info(provider="anthropic", model="claude-sonnet-4")
        metrics.record_llm_call(purpose="action", duration_ms=500, tokens_in=100, tokens_out=50)
        metrics.record_verification(risk_level="medium")
        metrics.complete(success=True)

        # Save to database
        store.save(metrics)
        conn.commit()

        # Verify it was saved
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, llm_provider, llm_model, success, first_try_success, completed_at FROM riva_metrics WHERE session_id = ?",
            (metrics.session_id,),
        )
        row = cursor.fetchone()

        assert row is not None, "Metrics should be saved"
        assert row[0] == "test_session_123"
        assert row[1] == "anthropic", "LLM provider should be saved"
        assert row[2] == "claude-sonnet-4", "LLM model should be saved"
        assert row[3] == 1  # success = True
        assert row[4] == 1  # first_try_success = True (no retries)
        assert row[5] is not None  # completed_at is set

        # Test get_baseline_stats
        baseline = store.get_baseline_stats(limit=10)
        print(f"  Baseline stats: {baseline}")
        assert "total_sessions" in baseline or "error" not in baseline
        if "total_sessions" in baseline:
            assert baseline["total_sessions"] == 1
            assert baseline["success_count"] == 1

        conn.close()
        print(f"  Verified metrics saved to {db_path}")


if __name__ == "__main__":
    print("Running test_metrics_store_save_and_load...")
    try:
        test_metrics_store_save_and_load()
        print("✓ PASSED: test_metrics_store_save_and_load")
    except AssertionError as e:
        print(f"✗ FAILED: test_metrics_store_save_and_load - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ ERROR: test_metrics_store_save_and_load - {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n✅ Test passed - metrics persistence works!")
    sys.exit(0)
