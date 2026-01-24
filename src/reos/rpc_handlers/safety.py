"""Safety and security settings RPC handlers.

These handlers manage rate limits, sudo escalation limits,
command length limits, and other safety parameters.
"""

from __future__ import annotations

from typing import Any

from reos.db import Database
from reos.security import (
    get_rate_limiter,
    DANGEROUS_PATTERNS,
    INJECTION_PATTERNS,
    MAX_COMMAND_LEN,
    MAX_SERVICE_NAME_LEN,
    MAX_CONTAINER_ID_LEN,
    MAX_PACKAGE_NAME_LEN,
)


# =============================================================================
# Safety Settings Handlers
# =============================================================================


def handle_safety_settings(_db: Database) -> dict[str, Any]:
    """Get current safety settings and limits."""
    from reos import linux_tools
    from reos.code_mode import executor as code_executor

    rate_limiter = get_rate_limiter()
    sudo_count, sudo_max = linux_tools.get_sudo_escalation_status()

    # Build rate limits dict
    rate_limits = {}
    for category, config in rate_limiter._limits.items():
        rate_limits[category] = {
            "max_requests": config.max_requests,
            "window_seconds": config.window_seconds,
            "name": config.name,
        }

    return {
        "rate_limits": rate_limits,
        "max_sudo_escalations": sudo_max,
        "current_sudo_count": sudo_count,
        "max_command_length": MAX_COMMAND_LEN,
        "max_iterations": code_executor.ExecutionState.max_iterations,
        "wall_clock_timeout_seconds": code_executor.DEFAULT_WALL_CLOCK_TIMEOUT_SECONDS,
        "max_service_name_length": MAX_SERVICE_NAME_LEN,
        "max_container_id_length": MAX_CONTAINER_ID_LEN,
        "max_package_name_length": MAX_PACKAGE_NAME_LEN,
        "dangerous_pattern_count": len(DANGEROUS_PATTERNS),
        "injection_pattern_count": len(INJECTION_PATTERNS),
    }


def handle_safety_set_rate_limit(
    _db: Database,
    *,
    category: str,
    max_requests: int,
    window_seconds: float,
) -> dict[str, Any]:
    """Update a rate limit configuration."""
    rate_limiter = get_rate_limiter()

    # Validate bounds
    if max_requests < 1:
        max_requests = 1
    if max_requests > 100:
        max_requests = 100
    if window_seconds < 10:
        window_seconds = 10
    if window_seconds > 600:
        window_seconds = 600

    rate_limiter.configure(category, max_requests, window_seconds)

    return {
        "success": True,
        "category": category,
        "max_requests": max_requests,
        "window_seconds": window_seconds,
    }


def handle_safety_set_sudo_limit(
    db: Database,
    *,
    max_escalations: int,
) -> dict[str, Any]:
    """Update the sudo escalation limit."""
    from reos import linux_tools

    # Validate bounds (1-20)
    if max_escalations < 1:
        max_escalations = 1
    if max_escalations > 20:
        max_escalations = 20

    # Update the module-level constant
    linux_tools._MAX_SUDO_ESCALATIONS = max_escalations

    # Persist to database
    db.set_state(key="safety_sudo_limit", value=str(max_escalations))

    return {
        "success": True,
        "max_escalations": max_escalations,
    }


def handle_safety_set_command_length(
    db: Database,
    *,
    max_length: int,
) -> dict[str, Any]:
    """Update the maximum command length."""
    from reos import security

    # Validate bounds (512-32768)
    if max_length < 512:
        max_length = 512
    if max_length > 32768:
        max_length = 32768

    # Update the module-level constant
    security.MAX_COMMAND_LEN = max_length

    # Persist to database
    db.set_state(key="safety_command_length", value=str(max_length))

    return {
        "success": True,
        "max_length": max_length,
    }


def handle_safety_set_max_iterations(
    db: Database,
    *,
    max_iterations: int,
) -> dict[str, Any]:
    """Update the maximum iterations for agent execution."""
    from reos.code_mode import executor as code_executor

    # Validate bounds (3-100)
    if max_iterations < 3:
        max_iterations = 3
    if max_iterations > 100:
        max_iterations = 100

    # Update the dataclass default
    code_executor.ExecutionState.max_iterations = max_iterations

    # Persist to database
    db.set_state(key="safety_max_iterations", value=str(max_iterations))

    return {
        "success": True,
        "max_iterations": max_iterations,
    }


def handle_safety_set_wall_clock_timeout(
    db: Database,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Update the wall-clock timeout for agent execution."""
    from reos.code_mode import executor as code_executor

    # Validate bounds (60s - 3600s / 1 hour max)
    if timeout_seconds < 60:
        timeout_seconds = 60
    if timeout_seconds > 3600:
        timeout_seconds = 3600

    # Update the module-level constant
    code_executor.DEFAULT_WALL_CLOCK_TIMEOUT_SECONDS = timeout_seconds

    # Persist to database
    db.set_state(key="safety_wall_clock_timeout", value=str(timeout_seconds))

    return {
        "success": True,
        "timeout_seconds": timeout_seconds,
    }
