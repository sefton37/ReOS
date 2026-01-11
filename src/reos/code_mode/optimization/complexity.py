"""Task complexity analysis for smart decomposition decisions.

This module analyzes task complexity to decide whether decomposition
is needed. The goal is to avoid over-decomposing simple tasks.

Simple, well-defined tasks should execute directly.
Complex, ambiguous tasks should decompose.

We err on the side of decomposition when uncertain.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ComplexityLevel(Enum):
    """Task complexity levels."""

    TRIVIAL = "trivial"  # Single line change, obvious
    SIMPLE = "simple"  # One function, clear spec
    MODERATE = "moderate"  # Multiple functions, some ambiguity
    COMPLEX = "complex"  # Multiple files, significant ambiguity
    VERY_COMPLEX = "very_complex"  # Architectural, high uncertainty


@dataclass
class TaskComplexity:
    """Analysis of task complexity.

    Used to decide whether to decompose or execute directly.
    """

    level: ComplexityLevel
    score: float  # 0.0 (trivial) to 1.0 (very complex)

    # Contributing factors
    estimated_files: int
    estimated_functions: int
    has_external_deps: bool
    requires_tests: bool
    modifies_existing: bool
    scope_ambiguous: bool
    has_compound_structure: bool

    # Decision
    should_decompose: bool
    confidence: float  # How confident are we in this analysis?
    reason: str

    def to_dict(self) -> dict:
        """Serialize for logging."""
        return {
            "level": self.level.value,
            "score": self.score,
            "factors": {
                "estimated_files": self.estimated_files,
                "estimated_functions": self.estimated_functions,
                "has_external_deps": self.has_external_deps,
                "requires_tests": self.requires_tests,
                "modifies_existing": self.modifies_existing,
                "scope_ambiguous": self.scope_ambiguous,
                "has_compound_structure": self.has_compound_structure,
            },
            "decision": {
                "should_decompose": self.should_decompose,
                "confidence": self.confidence,
                "reason": self.reason,
            },
        }


def analyze_complexity(
    what: str,
    acceptance: str,
    codebase_context: str | None = None,
) -> TaskComplexity:
    """Analyze task complexity to inform decomposition decision.

    Args:
        what: Natural language description of the task
        acceptance: Acceptance criteria
        codebase_context: Optional context about the codebase

    Returns:
        TaskComplexity with analysis and recommendation
    """
    what_lower = what.lower()
    acceptance_lower = acceptance.lower()

    # Analyze contributing factors
    estimated_files = _estimate_files(what_lower)
    estimated_functions = _estimate_functions(what_lower)
    has_external_deps = _detect_external_deps(what_lower)
    requires_tests = _detect_test_requirement(what_lower, acceptance_lower)
    modifies_existing = _detect_modification(what_lower)
    scope_ambiguous = _detect_ambiguity(what_lower, acceptance_lower)
    has_compound = _detect_compound_structure(what_lower)

    # Calculate complexity score (0.0 to 1.0)
    score = 0.0

    # File count impact
    if estimated_files == 1:
        score += 0.1
    elif estimated_files <= 3:
        score += 0.3
    else:
        score += 0.5

    # Function count impact
    if estimated_functions <= 1:
        score += 0.05
    elif estimated_functions <= 3:
        score += 0.15
    else:
        score += 0.25

    # Other factors
    if has_external_deps:
        score += 0.1
    if requires_tests:
        score += 0.05  # Tests are good, slight complexity
    if modifies_existing:
        score += 0.1  # Understanding existing code adds complexity
    if scope_ambiguous:
        score += 0.2  # Ambiguity is significant
    if has_compound:
        score += 0.15  # Compound tasks need decomposition

    # Clamp to [0, 1]
    score = min(1.0, max(0.0, score))

    # Determine level
    if score < 0.2:
        level = ComplexityLevel.TRIVIAL
    elif score < 0.4:
        level = ComplexityLevel.SIMPLE
    elif score < 0.6:
        level = ComplexityLevel.MODERATE
    elif score < 0.8:
        level = ComplexityLevel.COMPLEX
    else:
        level = ComplexityLevel.VERY_COMPLEX

    # Decision: should we decompose?
    # Default: decompose if score > 0.4 (moderate or above)
    # But we can skip decomposition for well-defined simple tasks
    if score < 0.3 and not scope_ambiguous:
        should_decompose = False
        reason = "Simple, well-defined task - execute directly"
        confidence = 0.8
    elif score < 0.4 and not has_compound:
        should_decompose = False
        reason = "Low complexity, no compound structure - execute directly"
        confidence = 0.7
    elif scope_ambiguous:
        should_decompose = True
        reason = "Scope is ambiguous - decompose to clarify"
        confidence = 0.8
    elif has_compound:
        should_decompose = True
        reason = "Compound structure detected - decompose"
        confidence = 0.9
    elif score > 0.6:
        should_decompose = True
        reason = "High complexity score - decompose"
        confidence = 0.7
    else:
        # Moderate complexity: decompose to be safe
        should_decompose = True
        reason = "Moderate complexity - decompose for safety"
        confidence = 0.6

    return TaskComplexity(
        level=level,
        score=score,
        estimated_files=estimated_files,
        estimated_functions=estimated_functions,
        has_external_deps=has_external_deps,
        requires_tests=requires_tests,
        modifies_existing=modifies_existing,
        scope_ambiguous=scope_ambiguous,
        has_compound_structure=has_compound,
        should_decompose=should_decompose,
        confidence=confidence,
        reason=reason,
    )


def _estimate_files(what: str) -> int:
    """Estimate number of files affected."""
    # Explicit mentions
    file_mentions = len(re.findall(r"\b\w+\.(py|ts|js|rs|go)\b", what))
    if file_mentions > 0:
        return file_mentions

    # Keywords suggesting multiple files
    multi_file_keywords = ["across", "multiple", "all", "every", "each file"]
    if any(kw in what for kw in multi_file_keywords):
        return 3  # Assume multiple

    # Keywords suggesting single file
    single_file_keywords = ["function", "method", "class", "add to", "modify"]
    if any(kw in what for kw in single_file_keywords):
        return 1

    return 1  # Default assumption


def _estimate_functions(what: str) -> int:
    """Estimate number of functions to create/modify."""
    # Count function-like mentions
    func_patterns = [
        r"\bfunction\b",
        r"\bmethod\b",
        r"\bendpoint\b",
        r"\bhandler\b",
        r"\bhelper\b",
    ]
    count = sum(len(re.findall(p, what)) for p in func_patterns)

    if count > 0:
        return count

    # If creating a class, assume 2-3 methods
    if "class" in what:
        return 3

    return 1


def _detect_external_deps(what: str) -> bool:
    """Detect if task involves external dependencies."""
    external_keywords = [
        "api",
        "http",
        "request",
        "database",
        "redis",
        "postgres",
        "mysql",
        "mongodb",
        "aws",
        "gcp",
        "azure",
        "docker",
        "kubernetes",
        "install",
        "import",
        "library",
        "package",
    ]
    return any(kw in what for kw in external_keywords)


def _detect_test_requirement(what: str, acceptance: str) -> bool:
    """Detect if task requires tests."""
    test_keywords = ["test", "spec", "verify", "assert", "should pass"]
    return any(kw in what or kw in acceptance for kw in test_keywords)


def _detect_modification(what: str) -> bool:
    """Detect if task modifies existing code."""
    modify_keywords = [
        "modify",
        "update",
        "change",
        "fix",
        "refactor",
        "improve",
        "existing",
        "current",
    ]
    return any(kw in what for kw in modify_keywords)


def _detect_ambiguity(what: str, acceptance: str) -> bool:
    """Detect if scope is ambiguous."""
    # Short description with no specific target
    if len(what.split()) < 5 and not re.search(r"\b\w+\.(py|ts|js)\b", what):
        return True

    # Vague acceptance criteria
    vague_patterns = [
        "works well",
        "looks good",
        "is complete",
        "everything",
        "properly",
        "correctly",
        "as expected",
    ]
    if any(p in acceptance for p in vague_patterns):
        return True

    # Questions in the task
    if "?" in what:
        return True

    return False


def _detect_compound_structure(what: str) -> bool:
    """Detect compound task structure (multiple distinct sub-tasks)."""
    compound_patterns = [
        r"\band\b.*\band\b",  # Multiple "and"s
        r"\bthen\b",  # Sequential steps
        r"\balso\b",
        r"\badditionally\b",
        r"\bplus\b",
        r"\bas well as\b",
        r"\d+\.\s",  # Numbered list
    ]
    return any(re.search(p, what) for p in compound_patterns)
