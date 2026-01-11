"""RIVA Performance Optimization modules.

This package contains optimization strategies to improve RIVA's performance
while maintaining verification quality. The core philosophy:

    "ChatGPT optimizes for speed. RIVA optimizes for correctness."

We accept being 3x slower in exchange for more rigorous verification.
These optimizations reduce unnecessary overhead, not verification rigor.

Quick Start
-----------
    from reos.code_mode.optimization import create_optimized_context

    # Create WorkContext with all optimizations enabled
    ctx = create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        session_id="my-session",
    )

    # Work with RIVA as normal - optimizations happen automatically
    result = work(intention, ctx)

    # Check optimization status
    from reos.code_mode.optimization import create_status
    status = create_status(ctx)
    print(status.summary())

Factory Functions
-----------------
    create_optimized_context   Full optimization (metrics + trust + batching)
    create_minimal_context     No optimizations (for testing)
    create_metrics_only_context  Just metrics collection
    create_high_trust_context  Speed-optimized with high initial trust
    create_paranoid_context    Maximum verification (verify everything)

Data Flow
---------
    action → assess_risk() → trust_budget.should_verify()
                                  ↓
                        [HIGH or low trust] → immediate verify
                        [LOW/MED + high trust] → defer to batcher
                                  ↓
                        intention verified → batcher.flush()
                                  ↓
                        [batch success] → done
                        [batch failure] → revert, deplete trust

Modules
-------
    metrics         Execution metrics collection and analysis
    complexity      Task complexity analysis for smart decomposition
    risk            Action risk classification (HIGH/MEDIUM/LOW)
    trust           Session-level trust budget management
    verification    Batch verification for reduced LLM calls
    pattern_success Pattern success tracking for learned trust (scaffolded)
    fast_path       Optimized handlers for common patterns (scaffolded)
    model_selector  Task-appropriate model selection (scaffolded)
    status          Unified status reporting for observability
    factory         Convenience functions for WorkContext creation

All optimizations are opt-in and can be enabled/disabled via config.
When in doubt, we fall back to full verification.
"""

from reos.code_mode.optimization.metrics import (
    ExecutionMetrics,
    MetricsStore,
    create_metrics,
)
from reos.code_mode.optimization.complexity import (
    TaskComplexity,
    analyze_complexity,
)
from reos.code_mode.optimization.risk import (
    RiskLevel,
    ActionRisk,
    assess_risk,
)
from reos.code_mode.optimization.trust import TrustBudget
from reos.code_mode.optimization.pattern_success import PatternSuccessTracker
from reos.code_mode.optimization.verification import VerificationBatcher
from reos.code_mode.optimization.fast_path import (
    FastPathPattern,
    detect_pattern,
    execute_fast_path,
)
from reos.code_mode.optimization.model_selector import (
    ModelTier,
    ModelSelection,
    select_model,
)
from reos.code_mode.optimization.status import (
    OptimizationStatus,
    create_status,
)
from reos.code_mode.optimization.factory import (
    create_optimized_context,
    create_minimal_context,
    create_metrics_only_context,
    create_high_trust_context,
    create_paranoid_context,
)

__all__ = [
    # Metrics
    "ExecutionMetrics",
    "MetricsStore",
    "create_metrics",
    # Complexity
    "TaskComplexity",
    "analyze_complexity",
    # Risk
    "RiskLevel",
    "ActionRisk",
    "assess_risk",
    # Trust
    "TrustBudget",
    # Pattern Success
    "PatternSuccessTracker",
    # Verification
    "VerificationBatcher",
    # Fast Path
    "FastPathPattern",
    "detect_pattern",
    "execute_fast_path",
    # Model Selection
    "ModelTier",
    "ModelSelection",
    "select_model",
    # Status
    "OptimizationStatus",
    "create_status",
    # Factory
    "create_optimized_context",
    "create_minimal_context",
    "create_metrics_only_context",
    "create_high_trust_context",
    "create_paranoid_context",
]
