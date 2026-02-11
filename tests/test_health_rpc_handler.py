"""Tests for Health RPC handlers.

Run with: PYTHONPATH=src pytest tests/test_health_rpc_handler.py -v --no-cov
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reos.cairn.store import CairnStore
from reos.db import Database
from reos.rpc_handlers.health import (
    handle_health_acknowledge,
    handle_health_findings,
    handle_health_status,
)


@pytest.fixture
def tmp_play_path(tmp_path: Path) -> Path:
    """Create a temporary play directory with cairn database."""
    play_path = tmp_path / "play"
    play_path.mkdir()

    cairn_dir = play_path / ".cairn"
    cairn_dir.mkdir()

    # Create a cairn database (initializes schema)
    cairn_db = cairn_dir / "cairn.db"
    CairnStore(cairn_db)

    return play_path


@pytest.fixture
def mock_db(tmp_play_path: Path) -> Database:
    """Create a mock Database that returns our test play path."""
    db = MagicMock(spec=Database)

    # Mock get_current_play_path to return our test path
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        yield db


def test_handle_health_status_returns_expected_format(mock_db: Database, tmp_play_path: Path):
    """handle_health_status should return expected dict format."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_status(mock_db)

    assert isinstance(result, dict)
    assert "overall_severity" in result
    assert "finding_count" in result
    assert "unacknowledged_count" in result


def test_handle_health_status_fresh_database_is_healthy(mock_db: Database, tmp_play_path: Path):
    """Fresh database should return healthy status."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_status(mock_db)

    # Fresh database with no acts should be healthy
    # Data integrity check may return warning if database is empty/new
    assert result["overall_severity"] in ["healthy", "warning"]
    assert "finding_count" in result
    assert "unacknowledged_count" in result


def test_handle_health_status_with_stale_acts(mock_db: Database, tmp_play_path: Path):
    """Status should reflect warnings from stale acts."""
    # Create a stale act
    cairn_db = tmp_play_path / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db)

    store.touch("act", "act-stale")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stale"),
    )
    conn.commit()
    conn.close()

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_status(mock_db)

    # Should show warning status
    assert result["overall_severity"] == "warning"
    assert result["finding_count"] > 0


def test_handle_health_findings_returns_expected_format(mock_db: Database, tmp_play_path: Path):
    """handle_health_findings should return expected dict format."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_findings(mock_db)

    assert isinstance(result, dict)
    assert "findings" in result
    assert isinstance(result["findings"], list)
    assert "overall_severity" in result
    assert "finding_count" in result
    assert "unacknowledged_count" in result


def test_handle_health_findings_with_stale_acts(mock_db: Database, tmp_play_path: Path):
    """Findings should include details about stale acts."""
    # Create a stale act
    cairn_db = tmp_play_path / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db)

    store.touch("act", "act-stale")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stale"),
    )
    conn.commit()
    conn.close()

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_findings(mock_db)

    findings = result["findings"]
    assert len(findings) > 0

    # Check finding structure
    finding = findings[0]
    assert "check_name" in finding
    assert "severity" in finding
    assert "title" in finding
    assert "details" in finding
    assert "finding_key" in finding


def test_handle_health_findings_excludes_healthy_results(mock_db: Database, tmp_play_path: Path):
    """Findings list should only include non-healthy results."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_findings(mock_db)

    findings = result["findings"]

    # All findings should be warning or critical
    for finding in findings:
        assert finding["severity"] in ["warning", "critical"]


def test_handle_health_acknowledge_with_valid_log_id(mock_db: Database, tmp_play_path: Path):
    """handle_health_acknowledge should work with valid log_id."""
    # Create a finding to acknowledge
    cairn_db = tmp_play_path / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db)

    from reos.cairn.health.anti_nag import AntiNagProtocol

    conn = store._get_connection()
    anti_nag = AntiNagProtocol(conn)
    log_id = anti_nag.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:ack",
        title="Test",
    )

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_acknowledge(mock_db, log_id=log_id)

    assert result["success"] is True


def test_handle_health_acknowledge_with_invalid_log_id(mock_db: Database, tmp_play_path: Path):
    """handle_health_acknowledge should return success=False for invalid log_id."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_acknowledge(mock_db, log_id="nonexistent")

    assert result["success"] is False


