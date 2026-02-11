"""Tests for the Anti-Nag Protocol.

Run with: PYTHONPATH=src pytest tests/test_anti_nag_protocol.py -v --no-cov
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from reos.cairn.health.anti_nag import (
    DEFAULT_CHECK_CONFIG,
    AntiNagProtocol,
    init_health_check_defaults,
    init_health_tables,
)


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary database with health tables."""
    db_path = tmp_path / "test_anti_nag.db"
    conn = sqlite3.connect(str(db_path))
    init_health_tables(conn)
    init_health_check_defaults(conn)
    return conn


def test_healthy_findings_never_surfaced(db_conn: sqlite3.Connection):
    """Healthy findings should never be surfaced."""
    protocol = AntiNagProtocol(db_conn)

    should_show = protocol.should_surface(
        check_name="context_freshness",
        severity="healthy",
        finding_key="test:healthy",
    )

    assert should_show is False


def test_warning_respects_rate_limits(db_conn: sqlite3.Connection):
    """Warning severity should respect min_interval_hours rate limit."""
    protocol = AntiNagProtocol(db_conn)

    # First surfacing should succeed
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:warning:1",
    ) is True

    # Log it
    protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:warning:1",
        title="Test warning",
    )

    # Second surfacing with different key should fail (rate limit per check)
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:warning:2",
    ) is False


def test_critical_bypasses_rate_limits(db_conn: sqlite3.Connection):
    """Critical severity should bypass rate limit checks."""
    protocol = AntiNagProtocol(db_conn)

    # Surface a critical finding
    assert protocol.should_surface(
        check_name="data_integrity",
        severity="critical",
        finding_key="test:critical:1",
    ) is True

    protocol.log_surfaced(
        check_name="data_integrity",
        severity="critical",
        finding_key="test:critical:1",
        title="Test critical",
    )

    # Another critical should still surface immediately (bypasses rate limit)
    assert protocol.should_surface(
        check_name="data_integrity",
        severity="critical",
        finding_key="test:critical:2",
    ) is True


def test_acknowledged_findings_not_resurfaced(db_conn: sqlite3.Connection):
    """Acknowledged findings should not be surfaced again."""
    protocol = AntiNagProtocol(db_conn)

    # Surface a finding
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:ack",
    ) is True

    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:ack",
        title="Test acknowledgment",
    )

    # Acknowledge it
    success = protocol.acknowledge(log_id)
    assert success is True

    # Should not surface again (even for critical)
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="critical",
        finding_key="test:ack",
    ) is False


def test_snoozed_findings_not_resurfaced(db_conn: sqlite3.Connection):
    """Snoozed findings should not be surfaced until snooze expires."""
    protocol = AntiNagProtocol(db_conn)

    # Surface a finding
    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:snooze",
        title="Test snooze",
    )

    # Snooze it for 24 hours
    success = protocol.snooze(log_id, hours=24)
    assert success is True

    # Should not surface while snoozed (even critical)
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="critical",
        finding_key="test:snooze",
    ) is False


def test_snooze_expires_after_duration(db_conn: sqlite3.Connection):
    """Snoozed findings should be surfaceable after snooze expires."""
    protocol = AntiNagProtocol(db_conn)

    # Surface and snooze
    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:snooze_expire",
        title="Test snooze expiration",
    )

    # Manually set snooze to expired timestamp
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    db_conn.execute(
        "UPDATE health_surfacing_log SET snoozed_until = ? WHERE log_id = ?",
        (past, log_id),
    )
    db_conn.commit()

    # Should be surfaceable now (but rate limit still applies for non-critical)
    # Use critical to bypass rate limit for this test
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="critical",
        finding_key="test:snooze_expire",
    ) is True


def test_log_surfaced_records_and_increments_session_count(db_conn: sqlite3.Connection):
    """log_surfaced should record the finding and increment session count."""
    protocol = AntiNagProtocol(db_conn)

    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:log",
        title="Test title",
        details="Test details",
    )

    # Verify it was recorded
    row = db_conn.execute(
        "SELECT * FROM health_surfacing_log WHERE log_id = ?",
        (log_id,),
    ).fetchone()

    assert row is not None
    # Check column values by index based on INSERT order
    # (log_id, check_name, severity, finding_key, title, details, surfaced_at, acknowledged, ...)
    assert row[0] == log_id
    assert row[1] == "context_freshness"
    assert row[2] == "warning"
    assert row[3] == "test:log"
    assert row[4] == "Test title"
    assert row[5] == "Test details"
    assert row[7] == 0  # acknowledged

    # Verify session count incremented
    assert protocol._session_counts["context_freshness"] == 1


