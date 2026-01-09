"""Centralized configuration constants for ReOS.

This module provides a single source of truth for:
- Security limits (rate limits, command length, sudo escalations)
- Timeouts (command execution, API calls)
- Execution budgets (iterations, operations)
- Context and token limits
- Output truncation limits

Constants can be overridden via environment variables where noted.
Security-critical values have hard minimums that cannot be bypassed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import NamedTuple


# =============================================================================
# Helper functions
# =============================================================================


def _env_int(name: str, default: int, min_val: int | None = None) -> int:
    """Get integer from environment with optional minimum enforcement."""
    val = int(os.environ.get(name, str(default)))
    if min_val is not None and val < min_val:
        return min_val
    return val


# =============================================================================
# Security Limits
# =============================================================================


@dataclass(frozen=True)
class SecurityLimits:
    """Hard limits for security-critical operations.

    These limits cannot be disabled, only tuned within safe ranges.
    """

    # Input validation limits
    MAX_SERVICE_NAME_LEN: int = 256
    MAX_CONTAINER_ID_LEN: int = 256
    MAX_PACKAGE_NAME_LEN: int = 256
    MAX_COMMAND_LEN: int = _env_int("REOS_MAX_COMMAND_LEN", 4096, min_val=1024)

    # Sudo escalation limit (per session)
    MAX_SUDO_ESCALATIONS: int = _env_int("REOS_MAX_SUDO_ESCALATIONS", 3, min_val=1)

    # Output truncation (prevent memory exhaustion)
    MAX_COMMAND_OUTPUT: int = 10000
    MAX_STDERR_OUTPUT: int = 5000
    MAX_SERVICE_STATUS_OUTPUT: int = 2000


SECURITY = SecurityLimits()


# =============================================================================
# Rate Limiting
# =============================================================================


class RateLimitConfig(NamedTuple):
    """Configuration for a rate limit bucket."""
    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimits:
    """Rate limits for different operation categories.

    Format: (max_requests, window_seconds)
    """

    AUTH: RateLimitConfig = RateLimitConfig(5, 60)
    SUDO: RateLimitConfig = RateLimitConfig(10, 60)
    SERVICE: RateLimitConfig = RateLimitConfig(20, 60)
    CONTAINER: RateLimitConfig = RateLimitConfig(30, 60)
    PACKAGE: RateLimitConfig = RateLimitConfig(5, 300)  # Longer window for package ops
    APPROVAL: RateLimitConfig = RateLimitConfig(20, 60)


RATE_LIMITS = RateLimits()


# =============================================================================
# Timeouts (in seconds)
# =============================================================================


@dataclass(frozen=True)
class Timeouts:
    """Timeout values for various operations.

    Organized by operation type for easy reference.
    """

    # Quick operations (system info, checks)
    QUICK: int = 5  # hostname, kernel, docker check, network

    # Standard operations (process listing, basic commands)
    STANDARD: int = 10  # ps, basic file ops

    # Service operations (systemctl, package search)
    SERVICE: int = 30  # systemctl, search, verification

    # Container operations
    CONTAINER_EXEC: int = 60

    # Package management (install/remove)
    PACKAGE_INSTALL: int = 300  # 5 minutes

    # Code execution wall-clock limit
    CODE_EXECUTION: int = _env_int("REOS_CODE_EXECUTION_TIMEOUT", 300, min_val=60)

    # Session idle timeout
    SESSION_IDLE: int = 900  # 15 minutes

    # API/LLM timeouts
    LLM_DEFAULT: float = 60.0
    OLLAMA_CHECK: float = 5.0
    OLLAMA_MODELS: float = 2.0
    HTTP_REQUEST: float = 10.0


TIMEOUTS = Timeouts()


# =============================================================================
# Execution Budgets
# =============================================================================


@dataclass(frozen=True)
class ExecutionBudgets:
    """Limits for code execution and operations.

    These prevent runaway execution and resource exhaustion.
    """

    # Code mode iteration limits
    MAX_ITERATIONS: int = _env_int("REOS_MAX_ITERATIONS", 10, min_val=3)

    # Total operations per execution
    MAX_TOTAL_OPERATIONS: int = 25

    # Privilege escalations per execution
    MAX_PRIVILEGE_ESCALATIONS: int = 3

    # Steps that can be injected during execution
    MAX_INJECTED_STEPS: int = 5

    # Recoveries before requiring human checkpoint
    HUMAN_CHECKPOINT_AFTER_RECOVERIES: int = 2

    # Memory growth limits
    MAX_LEARNED_PATTERNS: int = 1000
    MAX_ROLLBACK_HISTORY_HOURS: int = 24


EXECUTION = ExecutionBudgets()


# =============================================================================
# Context and Token Limits
# =============================================================================


@dataclass(frozen=True)
class ContextLimits:
    """Token and context budget limits."""

    # Context window sizes
    SMALL: int = 4096
    MEDIUM: int = 8192  # Default
    LARGE: int = 32768
    XLARGE: int = 131072

    # Reserved tokens for system use
    RESERVED_TOKENS: int = 2048

    # Default token budget for operations
    DEFAULT_TOKEN_BUDGET: int = 800

    # Codebase indexing budget
    CODEBASE_INDEX_TOKENS: int = 5500

    # Context warning thresholds (percentage)
    CRITICAL_THRESHOLD: float = 0.90
    WARNING_THRESHOLD: float = 0.75


CONTEXT = ContextLimits()


# =============================================================================
# Stale Data Thresholds
# =============================================================================


@dataclass(frozen=True)
class StaleThresholds:
    """Time thresholds for considering data stale (in seconds)."""

    # General data staleness
    DATA_STALE: int = 300  # 5 minutes

    # System state staleness
    SYSTEM_STATE_STALE: int = 3600  # 1 hour


STALE = StaleThresholds()


# =============================================================================
# Query and Result Limits
# =============================================================================


@dataclass(frozen=True)
class QueryLimits:
    """Limits for query results and listings."""

    # Default list limits
    DEFAULT_LIST_LIMIT: int = 20
    DEFAULT_LOG_LINES: int = 100

    # Maximum results
    MAX_GLOB_RESULTS: int = 50
    MAX_DIRECTORY_ENTRIES: int = 200
    MAX_INSTALLED_PACKAGES: int = 500
    MAX_SEARCH_RESULTS: int = 5


QUERY = QueryLimits()


# =============================================================================
# Web Tools Configuration
# =============================================================================


@dataclass(frozen=True)
class WebToolsConfig:
    """Configuration for web-based tools."""

    MAX_CONTENT_LENGTH: int = 15000
    MAX_SEARCH_RESULTS: int = 5
    DEFAULT_TIMEOUT: float = 10.0


WEB_TOOLS = WebToolsConfig()


# =============================================================================
# Model Defaults
# =============================================================================


@dataclass(frozen=True)
class ModelDefaults:
    """Default model configurations."""

    # Anthropic default model
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Default temperature for code operations
    CODE_TEMPERATURE: float = 0.3

    # Default temperature for chat
    CHAT_TEMPERATURE: float = 0.7

    # Tool call limits per agent type
    TOOL_CALLS_RIVA: int = 8
    TOOL_CALLS_DEFAULT: int = 5


MODELS = ModelDefaults()


# =============================================================================
# Agent and Handoff Limits
# =============================================================================


@dataclass(frozen=True)
class AgentLimits:
    """Limits for agent operations."""

    MAX_TOOLS_PER_AGENT: int = 15
    MAX_CORE_TOOLS: int = 12


AGENTS = AgentLimits()
