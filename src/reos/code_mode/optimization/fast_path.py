"""Fast-path handlers for common patterns.

This module provides optimized execution paths for well-known
patterns. 80% of requests are variations on 20% of patterns.
We optimize those common patterns and use full RIVA for edge cases.

Patterns are detected heuristically. When detection fails,
we fall back to full RIVA - no harm done.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from reos.code_mode.intention import Intention, WorkContext

logger = logging.getLogger(__name__)


class FastPathPattern(Enum):
    """Well-known patterns with optimized handlers."""

    # File operations
    CREATE_FILE = "create_file"
    CREATE_FUNCTION = "create_function"
    CREATE_CLASS = "create_class"

    # Modifications
    ADD_IMPORT = "add_import"
    ADD_METHOD = "add_method"
    ADD_DOCSTRING = "add_docstring"

    # Testing
    ADD_TEST = "add_test"
    FIX_TEST = "fix_test"

    # Common fixes
    FIX_TYPO = "fix_typo"
    FIX_IMPORT = "fix_import"
    FIX_INDENT = "fix_indent"


@dataclass
class PatternMatch:
    """Result of pattern detection.

    Attributes:
        pattern: The detected pattern (or None)
        confidence: How confident we are in the match (0-1)
        extracted: Extracted parameters for the handler
    """

    pattern: FastPathPattern | None
    confidence: float
    extracted: dict

    @property
    def is_match(self) -> bool:
        """Is this a confident match?"""
        return self.pattern is not None and self.confidence >= 0.7


# Pattern detection rules
# Each rule is (pattern, keywords, anti-keywords, extractor)
DETECTION_RULES: list[tuple[FastPathPattern, list[str], list[str], Callable]] = [
    # CREATE_FUNCTION: "create a function", "add function", "write function"
    (
        FastPathPattern.CREATE_FUNCTION,
        ["create", "add", "write", "implement"],
        ["class", "test", "file"],
        lambda what: {"func_hint": re.search(r"\b(\w+)\s*\(", what)},
    ),
    # CREATE_CLASS: "create a class", "add class"
    (
        FastPathPattern.CREATE_CLASS,
        ["create", "add", "write"],
        ["function", "test", "method"],
        lambda what: {"class_hint": re.search(r"\bclass\s+(\w+)", what, re.I)},
    ),
    # ADD_TEST: "add test", "write test", "create test"
    (
        FastPathPattern.ADD_TEST,
        ["add", "write", "create"],
        ["fix", "update"],
        lambda what: {"test_hint": re.search(r"test[_\s]?(\w+)", what, re.I)},
    ),
    # FIX_IMPORT: "fix import", "missing import", "add import"
    (
        FastPathPattern.FIX_IMPORT,
        ["fix", "add", "missing"],
        ["test", "class"],
        lambda what: {"import_hint": re.search(r"import\s+(\w+)", what)},
    ),
    # ADD_IMPORT: "add import", "import X"
    (
        FastPathPattern.ADD_IMPORT,
        ["add", "import"],
        ["fix", "remove"],
        lambda what: {"import": re.search(r"import\s+(\w+)", what)},
    ),
    # FIX_TYPO: "fix typo", "typo in"
    (
        FastPathPattern.FIX_TYPO,
        ["fix", "typo", "spelling"],
        ["test", "class"],
        lambda what: {},
    ),
]


def detect_pattern(what: str, acceptance: str = "") -> PatternMatch:
    """Detect if this is a well-known pattern.

    Args:
        what: Task description
        acceptance: Acceptance criteria

    Returns:
        PatternMatch with detected pattern and confidence
    """
    what_lower = what.lower()
    combined = f"{what_lower} {acceptance.lower()}"

    best_match: PatternMatch | None = None
    best_score = 0.0

    for pattern, keywords, anti_keywords, extractor in DETECTION_RULES:
        # Count keyword matches
        keyword_matches = sum(1 for kw in keywords if kw in combined)
        if keyword_matches == 0:
            continue

        # Check for anti-keywords
        anti_matches = sum(1 for akw in anti_keywords if akw in combined)
        if anti_matches > 0:
            continue

        # Calculate confidence
        confidence = min(1.0, keyword_matches * 0.3 + 0.4)

        # Extract parameters
        try:
            extracted = extractor(what) or {}
            # Clean up regex matches
            extracted = {
                k: v.group(1) if hasattr(v, "group") else v
                for k, v in extracted.items()
                if v is not None
            }
        except Exception:
            extracted = {}

        if confidence > best_score:
            best_score = confidence
            best_match = PatternMatch(
                pattern=pattern,
                confidence=confidence,
                extracted=extracted,
            )

    if best_match and best_match.confidence >= 0.7:
        logger.debug(
            "Detected pattern %s with confidence %.2f",
            best_match.pattern.value if best_match.pattern else "none",
            best_match.confidence,
        )
        return best_match

    return PatternMatch(pattern=None, confidence=0.0, extracted={})


def execute_fast_path(
    pattern: FastPathPattern,
    intention: "Intention",
    ctx: "WorkContext",
) -> bool:
    """Execute optimized path for known pattern.

    Args:
        pattern: The detected pattern
        intention: The intention to satisfy
        ctx: Work context with dependencies

    Returns:
        True if handled successfully, False to fall back to full RIVA
    """
    handler = FAST_PATH_HANDLERS.get(pattern)
    if not handler:
        logger.warning("No handler for pattern %s", pattern.value)
        return False

    try:
        logger.info("Executing fast path: %s", pattern.value)
        return handler(intention, ctx)
    except Exception as e:
        logger.warning(
            "Fast path %s failed, falling back to full RIVA: %s",
            pattern.value,
            e,
        )
        return False


# Handler implementations
# These are simplified handlers that bypass full RIVA verification
# They still verify at the end, just with less overhead


def _handle_create_function(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for creating a single function.

    This is a stub - real implementation would:
    1. Extract function name/signature from intention
    2. Generate code with minimal LLM calls
    3. Single verification at end
    """
    # TODO: Implement optimized function creation
    # For now, return False to fall back to full RIVA
    logger.debug("CREATE_FUNCTION fast path not yet implemented")
    return False