def test_acknowledge_marks_as_acknowledged(db_conn: sqlite3.Connection):
    """acknowledge() should mark finding as acknowledged."""
    protocol = AntiNagProtocol(db_conn)

    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:ack2",
        title="Test",
    )

    # Should not be acknowledged initially
    row = db_conn.execute(
        "SELECT acknowledged FROM health_surfacing_log WHERE log_id = ?",
        (log_id,),
    ).fetchone()
    assert row[0] == 0

    # Acknowledge
    success = protocol.acknowledge(log_id)
    assert success is True

    # Should be acknowledged now
    row = db_conn.execute(
        "SELECT acknowledged, acknowledged_at FROM health_surfacing_log WHERE log_id = ?",
        (log_id,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] is not None  # acknowledged_at timestamp


def test_acknowledge_nonexistent_returns_false(db_conn: sqlite3.Connection):
    """acknowledge() should return False for nonexistent log_id."""
    protocol = AntiNagProtocol(db_conn)

    success = protocol.acknowledge("nonexistent-id")
    assert success is False


def test_snooze_sets_timestamp(db_conn: sqlite3.Connection):
    """snooze() should set snoozed_until timestamp."""
    protocol = AntiNagProtocol(db_conn)

    log_id = protocol.log_surfaced(
        check_name="context_freshness",
        severity="warning",
        finding_key="test:snooze2",
        title="Test",
    )

    # Snooze for 24 hours
    before_snooze = datetime.now()
    success = protocol.snooze(log_id, hours=24)
    assert success is True

    # Check timestamp
    row = db_conn.execute(
        "SELECT snoozed_until FROM health_surfacing_log WHERE log_id = ?",
        (log_id,),
    ).fetchone()
    assert row[0] is not None

    snooze_until = datetime.fromisoformat(row[0])
    expected = before_snooze + timedelta(hours=24)
    # Allow 1 second tolerance for test execution time
    assert abs((snooze_until - expected).total_seconds()) < 1


def test_snooze_nonexistent_returns_false(db_conn: sqlite3.Connection):
    """snooze() should return False for nonexistent log_id."""
    protocol = AntiNagProtocol(db_conn)

    success = protocol.snooze("nonexistent-id", hours=24)
    assert success is False


def test_get_unacknowledged_count(db_conn: sqlite3.Connection):
    """get_unacknowledged_count should count correctly."""
    protocol = AntiNagProtocol(db_conn)

    # Initially zero
    assert protocol.get_unacknowledged_count() == 0

    # Add two findings
    log_id1 = protocol.log_surfaced(
        "context_freshness", "warning", "test:1", "Test 1"
    )
    log_id2 = protocol.log_surfaced(
        "act_vitality", "warning", "test:2", "Test 2"
    )

    # Should be 2
    assert protocol.get_unacknowledged_count() == 2

    # Acknowledge one
    protocol.acknowledge(log_id1)
    assert protocol.get_unacknowledged_count() == 1

    # Snooze the other (not expired)
    protocol.snooze(log_id2, hours=24)
    assert protocol.get_unacknowledged_count() == 0  # snoozed doesn't count

    # Expire the snooze
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    db_conn.execute(
        "UPDATE health_surfacing_log SET snoozed_until = ? WHERE log_id = ?",
        (past, log_id2),
    )
    db_conn.commit()

    # Should count again
    assert protocol.get_unacknowledged_count() == 1


def test_init_health_tables_creates_tables(tmp_path: Path):
    """init_health_tables should create required tables and indexes."""
    db_path = tmp_path / "test_init.db"
    conn = sqlite3.connect(str(db_path))

    init_health_tables(conn)

    # Check tables exist
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t[0] for t in tables}

    assert "health_surfacing_log" in table_names
    assert "health_check_config" in table_names

    # Check indexes exist
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    index_names = {i[0] for i in indexes}

    assert "idx_health_surfacing_check" in index_names
    assert "idx_health_surfacing_key" in index_names
    assert "idx_health_surfacing_time" in index_names


def test_init_health_check_defaults_seeds_config(tmp_path: Path):
    """init_health_check_defaults should seed config without overwriting."""
    db_path = tmp_path / "test_defaults.db"
    conn = sqlite3.connect(str(db_path))
    init_health_tables(conn)

    # Seed defaults
    init_health_check_defaults(conn)

    # Check all default checks are present
    rows = conn.execute(
        "SELECT check_name FROM health_check_config"
    ).fetchall()
    check_names = {r[0] for r in rows}

    for check_name in DEFAULT_CHECK_CONFIG.keys():
        assert check_name in check_names

    # Modify one config
    conn.execute(
        "UPDATE health_check_config SET config_json = ? WHERE check_name = ?",
        ('{"enabled": false}', "context_freshness"),
    )
    conn.commit()

    # Re-seed should not overwrite (INSERT OR IGNORE)
    init_health_check_defaults(conn)

    row = conn.execute(
        "SELECT config_json FROM health_check_config WHERE check_name = ?",
        ("context_freshness",),
    ).fetchone()

    assert row[0] == '{"enabled": false}'


def test_session_caps_prevent_spam(db_conn: sqlite3.Connection):
    """Session caps should prevent excessive surfacing of same check."""
    protocol = AntiNagProtocol(db_conn)

    # context_freshness has max_per_session = 2 by default
    check_name = "context_freshness"

    # First two should succeed (use unique finding keys)
    for i in range(2):
        finding_key = f"test:cap:{i}"
        assert protocol.should_surface(
            check_name=check_name,
            severity="critical",  # Use critical to bypass rate limit
            finding_key=finding_key,
        ) is True
        protocol.log_surfaced(check_name, "critical", finding_key, f"Test {i}")

    # Third should fail (session cap reached)
    # Use critical to bypass rate limit, but session cap still applies
    assert protocol.should_surface(
        check_name=check_name,
        severity="warning",  # Even warnings should fail once cap is reached
        finding_key="test:cap:3",
    ) is False


def test_disabled_check_not_surfaced(db_conn: sqlite3.Connection):
    """Checks with enabled=false in config should not surface."""
    protocol = AntiNagProtocol(db_conn)

    # Disable context_freshness
    db_conn.execute(
        "UPDATE health_check_config SET config_json = ? WHERE check_name = ?",
        ('{"enabled": false, "min_interval_hours": 24, "max_per_session": 2}',
         "context_freshness"),
    )
    db_conn.commit()

    # Should not surface
    assert protocol.should_surface(
        check_name="context_freshness",
        severity="critical",
        finding_key="test:disabled",
    ) is False
