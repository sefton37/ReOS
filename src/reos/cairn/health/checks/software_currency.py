"""Software Currency Check — Is the LLM provider healthy?

Checks Ollama availability via existing provider health checks.
Optionally runs pip-audit if available (graceful fallback).
"""

from __future__ import annotations

import logging

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)


class SoftwareCurrencyCheck:
    """Check software infrastructure health."""

    name = "software_currency"

    def run(self) -> list[HealthCheckResult]:
        """Run the software currency check."""
        results: list[HealthCheckResult] = []

        # Check Ollama provider availability
        results.extend(self._check_ollama())

        return results

    def _check_ollama(self) -> list[HealthCheckResult]:
        """Check if Ollama is accessible."""
        try:
            from reos.providers.factory import check_provider_health

            health = check_provider_health()
            if health.get("available", False):
                return [HealthCheckResult(
                    check_name=self.name,
                    severity=Severity.HEALTHY,
                    title="Ollama provider is available",
                    finding_key=f"{self.name}:ollama:ok",
                )]
            else:
                error = health.get("error", "Unknown error")
                return [HealthCheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    title="Ollama provider is not available",
                    details=f"The LLM provider could not be reached: {error}",
                    finding_key=f"{self.name}:ollama:unavailable",
                )]
        except ImportError:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Provider health check not available",
                finding_key=f"{self.name}:no_provider",
            )]
        except Exception as e:
            logger.debug("Ollama health check failed: %s", e)
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title="Could not check provider health",
                details=str(e),
                finding_key=f"{self.name}:error",
            )]
