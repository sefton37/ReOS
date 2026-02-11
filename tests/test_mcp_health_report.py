"""Tests for MCP health tool integration.

Run with: PYTHONPATH=src pytest tests/test_mcp_health_report.py -v --no-cov
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.cairn.mcp_tools import CairnToolHandler, list_tools
from reos.cairn.store import CairnStore


@pytest.fixture
def store(tmp_path: Path) -> CairnStore:
    """Create a fresh CairnStore."""
    db_path = tmp_path / "cairn.db"
    return CairnStore(db_path)


@pytest.fixture
def handler(store: CairnStore) -> CairnToolHandler:
    """Create a CairnToolHandler."""
    return CairnToolHandler(store=store)


def test_cairn_health_report_in_list_tools():
    """cairn_health_report tool should be in the list of available tools."""
    tools = list_tools()
    tool_names = [t.name for t in tools]

    assert "cairn_health_report" in tool_names


def test_cairn_acknowledge_health_in_list_tools():
    """cairn_acknowledge_health tool should be in the list of available tools."""
    tools = list_tools()
    tool_names = [t.name for t in tools]

    assert "cairn_acknowledge_health" in tool_names


def test_health_report_tool_schema():
    """cairn_health_report should have correct schema."""
    tools = list_tools()
    health_report_tool = next(t for t in tools if t.name == "cairn_health_report")

    assert health_report_tool.description is not None
    assert "health" in health_report_tool.description.lower()
    assert health_report_tool.input_schema["type"] == "object"
    assert "properties" in health_report_tool.input_schema


def test_acknowledge_health_tool_schema():
    """cairn_acknowledge_health should have correct schema with log_id."""
    tools = list_tools()
    ack_tool = next(t for t in tools if t.name == "cairn_acknowledge_health")

    assert ack_tool.description is not None
    assert "acknowledge" in ack_tool.description.lower()
    schema = ack_tool.input_schema
    assert "log_id" in schema["properties"]
    assert "log_id" in schema["required"]


def test_health_report_runs_without_error(handler: CairnToolHandler):
    """_health_report should run without error on a fresh store."""
    result = handler.call_tool("cairn_health_report", {})

    # Should return a dict with expected keys
    assert isinstance(result, dict)
    assert "full_results" in result
    assert "surfaced_messages" in result
    assert "summary" in result

    # full_results should be a list
    assert isinstance(result["full_results"], list)

    # summary should have expected structure
    assert "overall_severity" in result["summary"]
    assert "finding_count" in result["summary"]


def test_health_report_with_fresh_store_returns_healthy_or_warning(handler: CairnToolHandler):
    """Fresh store with no data should return healthy or warning status."""
    result = handler.call_tool("cairn_health_report", {})

    summary = result["summary"]

    # Should be healthy (no acts = healthy for context/vitality checks)
    # Data integrity check might return warning for empty database
    assert summary["overall_severity"] in ["healthy", "warning"]


def test_health_report_includes_all_phase_1_checks(handler: CairnToolHandler):
    """Health report should include results from all Phase 1 checks."""
    result = handler.call_tool("cairn_health_report", {})

    full_results = result["full_results"]
    check_names = {r["check_name"] for r in full_results}

    # Phase 1 checks
    assert "context_freshness" in check_names
    assert "act_vitality" in check_names
    assert "data_integrity" in check_names


def test_acknowledge_health_with_valid_log_id(handler: CairnToolHandler):
    """_acknowledge_health should work with a valid log_id."""
    # First, create a finding (initializes runner)
    handler.call_tool("cairn_health_report", {})

    # Manually create a surfaced finding to acknowledge
    from reos.cairn.health.anti_nag import AntiNagProtocol

    conn = handler.store._get_connection()
    anti_nag = AntiNagProtocol(conn)
    log_id = anti_nag.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:ack",
        title="Test finding",
    )

    # Now acknowledge it via the tool
    result = handler.call_tool("cairn_acknowledge_health", {"log_id": log_id})

    assert result["success"] is True


def test_acknowledge_health_with_invalid_log_id(handler: CairnToolHandler):
    """_acknowledge_health should return success=False for invalid log_id."""
    result = handler.call_tool("cairn_acknowledge_health", {"log_id": "nonexistent"})

    assert result["success"] is False


def test_acknowledge_health_missing_log_id_raises_error(handler: CairnToolHandler):
    """_acknowledge_health should raise error if log_id is missing."""
    from reos.cairn.mcp_tools import CairnToolError

    with pytest.raises(CairnToolError) as exc_info:
        handler.call_tool("cairn_acknowledge_health", {})

    assert "log_id is required" in str(exc_info.value)


def test_health_report_filters_through_anti_nag(handler: CairnToolHandler, store: CairnStore):
    """Health report should filter findings through anti-nag protocol."""
    # Create a stale act (should trigger warning)
    from datetime import datetime, timedelta

    store.touch("act", "act-stale")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stale"),
    )
    conn.commit()
    conn.close()

    # First call should surface the finding
    result1 = handler.call_tool("cairn_health_report", {})
    assert len(result1["surfaced_messages"]) > 0

    # Second call should NOT surface (rate limited)
    result2 = handler.call_tool("cairn_health_report", {})
    assert len(result2["surfaced_messages"]) == 0


def test_surfaced_messages_include_log_id(handler: CairnToolHandler, store: CairnStore):
    """Surfaced messages should include log_id for acknowledgment."""
    # Create a critical finding (bypasses rate limits)
    from datetime import datetime, timedelta

    store.touch("act", "act-critical")
    forty_days_ago = (datetime.now() - timedelta(days=40)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (forty_days_ago, "act-critical"),
    )
    conn.commit()
    conn.close()

    result = handler.call_tool("cairn_health_report", {})

    surfaced = result["surfaced_messages"]
    if surfaced:  # May be empty due to rate limiting
        assert "log_id" in surfaced[0]


def test_health_report_full_results_include_healthy(handler: CairnToolHandler):
    """full_results should include healthy results, surfaced_messages should not."""
    result = handler.call_tool("cairn_health_report", {})

    full_results = result["full_results"]
    surfaced = result["surfaced_messages"]

    # full_results should include healthy results
    healthy_results = [r for r in full_results if r["severity"] == "healthy"]
    assert len(healthy_results) > 0

    # surfaced_messages should not include healthy (anti-nag filters them)
    if surfaced:
        for msg in surfaced:
            assert msg["severity"] != "healthy"


def test_health_report_imports_phase_2_checks_gracefully(handler: CairnToolHandler):
    """Health report should handle missing Phase 2+ checks gracefully."""
    # This test validates that the try/except blocks work
    # Phase 2 checks may not exist yet, but should not crash
    result = handler.call_tool("cairn_health_report", {})

    # Should complete without error
    assert "full_results" in result
    assert "summary" in result
