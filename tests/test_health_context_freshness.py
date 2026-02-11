"""Tests for Context Freshness health check.

Run with: PYTHONPATH=src pytest tests/test_health_context_freshness.py -v --no-cov
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from reos.cairn.health.checks.context_freshness import ContextFreshnessCheck
from reos.cairn.health.runner import Severity
from reos.cairn.store import CairnStore


@pytest.fixture
def store(tmp_path: Path) -> CairnStore:
    """Create a fresh CairnStore."""
    db_path = tmp_path / "cairn.db"
    return CairnStore(db_path)


def test_no_acts_returns_healthy(store: CairnStore):
    """With no Acts, check should return healthy."""
    check = ContextFreshnessCheck(store)
    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY
    assert "No Acts tracked yet" in results[0].title
    assert results[0].finding_key == "context_freshness:no_acts"


def test_all_acts_fresh_returns_healthy(store: CairnStore):
    """When all Acts have recent context, check should return healthy."""
    check = ContextFreshnessCheck(store)

    # Create two fresh acts (touched today)
    store.touch("act", "act-1")
    store.touch("act", "act-2")

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY
    assert "All Acts have recent context" in results[0].title


def test_acts_14_to_30_days_stale_returns_warning(store: CairnStore):
    """Acts stale between 14-29 days should return warning."""
    check = ContextFreshnessCheck(store)

    # Create an act and manually set last_touched to 20 days ago
    store.touch("act", "act-stale")

    # Update last_touched to 20 days ago
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stale"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "1 Act(s) have stale context" in results[0].title
    # Check for presence of stale details (exact days might vary by a day due to timing)
    assert "days" in results[0].details
    # Implementation truncates act_id to first 8 chars
    assert "act-stal" in results[0].details


def test_acts_30_plus_days_stale_returns_critical(store: CairnStore):
    """Acts stale 30+ days should return critical severity."""
    check = ContextFreshnessCheck(store)

    # Create an act and set last_touched to 35 days ago
    store.touch("act", "act-very-stale")

    thirty_five_days_ago = (datetime.now() - timedelta(days=35)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (thirty_five_days_ago, "act-very-stale"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.CRITICAL
    assert "1 Act(s) have stale context" in results[0].title
    assert "35 days" in results[0].details


def test_mix_of_fresh_and_stale_acts(store: CairnStore):
    """Mix of fresh and stale Acts should report only stale ones."""
    check = ContextFreshnessCheck(store)

    # Fresh act
    store.touch("act", "act-fresh")

    # Stale act (25 days)
    store.touch("act", "act-stale-1")
    twenty_five_days_ago = (datetime.now() - timedelta(days=25)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_five_days_ago, "act-stale-1"),
    )
    conn.commit()

    # Very stale act (40 days)
    store.touch("act", "act-stale-2")
    forty_days_ago = (datetime.now() - timedelta(days=40)).isoformat()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (forty_days_ago, "act-stale-2"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.CRITICAL  # Worst is 40 days
    assert "2 Act(s) have stale context" in results[0].title
    # Implementation truncates act_id to first 8 chars
    assert "act-stal" in results[0].details  # Matches both act-stale-1 and act-stale-2
    # Check for presence of day counts (exact values might vary by timing)
    assert "days" in results[0].details
    # Fresh act should not be mentioned
    assert "act-fres" not in results[0].details


def test_act_with_null_last_touched_treated_as_very_stale(store: CairnStore):
    """Acts with null last_touched should be treated as critically stale."""
    check = ContextFreshnessCheck(store)

    # Create metadata with null last_touched
    conn = store._get_connection()
    conn.execute(
        """
        INSERT INTO cairn_metadata (entity_type, entity_id, last_touched, touch_count)
        VALUES (?, ?, NULL, 0)
        """,
        ("act", "act-never-touched"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.CRITICAL
    assert "999 days" in results[0].details  # Code uses 999 for null


def test_finding_key_includes_staleness_details(store: CairnStore):
    """Finding key should include count and worst staleness for deduplication."""
    check = ContextFreshnessCheck(store)

    # Create two stale acts
    store.touch("act", "act-1")
    store.touch("act", "act-2")

    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-1"),
    )
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (thirty_days_ago, "act-2"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    # Finding key should include count and worst staleness
    assert results[0].finding_key == "context_freshness:stale:2:30"


def test_reframe_protocol_language(store: CairnStore):
    """Check should use Reframe Protocol language (system limitation, not user failure)."""
    check = ContextFreshnessCheck(store)

    store.touch("act", "act-stale")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stale"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    # Should frame as system limitation
    assert "My context" in results[0].details
    assert "may be outdated" in results[0].details
    assert "I work best with fresh information" in results[0].details
    # Should NOT contain blaming language
    assert "you should" not in results[0].details.lower()
    assert "you need to" not in results[0].details.lower()