def _handle_add_test(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for adding a test.

    This is a stub - real implementation would:
    1. Find the test file
    2. Analyze existing test patterns
    3. Generate matching test
    4. Verify test passes
    """
    # TODO: Implement optimized test creation
    logger.debug("ADD_TEST fast path not yet implemented")
    return False


def _handle_fix_import(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for fixing imports.

    This is a stub - real implementation would:
    1. Identify the missing import
    2. Add it at the right location
    3. Verify no syntax errors
    """
    # TODO: Implement optimized import fix
    logger.debug("FIX_IMPORT fast path not yet implemented")
    return False


def _handle_add_import(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for adding imports."""
    logger.debug("ADD_IMPORT fast path not yet implemented")
    return False


def _handle_fix_typo(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for fixing typos."""
    logger.debug("FIX_TYPO fast path not yet implemented")
    return False


def _handle_create_class(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for creating a class."""
    logger.debug("CREATE_CLASS fast path not yet implemented")
    return False


# Map patterns to handlers
FAST_PATH_HANDLERS: dict[FastPathPattern, Callable] = {
    FastPathPattern.CREATE_FUNCTION: _handle_create_function,
    FastPathPattern.CREATE_CLASS: _handle_create_class,
    FastPathPattern.ADD_TEST: _handle_add_test,
    FastPathPattern.FIX_IMPORT: _handle_fix_import,
    FastPathPattern.ADD_IMPORT: _handle_add_import,
    FastPathPattern.FIX_TYPO: _handle_fix_typo,
}


def get_available_patterns() -> list[FastPathPattern]:
    """Get list of patterns that have implementations."""
    # For now, none are fully implemented
    # Return empty list until handlers are ready
    return []


def is_pattern_available(pattern: FastPathPattern) -> bool:
    """Check if a pattern handler is available and implemented."""
    return pattern in get_available_patterns()
