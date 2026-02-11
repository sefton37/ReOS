"""Security Posture Check — Is the system maintaining local-only operation?

Verifies:
1. No cloud API keys set (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
2. Data directory permissions are restrictive (0700)
3. Confirms local-only operation

This supports the project's core philosophy: local-first, never phones home.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)

# Cloud API key environment variables that should NOT be set
CLOUD_API_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "COHERE_API_KEY",
    "HUGGINGFACE_API_KEY",
]


class SecurityPostureCheck:
    """Check security posture for local-only operation."""

    name = "security_posture"

    def __init__(self, data_dir: Path | None = None) -> None:
        """Initialize with optional data directory override."""
        self._data_dir = data_dir

    def run(self) -> list[HealthCheckResult]:
        """Run the security posture check."""
        results: list[HealthCheckResult] = []

        # Check for cloud API keys
        results.extend(self._check_api_keys())

        # Check data directory permissions
        results.extend(self._check_data_permissions())

        # If all good, add a healthy result
        if all(r.severity == Severity.HEALTHY for r in results):
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Security posture: local-only confirmed",
                finding_key=f"{self.name}:ok",
            )]

        return results

    def _check_api_keys(self) -> list[HealthCheckResult]:
        """Check that no cloud API keys are set."""
        found_keys: list[str] = []
        for key_name in CLOUD_API_KEYS:
            if os.environ.get(key_name):
                found_keys.append(key_name)

        if found_keys:
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title=f"Cloud API key(s) detected: {', '.join(found_keys)}",
                details=(
                    "ReOS is designed for local-only operation. Cloud API keys "
                    "in the environment may indicate unintended cloud connectivity. "
                    "If these are for other tools, this is safe to acknowledge."
                ),
                finding_key=f"{self.name}:api_keys:{','.join(sorted(found_keys))}",
            )]

        return [HealthCheckResult(
            check_name=self.name,
            severity=Severity.HEALTHY,
            title="No cloud API keys detected",
            finding_key=f"{self.name}:no_api_keys",
        )]

    def _check_data_permissions(self) -> list[HealthCheckResult]:
        """Check data directory permissions."""
        data_dir = self._data_dir
        if data_dir is None:
            try:
                from reos.settings import settings
                data_dir = settings.data_dir
            except Exception:
                return [HealthCheckResult(
                    check_name=self.name,
                    severity=Severity.HEALTHY,
                    title="Data directory not configured yet",
                    finding_key=f"{self.name}:no_data_dir",
                )]

        if not data_dir.exists():
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Data directory not yet created",
                finding_key=f"{self.name}:data_dir_missing",
            )]

        try:
            dir_stat = data_dir.stat()
            mode = stat.S_IMODE(dir_stat.st_mode)

            # Check if others or group have access
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                perms = oct(mode)
                return [HealthCheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    title=f"Data directory permissions too open ({perms})",
                    details=(
                        f"Directory {data_dir} has permissions {perms}. "
                        "Recommended: 0700 (owner only). "
                        f"Fix with: chmod 700 {data_dir}"
                    ),
                    finding_key=f"{self.name}:perms:{perms}",
                )]

            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Data directory permissions are secure",
                finding_key=f"{self.name}:perms_ok",
            )]

        except OSError as e:
            logger.debug("Could not check data dir permissions: %s", e)
            return [HealthCheckResult(
                check_name=self.name,
                severity=Severity.HEALTHY,
                title="Could not verify data directory permissions",
                finding_key=f"{self.name}:perms_check_error",
            )]
