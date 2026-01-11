"""Fast-path handlers for common patterns.

80% of requests are variations on 20% of patterns.
We optimize those common patterns and use full RIVA for edge cases.

Patterns are detected heuristically. When detection fails,
we fall back to full RIVA - no harm done.

Implemented Handlers
--------------------
- ADD_IMPORT: Add import statements to Python files

Scaffolded (not yet implemented)
--------------------------------
- CREATE_FUNCTION, CREATE_CLASS, CREATE_FILE
- ADD_TEST, FIX_TEST
- FIX_IMPORT, FIX_TYPO, FIX_INDENT
- ADD_METHOD, ADD_DOCSTRING

Use get_available_patterns() to check which handlers are ready.
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
    """Optimized handler for adding imports.

    This handler adds an import statement to a Python file with minimal overhead.
    It's optimized for the common case: "add import X to file Y".

    Steps:
    1. Extract file path and import statement from intention
    2. Read the file and find the import section
    3. Add the import at the right location
    4. Verify syntax is valid

    Returns:
        True if handled successfully, False to fall back to full RIVA
    """
    from reos.code_mode.intention import (
        ActionType,
        Action,
        Cycle,
        Judgment,
        IntentionStatus,
    )

    # Extract file path and import from intention
    file_path = _extract_file_path(intention.what)
    import_stmt = _extract_import_statement(intention.what)

    if not file_path or not import_stmt:
        logger.debug("ADD_IMPORT: Could not extract file path or import statement")
        return False

    logger.info(
        "ADD_IMPORT fast path: adding '%s' to %s",
        import_stmt.strip(),
        file_path,
    )

    try:
        # Read the file
        content = ctx.sandbox.read_file(file_path)
        lines = content.splitlines(keepends=True)

        # Check if import already exists
        import_line = import_stmt if import_stmt.endswith("\n") else import_stmt + "\n"
        if import_stmt.strip() in content:
            logger.info("ADD_IMPORT: Import already exists, marking success")
            # Create a cycle to record the action
            cycle = Cycle(
                action=Action(type=ActionType.QUERY, content=f"Check if {import_stmt} exists"),
                result="Import already exists",
                judgment=Judgment.SUCCESS,
            )
            intention.trace.append(cycle)
            intention.status = IntentionStatus.VERIFIED
            return True

        # Find the right position to insert
        insert_pos = _find_import_insert_position(lines, import_stmt)

        # Insert the import
        lines.insert(insert_pos, import_line)
        new_content = "".join(lines)

        # Verify syntax before writing
        if not _verify_python_syntax(new_content, file_path):
            logger.warning("ADD_IMPORT: Syntax error after adding import")
            return False

        # Write the file
        old_str, new_str = _build_import_edit(lines, insert_pos, import_line, content)
        ctx.sandbox.edit_file(file_path, old_str, new_str)

        # Record the action in the intention
        cycle = Cycle(
            action=Action(type=ActionType.EDIT, content=f"Add {import_stmt} to {file_path}"),
            result=f"Added import at line {insert_pos + 1}",
            judgment=Judgment.SUCCESS,
        )
        intention.trace.append(cycle)
        intention.status = IntentionStatus.VERIFIED

        logger.info("ADD_IMPORT: Successfully added import at line %d", insert_pos + 1)
        return True

    except Exception as e:
        logger.warning("ADD_IMPORT fast path failed: %s", e)
        return False


def _extract_file_path(what: str) -> str | None:
    """Extract file path from intention description.

    Handles patterns like:
    - "add import json to src/utils/parser.py"
    - "import datetime in lib/helpers.py"
    - "src/main.py: add import os"
    """
    # Pattern: explicit "to <path>" or "in <path>"
    match = re.search(r"(?:to|in)\s+([^\s]+\.py)", what, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern: "<path>:" at the start
    match = re.search(r"^([^\s:]+\.py)\s*:", what)
    if match:
        return match.group(1)

    # Pattern: any .py path in the string
    match = re.search(r"([a-zA-Z0-9_/\\.-]+\.py)", what)
    if match:
        return match.group(1)

    return None


def _extract_import_statement(what: str) -> str | None:
    """Extract import statement from intention description.

    Handles patterns like:
    - "add import json to file.py" -> "import json"
    - "add from typing import Optional" -> "from typing import Optional"
    - "import datetime in file.py" -> "import datetime"
    """
    # Pattern: "from X import Y" - stop at words that indicate end of import
    match = re.search(
        r"(from\s+[\w.]+\s+import\s+(?:[\w]+(?:\s*,\s*[\w]+)*|\*))",
        what,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Pattern: "import X" (but not "add import X")
    match = re.search(r"(?:^|add\s+)(import\s+[\w.]+(?:\s+as\s+\w+)?)", what, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return None


def _find_import_insert_position(lines: list[str], import_stmt: str) -> int:
    """Find the best position to insert an import.

    Strategy:
    - After __future__ imports
    - Group with similar imports (stdlib, third-party, local)
    - After docstrings and before code
    """
    last_import_line = 0
    in_docstring = False
    docstring_end = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track docstrings
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                docstring_end = i + 1
            elif stripped.count('"""') == 1 or stripped.count("'''") == 1:
                in_docstring = True
            else:
                # Single-line docstring
                docstring_end = i + 1

        # Track imports
        if stripped.startswith(("import ", "from ")):
            last_import_line = i + 1

    # If there are existing imports, add after them
    if last_import_line > 0:
        return last_import_line

    # If there's a module docstring, add after it
    if docstring_end > 0:
        return docstring_end

    # Otherwise, add at the beginning
    return 0


def _verify_python_syntax(content: str, file_path: str) -> bool:
    """Verify Python syntax is valid.

    Returns True if syntax is valid, False otherwise.
    """
    import ast

    try:
        ast.parse(content)
        return True
    except SyntaxError as e:
        logger.debug("Syntax error in %s: %s", file_path, e)
        return False


def _build_import_edit(
    lines: list[str],
    insert_pos: int,
    import_line: str,
    original_content: str,
) -> tuple[str, str]:
    """Build old_str and new_str for the edit operation.

    Since we're inserting, we need to find an anchor point.
    We use the line at insert_pos (or the last line if inserting at end).
    """
    if insert_pos == 0:
        # Inserting at the beginning
        if lines:
            old_str = lines[0]
            new_str = import_line + old_str
        else:
            # Empty file
            old_str = ""
            new_str = import_line
    elif insert_pos >= len(lines):
        # Inserting at the end
        old_str = lines[-1]
        new_str = old_str.rstrip("\n") + "\n" + import_line
    else:
        # Inserting in the middle - use the line before as anchor
        old_str = lines[insert_pos - 1]
        new_str = old_str.rstrip("\n") + "\n" + import_line

    return old_str, new_str


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
    return [
        FastPathPattern.ADD_IMPORT,
    ]


def is_pattern_available(pattern: FastPathPattern) -> bool:
    """Check if a pattern handler is available and implemented."""
    return pattern in get_available_patterns()
