"""RIVA Performance Optimization modules.

This package contains optimization strategies to improve RIVA's performance
while maintaining verification quality. The core philosophy:

    "ChatGPT optimizes for speed. RIVA optimizes for correctness."

We accept being 3x slower in exchange for more rigorous verification.
These optimizations reduce unnecessary overhead, not verification rigor.

Modules:
    metrics: Execution metrics collection and analysis
    complexity: Task complexity analysis for smart decomposition
    risk: Action risk classification for confidence-based verification
    trust: Session-level trust budget management
    pattern_success: Pattern success tracking for learned trust
    verification: Batch verification for reduced LLM calls
    fast_path: Optimized handlers for common patterns
    model_selector: Task-appropriate model selection

Usage:
    from reos.code_mode.optimization import (
        ExecutionMetrics,
        TaskComplexity,
        analyze_complexity,
        ActionRisk,
        assess_risk,
        TrustBudget,
    )

All optimizations are opt-in and can be enabled/disabled via config.
When in doubt, we fall back to full verification.
"""

from reos.code_mode.optimization.metrics import ExecutionMetrics
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

__all__ = [
    # Metrics
    "ExecutionMetrics",
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
]
