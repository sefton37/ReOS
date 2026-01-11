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

import asyncio
import logging
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
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


async def analyze_repo_and_populate_memory(
    act: "Act",
    llm: "LLMProvider",
    project_memory: Any,  # ProjectMemoryStore
) -> None:
    """Analyze repository and populate ProjectMemory with findings.

    Uses ActRepoAnalyzer to discover:
    - Structure (components, entry points, test strategy)
    - Conventions (naming, imports, docstrings)
    - Types (data models with field types)

    Then converts analysis into ProjectMemory decisions and patterns.

    Args:
        act: The Act (project) to analyze
        llm: Local LLM provider (Ollama) for cheap analysis
        project_memory: ProjectMemoryStore to populate

    Cost: ~$0.0011 per analysis with local LLM (vs $0.33 with GPT-4)
    """
    try:
        from reos.code_mode.repo_analyzer import ActRepoAnalyzer

        # Create analyzer
        analyzer = ActRepoAnalyzer(act=act, llm=llm)

        # Run analysis (cached if recent)
        logger.info("Running repo analysis for %s", act.title)
        context = await analyzer.analyze_if_needed()

        # Convert structure analysis to ProjectMemory decisions
        if context.structure:
            struct = context.structure

            # Record test strategy decision
            if struct.test_strategy:
                await asyncio.to_thread(
                    project_memory.record_decision,
                    decision=f"Test strategy: {struct.test_strategy}",
                    rationale="Discovered from repository analysis",
                    confidence=0.9,
                )

            # Record documentation location
            if struct.docs_location:
                await asyncio.to_thread(
                    project_memory.record_decision,
                    decision=f"Documentation: {struct.docs_location}",
                    rationale="Discovered from repository analysis",
                    confidence=0.9,
                )

            # Record component structure as patterns
            for comp in struct.components[:5]:  # Top 5 components
                pattern_desc = f"Component '{comp['name']}': {comp['purpose']}"
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="structure",
                    description=pattern_desc,
                    example=f"Located at: {comp['path']}",
                    confidence=0.8,
                )

        # Convert convention analysis to ProjectMemory patterns
        if context.conventions:
            conv = context.conventions

            # Import style pattern
            if conv.import_style:
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="import",
                    description=f"Import style: {conv.import_style}",
                    example=conv.examples.get("import", ""),
                    confidence=0.9,
                )

            # Class naming pattern
            if conv.class_naming:
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="naming",
                    description=f"Class naming: {conv.class_naming}",
                    example=conv.examples.get("class", ""),
                    confidence=0.9,
                )

            # Function naming pattern
            if conv.function_naming:
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="naming",
                    description=f"Function naming: {conv.function_naming}",
                    example=conv.examples.get("function", ""),
                    confidence=0.9,
                )

            # Type hints pattern
            if conv.type_hints_usage:
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="style",
                    description=f"Type hints: {conv.type_hints_usage}",
                    example=conv.examples.get("function", ""),
                    confidence=0.9,
                )

            # Docstring style pattern
            if conv.docstring_style:
                await asyncio.to_thread(
                    project_memory.record_pattern,
                    pattern_type="documentation",
                    description=f"Docstring style: {conv.docstring_style}",
                    example=conv.examples.get("docstring", ""),
                    confidence=0.9,
                )

        # Convert type analysis to ProjectMemory patterns
        if context.types:
            types = context.types

            # Record key data models
            for model in types.data_models[:10]:  # Top 10 data models
                fields_desc = ", ".join(
                    f"{name}: {typ}"
                    for name, typ in model.get("key_fields", {}).items()
                )
                if fields_desc:
                    pattern_desc = f"{model['name']} fields: {fields_desc}"
                    await asyncio.to_thread(
                        project_memory.record_pattern,
                        pattern_type="types",
                        description=pattern_desc,
                        example=f"File: {model.get('file', 'unknown')}",
                        confidence=0.8,
                    )

        logger.info("Repo analysis complete and injected into ProjectMemory")

    except Exception as e:
        # Don't fail session creation if analysis fails
        logger.warning("Repo analysis failed, continuing without it: %s", e)


async def create_optimized_context_with_repo_analysis(
    sandbox: "CodeSandbox",
    llm: "LLMProvider | None",
    checkpoint: Any,
    *,
    act: "Act",
    local_llm: "LLMProvider",
    project_memory: Any,  # ProjectMemoryStore (required for this function)
    enable_repo_analysis: bool = True,
    **kwargs: Any,
) -> "WorkContext":
    """Create WorkContext with automatic repo analysis and ProjectMemory population.

    This is an async wrapper around create_optimized_context that:
    1. Runs ActRepoAnalyzer to discover repo structure, conventions, types
    2. Converts analysis into ProjectMemory decisions and patterns
    3. Creates WorkContext with populated ProjectMemory

    Use this when starting a Code Mode session to ensure models have comprehensive
    repo context for fair evaluation.

    Args:
        sandbox: Code sandbox for execution
        llm: LLM provider for code generation
        checkpoint: Human or auto checkpoint

        act: The Act (project) being worked on
        local_llm: Local LLM provider (Ollama) for cheap repo analysis
        project_memory: ProjectMemoryStore to populate with analysis
        enable_repo_analysis: Whether to run repo analysis (default True)
        **kwargs: Additional arguments passed to create_optimized_context

    Returns:
        Configured WorkContext with repo analysis injected into ProjectMemory

    Cost: ~$0.0011 for repo analysis with local LLM (vs $0.33 with GPT-4)
    """
    # Run repo analysis and populate ProjectMemory
    if enable_repo_analysis and act and local_llm and project_memory:
        await analyze_repo_and_populate_memory(
            act=act,
            llm=local_llm,
            project_memory=project_memory,
        )

    # Create WorkContext with populated ProjectMemory
    return create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        project_memory=project_memory,
        **kwargs,
    )


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