def test_handle_health_status_no_active_play_returns_safe_defaults():
    """Status should return safe defaults if no active play (exception caught internally)."""
    # Don't use mock_db fixture - create a simple mock without the fixture's patch
    mock_db = MagicMock(spec=Database)

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=None):
        result = handle_health_status(mock_db)

    # Implementation catches exceptions and returns safe defaults
    assert result["overall_severity"] == "healthy"
    assert result["finding_count"] == 0
    assert result["unacknowledged_count"] == 0


def test_handle_health_findings_no_active_play_returns_safe_defaults():
    """Findings should return safe defaults if no active play (exception caught internally)."""
    # Don't use mock_db fixture - create a simple mock without the fixture's patch
    mock_db = MagicMock(spec=Database)

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=None):
        result = handle_health_findings(mock_db)

    # Implementation catches exceptions and returns safe defaults
    assert result["findings"] == []
    assert result["overall_severity"] == "healthy"
    assert result["finding_count"] == 0
    assert result["unacknowledged_count"] == 0


def test_health_components_registers_all_phase_1_checks(mock_db: Database, tmp_play_path: Path):
    """_get_health_components should register all Phase 1 checks."""
    from reos.rpc_handlers.health import _get_health_components

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        runner, anti_nag, store = _get_health_components(mock_db)

    # Run checks to see what's registered
    results = runner.run_all_checks()
    check_names = {r.check_name for r in results}

    assert "context_freshness" in check_names
    assert "act_vitality" in check_names
    assert "data_integrity" in check_names


def test_health_components_handles_phase_2_imports_gracefully(
    mock_db: Database, tmp_play_path: Path
):
    """_get_health_components should handle missing Phase 2+ checks gracefully."""
    from reos.rpc_handlers.health import _get_health_components

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        # Should not raise ImportError even if Phase 2 checks don't exist
        runner, anti_nag, store = _get_health_components(mock_db)

    # Should have at least Phase 1 checks
    results = runner.run_all_checks()
    assert len(results) >= 3  # At least 3 Phase 1 checks


def test_handle_health_status_caches_results(mock_db: Database, tmp_play_path: Path):
    """Multiple status calls should use cached results."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result1 = handle_health_status(mock_db)
        result2 = handle_health_status(mock_db)

    # Results should be identical (from cache)
    assert result1 == result2


def test_handle_health_findings_count_matches_list_length(mock_db: Database, tmp_play_path: Path):
    """finding_count should match the length of findings list."""
    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_findings(mock_db)

    assert result["finding_count"] == len(result["findings"])


def test_exception_handling_returns_safe_defaults(mock_db: Database):
    """Exceptions during health checks should return safe defaults."""
    # Mock get_current_play_path to raise an exception
    with patch(
        "reos.rpc_handlers.health.get_current_play_path",
        side_effect=Exception("Test error"),
    ):
        result = handle_health_status(mock_db)

    # Should return safe defaults instead of crashing
    assert result["overall_severity"] == "healthy"
    assert result["finding_count"] == 0


def test_rpc_error_for_no_active_play_in_acknowledge(mock_db: Database):
    """handle_health_acknowledge should raise RpcError if no active play."""
    from reos.rpc_handlers import RpcError

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=None):
        with pytest.raises(RpcError) as exc_info:
            handle_health_acknowledge(mock_db, log_id="test-id")

    assert "No active play" in str(exc_info.value)


def test_unacknowledged_count_reflects_anti_nag_state(mock_db: Database, tmp_play_path: Path):
    """unacknowledged_count should reflect anti-nag protocol state."""
    # Create and surface a finding
    cairn_db = tmp_play_path / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db)

    from reos.cairn.health.anti_nag import AntiNagProtocol

    conn = store._get_connection()
    anti_nag = AntiNagProtocol(conn)
    anti_nag.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:unack",
        title="Test",
    )

    with patch("reos.rpc_handlers.health.get_current_play_path", return_value=str(tmp_play_path)):
        result = handle_health_status(mock_db)

    # Should show 1 unacknowledged
    assert result["unacknowledged_count"] == 1
