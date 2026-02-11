"""Tests for Act Vitality health check.

Run with: PYTHONPATH=src pytest tests/test_health_act_vitality.py -v --no-cov
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from reos.cairn.health.checks.act_vitality import ActVitalityCheck
from reos.cairn.health.runner import Severity
from reos.cairn.models import ActivityType
from reos.cairn.store import CairnStore


@pytest.fixture
def store(tmp_path: Path) -> CairnStore:
    """Create a fresh CairnStore."""
    db_path = tmp_path / "cairn.db"
    return CairnStore(db_path)


def test_no_acts_returns_healthy(store: CairnStore):
    """With no Acts tracked, check should return healthy."""
    check = ActVitalityCheck(store)
    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY
    assert "No Acts tracked" in results[0].title
    assert results[0].finding_key == "act_vitality:no_acts"


def test_acts_with_recent_activity_returns_healthy(store: CairnStore):
    """Acts with recent scene activity should return healthy."""
    check = ActVitalityCheck(store)

    # Create an act
    store.touch("act", "act-active")

    # Create a scene and log activity
    store.touch("scene", "scene-1")
    store.log_activity(
        entity_type="scene",
        entity_id="scene-1",
        activity_type=ActivityType.CREATED,
    )

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY
    assert "All tracked Acts show recent activity" in results[0].title


def test_acts_with_no_recent_scene_activity_returns_warning(store: CairnStore):
    """Acts with no scene activity in 14+ days should return warning."""
    check = ActVitalityCheck(store)

    # Create an act
    store.touch("act", "act-stalled")

    # Set last_touched to 20 days ago (past the 14-day threshold)
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stalled"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "Act(s) may need attention" in results[0].title
    # Implementation truncates act_id to first 8 chars
    assert "act-stal" in results[0].details
    # Check for mention of the threshold
    assert "14" in results[0].details or "days" in results[0].details


def test_act_touched_recently_but_no_scenes_is_healthy(store: CairnStore):
    """Act touched recently (even without scenes) should be healthy."""
    check = ActVitalityCheck(store)

    # Create an act and touch it
    store.touch("act", "act-recent")

    # No scenes, but the act itself was touched recently
    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY


def test_multiple_stalled_acts(store: CairnStore):
    """Multiple stalled Acts should all be reported."""
    check = ActVitalityCheck(store)

    # Create three stalled acts
    for i in range(3):
        store.touch("act", f"act-stalled-{i}")

    # Set all to 20 days ago
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    conn = store._get_connection()
    for i in range(3):
        conn.execute(
            "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
            (twenty_days_ago, f"act-stalled-{i}"),
        )
    conn.commit()
    conn.close()

    results = check.run()

    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "Act(s) may need attention" in results[0].title
    # Implementation truncates act_id to first 8 chars, so check for prefix
    assert "act-stal" in results[0].details


def test_scene_activity_within_14_days_makes_act_healthy(store: CairnStore):
    """Scene activity within 14 days should make the Act healthy."""
    check = ActVitalityCheck(store)

    # Create an act (touched 20 days ago)
    store.touch("act", "act-has-recent-scene")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-has-recent-scene"),
    )
    conn.commit()
    conn.close()

    # Create a scene and log recent activity (5 days ago)
    store.touch("scene", "scene-recent")
    five_days_ago = (datetime.now() - timedelta(days=5)).isoformat()
    conn = store._get_connection()
    # Log activity directly to get specific timestamp
    conn.execute(
        """
        INSERT INTO activity_log (log_id, entity_type, entity_id, activity_type, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("log-1", "scene", "scene-recent", "viewed", five_days_ago),
    )
    conn.commit()
    conn.close()

    results = check.run()

    # Should be healthy because scene has recent activity
    assert len(results) == 1
    assert results[0].severity == Severity.HEALTHY


def test_finding_key_includes_stalled_count(store: CairnStore):
    """Finding key should include count of stalled acts for deduplication."""
    check = ActVitalityCheck(store)

    # Create two stalled acts
    store.touch("act", "act-1")
    store.touch("act", "act-2")

    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-1"),
    )
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-2"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    assert results[0].finding_key == "act_vitality:stalled:2"


def test_reframe_protocol_language(store: CairnStore):
    """Check should use Reframe Protocol language (gentle, non-blaming)."""
    check = ActVitalityCheck(store)

    store.touch("act", "act-stalled")
    twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()

    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (twenty_days_ago, "act-stalled"),
    )
    conn.commit()
    conn.close()

    results = check.run()

    # Should frame gently
    assert "waiting for you when you're ready" in results[0].details
    # Should NOT contain blaming language
    assert "you should" not in results[0].details.lower()
    assert "you need to" not in results[0].details.lower()
    assert "you must" not in results[0].details.lower()


def test_stale_days_threshold_is_14(store: CairnStore):
    """Check should use 14 days as the threshold."""
    check = ActVitalityCheck(store)

    assert check.STALE_DAYS == 14

    # Create an act exactly 13 days old (should be healthy)
    store.touch("act", "act-13days")
    thirteen_days_ago = (datetime.now() - timedelta(days=13)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (thirteen_days_ago, "act-13days"),
    )
    conn.commit()
    conn.close()

    results = check.run()
    assert results[0].severity == Severity.HEALTHY

    # Now create an act exactly 14 days old (should be warning)
    store.touch("act", "act-14days")
    fourteen_days_ago = (datetime.now() - timedelta(days=14)).isoformat()
    conn = store._get_connection()
    conn.execute(
        "UPDATE cairn_metadata SET last_touched = ? WHERE entity_id = ?",
        (fourteen_days_ago, "act-14days"),
    )
    conn.commit()
    conn.close()

    results = check.run()
    assert results[0].severity == Severity.WARNING
