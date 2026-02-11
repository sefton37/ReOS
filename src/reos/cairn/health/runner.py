"""Health Check Runner — Orchestrates all registered checks with caching.

Results are cached for 5 minutes to avoid redundant DB queries.
Cache is invalidated when user acknowledges/snoozes a finding.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes


class Severity(Enum):
    """Health check severity levels."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """Result from a single health check."""

    check_name: str
    severity: Severity
    title: str
    details: str = ""
    finding_key: str = ""  # Unique key for dedup (check_name + specifics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "severity": self.severity.value,
            "title": self.title,
            "details": self.details,
            "finding_key": self.finding_key,
        }


@dataclass
class HealthStatus:
    """Lightweight summary for UI polling."""

    overall_severity: Severity
    finding_count: int
    unacknowledged_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_severity": self.overall_severity.value,
            "finding_count": self.finding_count,
            "unacknowledged_count": self.unacknowledged_count,
        }


class HealthCheck(Protocol):
    """Protocol for health check implementations."""

    @property
    def name(self) -> str: ...

    def run(self) -> list[HealthCheckResult]: ...


@dataclass
class _CachedResults:
    """Internal cache entry."""

    results: list[HealthCheckResult]
    timestamp: float
    status: HealthStatus


class HealthCheckRunner:
    """Orchestrates all registered health checks with result caching."""

    def __init__(self) -> None:
        self._checks: list[HealthCheck] = []
        self._cache: _CachedResults | None = None

    def register(self, check: HealthCheck) -> None:
        """Register a health check."""
        self._checks.append(check)

    def invalidate_cache(self) -> None:
        """Invalidate the cached results (call after acknowledge/snooze)."""
        self._cache = None

    def run_all_checks(self) -> list[HealthCheckResult]:
        """Run all registered checks, returning cached results if fresh.

        Returns:
            List of all check results (including healthy ones).
        """
        if self._cache and (time.monotonic() - self._cache.timestamp) < CACHE_TTL_SECONDS:
            return self._cache.results

        results: list[HealthCheckResult] = []
        for check in self._checks:
            try:
                check_results = check.run()
                results.extend(check_results)
            except Exception:
                logger.exception("Health check %s failed", check.name)
                results.append(HealthCheckResult(
                    check_name=check.name,
                    severity=Severity.WARNING,
                    title=f"Health check '{check.name}' failed to run",
                    details="An internal error occurred. Check logs for details.",
                    finding_key=f"{check.name}:error",
                ))

        status = self._compute_status(results)
        self._cache = _CachedResults(
            results=results,
            timestamp=time.monotonic(),
            status=status,
        )
        return results

    def get_status_summary(self) -> HealthStatus:
        """Get lightweight status summary (runs checks if cache expired).

        Returns:
            HealthStatus with overall severity and counts.
        """
        if self._cache and (time.monotonic() - self._cache.timestamp) < CACHE_TTL_SECONDS:
            return self._cache.status

        self.run_all_checks()
        assert self._cache is not None
        return self._cache.status

    def get_findings(self) -> list[HealthCheckResult]:
        """Get only non-healthy findings.

        Returns:
            List of warning and critical findings.
        """
        results = self.run_all_checks()
        return [r for r in results if r.severity != Severity.HEALTHY]

    def _compute_status(self, results: list[HealthCheckResult]) -> HealthStatus:
        """Compute overall status from check results."""
        findings = [r for r in results if r.severity != Severity.HEALTHY]
        has_critical = any(r.severity == Severity.CRITICAL for r in findings)

        if has_critical:
            overall = Severity.CRITICAL
        elif findings:
            overall = Severity.WARNING
        else:
            overall = Severity.HEALTHY

        return HealthStatus(
            overall_severity=overall,
            finding_count=len(findings),
            unacknowledged_count=len(findings),  # Updated by caller with anti-nag data
        )
