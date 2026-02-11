"""Tests for Health Check Runner.

Run with: PYTHONPATH=src pytest tests/test_health_runner.py -v --no-cov
"""

from __future__ import annotations

import time

from reos.cairn.health.runner import (
    CACHE_TTL_SECONDS,
    HealthCheckResult,
    HealthCheckRunner,
    Severity,
)


class MockHealthCheck:
    """Mock health check for testing."""

    def __init__(self, name: str, results: list[HealthCheckResult]) -> None:
        self._name = name
        self._results = results
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> list[HealthCheckResult]:
        self.call_count += 1
        return self._results


class FailingHealthCheck:
    """Mock health check that raises an exception."""

    name = "failing_check"

    def run(self) -> list[HealthCheckResult]:
        raise RuntimeError("Intentional test failure")


def test_register_and_run_checks():
    """Runner should register and run checks."""
    runner = HealthCheckRunner()

    check1 = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    check2 = MockHealthCheck(
        "check2",
        [HealthCheckResult("check2", Severity.WARNING, "Minor issue")],
    )

    runner.register(check1)
    runner.register(check2)

    results = runner.run_all_checks()

    assert len(results) == 2
    assert check1.call_count == 1
    assert check2.call_count == 1


def test_caching_returns_cached_results_within_ttl():
    """Second call within TTL should return cached results without re-running."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    runner.register(check)

    # First call
    results1 = runner.run_all_checks()
    assert check.call_count == 1

    # Second call (within TTL)
    results2 = runner.run_all_checks()
    assert check.call_count == 1  # Should not re-run
    assert results1 == results2


def test_cache_expires_after_ttl():
    """Cache should expire after TTL, causing checks to re-run."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    runner.register(check)

    # First call
    runner.run_all_checks()
    assert check.call_count == 1

    # Manipulate cache timestamp to simulate expiration
    if runner._cache:
        runner._cache.timestamp = time.monotonic() - CACHE_TTL_SECONDS - 1

    # Second call (cache expired)
    runner.run_all_checks()
    assert check.call_count == 2


def test_invalidate_cache_clears_cache():
    """invalidate_cache should clear cached results."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    runner.register(check)

    # First call
    runner.run_all_checks()
    assert check.call_count == 1

    # Invalidate cache
    runner.invalidate_cache()

    # Second call should re-run
    runner.run_all_checks()
    assert check.call_count == 2


def test_status_summary_computation():
    """Status summary should reflect overall severity and finding count."""
    runner = HealthCheckRunner()

    check1 = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    check2 = MockHealthCheck(
        "check2",
        [HealthCheckResult("check2", Severity.WARNING, "Minor issue")],
    )
    check3 = MockHealthCheck(
        "check3",
        [HealthCheckResult("check3", Severity.CRITICAL, "Critical issue")],
    )

    runner.register(check1)
    runner.register(check2)
    runner.register(check3)

    status = runner.get_status_summary()

    assert status.overall_severity == Severity.CRITICAL  # Worst severity
    assert status.finding_count == 2  # WARNING + CRITICAL (not HEALTHY)


def test_status_summary_all_healthy():
    """Status summary with all healthy checks should show healthy."""
    runner = HealthCheckRunner()

    check1 = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    check2 = MockHealthCheck(
        "check2",
        [HealthCheckResult("check2", Severity.HEALTHY, "All good")],
    )

    runner.register(check1)
    runner.register(check2)

    status = runner.get_status_summary()

    assert status.overall_severity == Severity.HEALTHY
    assert status.finding_count == 0


def test_status_summary_warning_only():
    """Status with only warnings should show warning severity."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.WARNING, "Warning")],
    )
    runner.register(check)

    status = runner.get_status_summary()

    assert status.overall_severity == Severity.WARNING
    assert status.finding_count == 1


def test_get_findings_filters_healthy():
    """get_findings should return only non-healthy results."""
    runner = HealthCheckRunner()

    check1 = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    check2 = MockHealthCheck(
        "check2",
        [HealthCheckResult("check2", Severity.WARNING, "Warning")],
    )
    check3 = MockHealthCheck(
        "check3",
        [HealthCheckResult("check3", Severity.CRITICAL, "Critical")],
    )

    runner.register(check1)
    runner.register(check2)
    runner.register(check3)

    findings = runner.get_findings()

    assert len(findings) == 2
    assert all(f.severity != Severity.HEALTHY for f in findings)


def test_failed_check_produces_warning_result():
    """A check that raises an exception should produce a warning result."""
    runner = HealthCheckRunner()

    failing = FailingHealthCheck()
    runner.register(failing)

    results = runner.run_all_checks()

    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "failed to run" in results[0].title
    assert results[0].check_name == "failing_check"
    assert results[0].finding_key == "failing_check:error"


def test_failed_check_does_not_crash_runner():
    """A failing check should not prevent other checks from running."""
    runner = HealthCheckRunner()

    failing = FailingHealthCheck()
    healthy = MockHealthCheck(
        "healthy_check",
        [HealthCheckResult("healthy_check", Severity.HEALTHY, "All good")],
    )

    runner.register(failing)
    runner.register(healthy)

    results = runner.run_all_checks()

    # Should have results from both checks
    assert len(results) == 2
    assert healthy.call_count == 1


def test_multiple_results_from_single_check():
    """A check can return multiple results."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "multi_result",
        [
            HealthCheckResult("multi_result", Severity.WARNING, "Issue 1"),
            HealthCheckResult("multi_result", Severity.WARNING, "Issue 2"),
        ],
    )
    runner.register(check)

    results = runner.run_all_checks()

    assert len(results) == 2


def test_status_summary_uses_cache():
    """get_status_summary should use cached results when available."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.HEALTHY, "All good")],
    )
    runner.register(check)

    # First call
    runner.get_status_summary()
    assert check.call_count == 1

    # Second call (should use cache)
    runner.get_status_summary()
    assert check.call_count == 1


def test_health_check_result_to_dict():
    """HealthCheckResult.to_dict should return correct format."""
    result = HealthCheckResult(
        check_name="test_check",
        severity=Severity.WARNING,
        title="Test warning",
        details="Some details",
        finding_key="test:key",
    )

    data = result.to_dict()

    assert data["check_name"] == "test_check"
    assert data["severity"] == "warning"
    assert data["title"] == "Test warning"
    assert data["details"] == "Some details"
    assert data["finding_key"] == "test:key"


def test_health_status_to_dict():
    """HealthStatus.to_dict should return correct format."""
    runner = HealthCheckRunner()

    check = MockHealthCheck(
        "check1",
        [HealthCheckResult("check1", Severity.WARNING, "Warning")],
    )
    runner.register(check)

    status = runner.get_status_summary()
    data = status.to_dict()

    assert data["overall_severity"] == "warning"
    assert data["finding_count"] == 1
    assert "unacknowledged_count" in data


def test_empty_runner_returns_healthy():
    """Runner with no checks should return healthy status."""
    runner = HealthCheckRunner()

    status = runner.get_status_summary()

    assert status.overall_severity == Severity.HEALTHY
    assert status.finding_count == 0


def test_finding_key_defaults_to_empty():
    """HealthCheckResult finding_key should default to empty string."""
    result = HealthCheckResult(
        check_name="test",
        severity=Severity.HEALTHY,
        title="Test",
    )

    assert result.finding_key == ""


def test_details_defaults_to_empty():
    """HealthCheckResult details should default to empty string."""
    result = HealthCheckResult(
        check_name="test",
        severity=Severity.HEALTHY,
        title="Test",
    )

    assert result.details == ""
