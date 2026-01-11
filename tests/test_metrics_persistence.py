#!/usr/bin/env python3
"""Test that metrics are persisted to database after RIVA sessions."""

import sqlite3
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode import (
    Action,
    ActionType,
    AutoCheckpoint,
    CodeSandbox,
    Intention,
    WorkContext,
    riva_work,
)
from reos.code_mode.optimization.metrics import MetricsStore, create_metrics


def test_metrics_persisted_after_riva_work():
    """Test that metrics are automatically persisted to database."""
    import os

    # Create temporary sandbox and database
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox_dir = Path(tmpdir) / "sandbox"
        sandbox_dir.mkdir()

        # Set up data directory via environment variable
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir()

        # Save old REOS_ROOT and set temporary one
        old_root = os.environ.get("REOS_ROOT")
        os.environ["REOS_ROOT"] = tmpdir

        try:
            # Import settings AFTER setting environment
            from reos.settings import Settings
            temp_settings = Settings()
            temp_settings.data_dir.mkdir(parents=True, exist_ok=True)

            # Create sandbox and context
            sandbox = CodeSandbox(sandbox_dir)
            checkpoint = AutoCheckpoint(sandbox=sandbox)
            metrics = create_metrics("test_persistence")

            ctx = WorkContext(
                sandbox=sandbox,
                llm=None,
                checkpoint=checkpoint,
                metrics=metrics,
                enable_multilayer_verification=False,  # Keep simple
            )

            # Create simple intention
            intention = Intention.create(
                what="Create a simple test file",
                acceptance="File exists with content",
            )

            # Run RIVA (will complete metrics and persist to DB)
            try:
                riva_work(intention, ctx)
            except Exception as e:
                print(f"  (RIVA work failed as expected: {e})")
                pass  # May fail, but should still persist metrics

            # Check that database was created
            db_path = temp_settings.data_dir / "riva.db"
            assert db_path.exists(), f"Database should be created at {db_path}"

            # Verify metrics were saved
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Check table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='riva_metrics'"
            )
            assert cursor.fetchone() is not None, "riva_metrics table should exist"

            # Check our session was saved
            cursor.execute(
                "SELECT session_id, success, completed_at FROM riva_metrics WHERE session_id = ?",
                (metrics.session_id,),
            )
            row = cursor.fetchone()
            assert row is not None, "Metrics should be saved to database"

            session_id, success, completed_at = row
            assert session_id == metrics.session_id
            assert completed_at is not None, "completed_at should be set"

            # Check metrics_json contains full data
            cursor.execute(
                "SELECT metrics_json FROM riva_metrics WHERE session_id = ?",
                (metrics.session_id,),
            )
            metrics_json = cursor.fetchone()[0]
            assert metrics_json is not None
            assert len(metrics_json) > 100, "Metrics JSON should contain substantial data"

            # Verify MetricsStore can read it back
            store = MetricsStore(conn)
            baseline = store.get_baseline_stats(limit=10)
            assert baseline["total_sessions"] >= 1

            conn.close()
        finally:
            # Restore old environment
            if old_root is not None:
                os.environ["REOS_ROOT"] = old_root
            elif "REOS_ROOT" in os.environ:
                del os.environ["REOS_ROOT"]


def test_metrics_persistence_failure_does_not_crash():
    """Test that RIVA continues even if metrics persistence fails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox_dir = Path(tmpdir) / "sandbox"
        sandbox_dir.mkdir()

        # Create a read-only data directory to force persistence failure
        import os
        from unittest.mock import patch

        data_dir = Path(tmpdir) / "readonly_data"
        data_dir.mkdir()
        os.chmod(data_dir, 0o444)  # Read-only

        with patch("reos.code_mode.intention.settings") as mock_settings:
            mock_settings.data_dir = data_dir

            sandbox = CodeSandbox(sandbox_dir)
            checkpoint = AutoCheckpoint(sandbox=sandbox)
            metrics = create_metrics("test_failure_resilience")

            ctx = WorkContext(
                sandbox=sandbox,
                llm=None,
                checkpoint=checkpoint,
                metrics=metrics,
                enable_multilayer_verification=False,
            )

            intention = Intention.create(
                what="Create test file",
                acceptance="File exists",
            )

            # This should NOT raise an exception even though persistence will fail
            try:
                riva_work(intention, ctx)
            except PermissionError:
                raise AssertionError("RIVA should not crash if metrics persistence fails")
            except Exception:
                pass  # Other exceptions are OK (e.g., from the work itself)

            # Clean up
            os.chmod(data_dir, 0o755)


if __name__ == "__main__":
    print("Running test_metrics_persisted_after_riva_work...")
    try:
        test_metrics_persisted_after_riva_work()
        print("✓ PASSED: test_metrics_persisted_after_riva_work")
    except AssertionError as e:
        print(f"✗ FAILED: test_metrics_persisted_after_riva_work - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ ERROR: test_metrics_persisted_after_riva_work - {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nRunning test_metrics_persistence_failure_does_not_crash...")
    try:
        test_metrics_persistence_failure_does_not_crash()
        print("✓ PASSED: test_metrics_persistence_failure_does_not_crash")
    except AssertionError as e:
        print(f"✗ FAILED: test_metrics_persistence_failure_does_not_crash - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ ERROR: test_metrics_persistence_failure_does_not_crash - {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n✅ All tests passed!")
    sys.exit(0)
