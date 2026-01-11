"""Factory functions for creating optimized WorkContext.

This module provides convenient factory functions to create WorkContext
instances with optimization components pre-configured.

Usage:
    from reos.code_mode.optimization.factory import create_optimized_context

    ctx = create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_id="my-session",
    )

    # ctx now has metrics, trust_budget, and verification_batcher configured
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from reos.code_mode.optimization.metrics import create_metrics
from reos.code_mode.optimization.trust import create_trust_budget
from reos.code_mode.optimization.verification import VerificationBatcher
from reos.code_mode.optimization.pattern_success import PatternSuccessTracker

if TYPE_CHECKING:
    from reos.code_mode.intention import WorkContext
    from reos.code_mode.sandbox import CodeSandbox
    from reos.code_mode.session_logger import SessionLogger
    from reos.code_mode.quality import QualityTracker
    from reos.code_mode.tools import ToolProvider
    from reos.providers import LLMProvider
    from reos.db import Database


def create_optimized_context(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,  # HumanCheckpoint | AutoCheckpoint
    *,
    session_id: str | None = None,
    session_logger: "SessionLogger | None" = None,
    quality_tracker: "QualityTracker | None" = None,
    tool_provider: "ToolProvider | None" = None,
    # Pattern success tracking
    db: "Database | None" = None,
    repo_path: str | None = None,
    # Project memory (for fair context provision)
    project_memory: Any = None,  # ProjectMemoryStore | None
    # Optimization settings
    enable_metrics: bool = True,
    enable_trust_budget: bool = True,
    enable_verification_batcher: bool = True,
    enable_pattern_success: bool = True,
    # Trust budget tuning
    initial_trust: int = 100,
    trust_floor: int = 20,
    # Context limits
    max_cycles_per_intention: int = 5,
    max_depth: int = 10,
    # Callbacks
    on_intention_start: Any = None,
    on_intention_complete: Any = None,
    on_cycle_complete: Any = None,
    on_decomposition: Any = None,
) -> "WorkContext":
    """Create a WorkContext with optimization components configured.

    This is the recommended way to create a WorkContext when you want
    RIVA's performance optimizations enabled.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for generation
        checkpoint: Human or auto checkpoint for verification

        session_id: Unique session identifier (auto-generated if None)
        session_logger: Optional session logger
        quality_tracker: Optional quality tracker
        tool_provider: Optional tool provider

        db: Database connection for pattern success tracking (optional)
        repo_path: Repository path for pattern success tracking (optional)
        project_memory: ProjectMemoryStore for providing repo context (optional)

        enable_metrics: Enable execution metrics collection
        enable_trust_budget: Enable trust budget for verification decisions
        enable_verification_batcher: Enable batch verification
        enable_pattern_success: Enable pattern success tracking (requires db and repo_path)

        initial_trust: Starting trust level (default 100)
        trust_floor: Minimum trust level (default 20)

        max_cycles_per_intention: Max action cycles per intention
        max_depth: Max recursion depth for decomposition

        on_intention_start: Callback when intention starts
        on_intention_complete: Callback when intention completes
        on_cycle_complete: Callback when cycle completes
        on_decomposition: Callback when decomposition occurs

    Returns:
        Configured WorkContext with optimization components
    """
    from reos.code_mode.intention import WorkContext

    # Generate session ID if not provided
    if session_id is None:
        session_id = str(uuid.uuid4())[:8]

    # Create optimization components
    metrics = create_metrics(session_id) if enable_metrics else None
    trust_budget = (
        create_trust_budget(initial=initial_trust, floor=trust_floor)
        if enable_trust_budget
        else None
    )
    verification_batcher = (
        VerificationBatcher(llm=llm)
        if enable_verification_batcher
        else None
    )
    pattern_success_tracker = (
        PatternSuccessTracker(db=db, repo_path=repo_path)
        if enable_pattern_success and db and repo_path
        else None
    )

    return WorkContext(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_logger=session_logger,
        quality_tracker=quality_tracker,
        tool_provider=tool_provider,
        metrics=metrics,
        trust_budget=trust_budget,
        verification_batcher=verification_batcher,
        pattern_success_tracker=pattern_success_tracker,
        project_memory=project_memory,
        max_cycles_per_intention=max_cycles_per_intention,
        max_depth=max_depth,
        on_intention_start=on_intention_start,
        on_intention_complete=on_intention_complete,
        on_cycle_complete=on_cycle_complete,
        on_decomposition=on_decomposition,
    )


def create_minimal_context(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,
    *,
    session_logger: "SessionLogger | None" = None,
) -> "WorkContext":
    """Create a minimal WorkContext without optimizations.

    Use this when you want the simplest possible configuration,
    such as for testing or debugging.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for generation
        checkpoint: Human or auto checkpoint

        session_logger: Optional session logger

    Returns:
        Basic WorkContext without optimization components
    """
    from reos.code_mode.intention import WorkContext

    return WorkContext(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_logger=session_logger,
    )


def create_metrics_only_context(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,
    *,
    session_id: str | None = None,
    session_logger: "SessionLogger | None" = None,
) -> "WorkContext":
    """Create WorkContext with only metrics enabled.

    Use this when you want to collect metrics without
    changing verification behavior.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for generation
        checkpoint: Human or auto checkpoint

        session_id: Session identifier
        session_logger: Optional session logger

    Returns:
        WorkContext with metrics only
    """
    return create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_id=session_id,
        session_logger=session_logger,
        enable_metrics=True,
        enable_trust_budget=False,
        enable_verification_batcher=False,
    )


def create_high_trust_context(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,
    *,
    session_id: str | None = None,
    session_logger: "SessionLogger | None" = None,
) -> "WorkContext":
    """Create WorkContext optimized for speed with high initial trust.

    Use this for well-tested codebases where you're confident
    most actions will succeed.

    Warning: This may miss some failures. Use for development,
    not production.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for generation
        checkpoint: Human or auto checkpoint

        session_id: Session identifier
        session_logger: Optional session logger

    Returns:
        WorkContext with high initial trust
    """
    return create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_id=session_id,
        session_logger=session_logger,
        initial_trust=100,
        trust_floor=10,  # Lower floor allows more skipping
    )


def create_paranoid_context(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,
    *,
    session_id: str | None = None,
    session_logger: "SessionLogger | None" = None,
) -> "WorkContext":
    """Create WorkContext that verifies everything.

    Use this for critical operations where you want
    maximum verification regardless of performance cost.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for generation
        checkpoint: Human or auto checkpoint

        session_id: Session identifier
        session_logger: Optional session logger

    Returns:
        WorkContext with paranoid verification settings
    """
    return create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_id=session_id,
        session_logger=session_logger,
        enable_metrics=True,
        enable_trust_budget=True,
        enable_verification_batcher=False,  # No batching
        initial_trust=20,  # Start at floor - verify everything
        trust_floor=20,
    )
