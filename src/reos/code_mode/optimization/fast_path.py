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

    This handler creates a function in a Python file with minimal overhead.
    It's optimized for simple function creation: "create function X in file Y".

    Steps:
    1. Extract function name, file path, and basic signature from intention
    2. Generate a minimal function stub or use LLM for implementation
    3. Find the right place to insert it (end of file)
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

    # Extract function name and file path
    func_name = _extract_function_name(intention.what)
    file_path = _extract_file_path(intention.what)

    if not func_name:
        logger.debug("CREATE_FUNCTION: Could not extract function name")
        return False

    # If no file path specified, fall back to full RIVA
    if not file_path:
        logger.debug("CREATE_FUNCTION: No file path specified")
        return False

    logger.info(
        "CREATE_FUNCTION fast path: creating '%s' in %s",
        func_name,
        file_path,
    )

    try:
        # Check if file exists, read or create
        try:
            content = ctx.sandbox.read_file(file_path)
            lines = content.splitlines(keepends=True)
        except FileNotFoundError:
            # New file - start with empty content
            content = ""
            lines = []

        # Check if function already exists
        if f"def {func_name}(" in content:
            logger.info("CREATE_FUNCTION: Function already exists, marking success")
            cycle = Cycle(
                thought=f"Check if {func_name} exists",
                action=Action(type=ActionType.QUERY, content=f"Check if def {func_name}( exists"),
                result="Function already exists",
                judgment=Judgment.SUCCESS,
            )
            intention.trace.append(cycle)
            intention.status = IntentionStatus.VERIFIED
            return True

        # Generate function code - use LLM if available, else template
        if ctx.llm:
            func_code = _generate_function_with_llm(
                func_name, intention.what, intention.acceptance, ctx
            )
        else:
            func_code = _generate_function_template(func_name, intention.what)

        if not func_code:
            logger.warning("CREATE_FUNCTION: Could not generate function code")
            return False

        # Add function at the end of file (with blank line before if file has content)
        new_content = content
        if new_content and not new_content.endswith("\n\n"):
            new_content += "\n\n" if new_content.endswith("\n") else "\n\n\n"
        new_content += func_code
        if not new_content.endswith("\n"):
            new_content += "\n"

        # Verify syntax before writing
        if not _verify_python_syntax(new_content, file_path):
            logger.warning("CREATE_FUNCTION: Syntax error after adding function")
            return False

        # Write the file
        if content:
            ctx.sandbox.edit_file(file_path, content, new_content)
        else:
            ctx.sandbox.write_file(file_path, new_content)

        # Record the action
        cycle = Cycle(
            thought=f"Create function {func_name} in {file_path}",
            action=Action(
                type=ActionType.CREATE if not content else ActionType.EDIT,
                content=func_code,
                target=file_path,
            ),
            result=f"Created function {func_name}",
            judgment=Judgment.SUCCESS,
        )
        intention.trace.append(cycle)
        intention.status = IntentionStatus.VERIFIED

        logger.info("CREATE_FUNCTION: Successfully created %s in %s", func_name, file_path)
        return True

    except Exception as e:
        logger.warning("CREATE_FUNCTION fast path failed: %s", e)
        return False


def _handle_add_test(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for adding a test.

    This handler adds a test function to a Python test file with minimal overhead.
    It's optimized for simple test addition: "add test for X" or "create test_Y".

    Steps:
    1. Extract test name and file path from intention
    2. Generate a minimal test function (stub or LLM-generated)
    3. Find the right place to insert it (end of file)
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

    # Extract test name and file path
    test_name = _extract_test_name(intention.what)
    file_path = _extract_file_path(intention.what)

    if not test_name:
        logger.debug("ADD_TEST: Could not extract test name")
        return False

    # If no file path, try to infer from test name
    if not file_path:
        # Common pattern: test_something -> tests/test_something.py
        if test_name.startswith("test_"):
            file_path = f"tests/{test_name.split('test_')[1].split('_')[0]}.py"
            file_path = f"tests/test_{test_name.split('test_')[1].split('_')[0]}.py"
        else:
            logger.debug("ADD_TEST: No file path specified or inferable")
            return False

    logger.info(
        "ADD_TEST fast path: creating '%s' in %s",
        test_name,
        file_path,
    )

    try:
        # Read file or create if doesn't exist
        try:
            content = ctx.sandbox.read_file(file_path)
        except FileNotFoundError:
            content = ""

        # Check if test already exists
        if f"def {test_name}(" in content:
            logger.info("ADD_TEST: Test already exists, marking success")
            cycle = Cycle(
                thought=f"Check if {test_name} exists",
                action=Action(type=ActionType.QUERY, content=f"Check if def {test_name}( exists"),
                result="Test already exists",
                judgment=Judgment.SUCCESS,
            )
            intention.trace.append(cycle)
            intention.status = IntentionStatus.VERIFIED
            return True

        # Generate test code
        if ctx.llm:
            test_code = _generate_test_with_llm(
                test_name, intention.what, intention.acceptance, ctx
            )
        else:
            test_code = _generate_test_template(test_name, intention.what)

        if not test_code:
            logger.warning("ADD_TEST: Could not generate test code")
            return False

        # Add test at end of file
        new_content = content
        if new_content and not new_content.endswith("\n\n"):
            new_content += "\n\n" if new_content.endswith("\n") else "\n\n\n"
        new_content += test_code
        if not new_content.endswith("\n"):
            new_content += "\n"

        # Verify syntax
        if not _verify_python_syntax(new_content, file_path):
            logger.warning("ADD_TEST: Syntax error after adding test")
            return False

        # Write file
        if content:
            ctx.sandbox.edit_file(file_path, content, new_content)
        else:
            ctx.sandbox.write_file(file_path, new_content)

        # Record action
        cycle = Cycle(
            thought=f"Create test {test_name} in {file_path}",
            action=Action(
                type=ActionType.CREATE if not content else ActionType.EDIT,
                content=test_code,
                target=file_path,
            ),
            result=f"Created test {test_name}",
            judgment=Judgment.SUCCESS,
        )
        intention.trace.append(cycle)
        intention.status = IntentionStatus.VERIFIED

        logger.info("ADD_TEST: Successfully created %s in %s", test_name, file_path)
        return True

    except Exception as e:
        logger.warning("ADD_TEST fast path failed: %s", e)
        return False


def _handle_fix_import(intention: "Intention", ctx: "WorkContext") -> bool:
    """Optimized handler for fixing imports.

    This handler fixes missing or incorrect imports in Python files.
    It's similar to ADD_IMPORT but specifically for fixing import errors.

    Steps:
    1. Extract the module/name that needs to be imported
    2. Find the file with the import error
    3. Add or fix the import statement
    4. Verify syntax is valid

    Returns:
        True if handled successfully, False to fall back to full RIVA
    """
    # FIX_IMPORT is essentially the same as ADD_IMPORT
    # Delegate to the ADD_IMPORT handler
    return _handle_add_import(intention, ctx)


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


def _extract_function_name(what: str) -> str | None:
    """Extract function name from intention description.

    Handles patterns like:
    - "create function get_user in file.py"
    - "add calculate_total function"
    - "write a function called process_data"
    - "def parse_json(data):" -> "parse_json"
    """
    # Pattern: "def func_name(...)" - explicit function definition
    match = re.search(r"def\s+(\w+)\s*\(", what)
    if match:
        return match.group(1)

    # Pattern: "function <name>" or "function called <name>"
    match = re.search(r"function\s+(?:called\s+)?(\w+)", what, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern: verb + function name (create/add/write + word)
    match = re.search(r"(?:create|add|write)\s+(?:a\s+)?(\w+)(?:\s+function)?", what, re.IGNORECASE)
    if match and match.group(1).lower() not in ["function", "a", "an", "the"]:
        return match.group(1)

    return None


def _generate_function_template(func_name: str, description: str) -> str:
    """Generate a simple function template without LLM.

    This creates a minimal stub that can be filled in later.
    """
    # Extract parameters if mentioned
    params = _extract_function_params(description)

    if params:
        param_str = ", ".join(params)
        func_def = f"def {func_name}({param_str}):"
    else:
        func_def = f"def {func_name}():"

    # Add a basic docstring
    docstring = f'    """TODO: Implement {func_name}."""'

    # Add pass statement
    body = "    pass"

    return f"{func_def}\n{docstring}\n{body}\n"


def _extract_function_params(description: str) -> list[str]:
    """Extract function parameters from description.

    Looks for patterns like:
    - "function name(param1, param2)"
    - "takes x and y"
    - "with parameter data"
    """
    # Pattern: "func_name(param1, param2, ...)"
    match = re.search(r"\w+\s*\(([^)]+)\)", description)
    if match:
        params_str = match.group(1)
        return [p.strip() for p in params_str.split(",") if p.strip()]

    # Pattern: "takes x and y" or "with parameters x, y"
    match = re.search(r"(?:takes|with parameters?)\s+([\w\s,and]+)", description, re.IGNORECASE)
    if match:
        params_str = match.group(1)
        # Split on "and" or ","
        params = re.split(r"[,\s]+(?:and\s+)?", params_str)
        return [p.strip() for p in params if p.strip() and p.strip().lower() not in ["and", ""]]

    return []


def _generate_function_with_llm(
    func_name: str,
    description: str,
    acceptance: str,
    ctx: "WorkContext",
) -> str | None:
    """Generate function implementation using LLM.

    Uses a simple prompt to generate the function quickly.
    """
    if not ctx.llm:
        return None

    prompt = f"""Generate a Python function based on this request:

Function name: {func_name}
Description: {description}
Acceptance criteria: {acceptance}

Generate ONLY the function definition with implementation. No explanations, no markdown.
Include a docstring and proper error handling if needed.
"""

    try:
        response = ctx.llm.generate_text(prompt)
        if not response:
            return None

        # Extract code if wrapped in markdown
        code = response.strip()
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0].strip()
        elif "```" in code:
            code = code.split("```")[1].split("```")[0].strip()

        # Verify it starts with def
        if not code.startswith("def "):
            logger.warning("Generated code doesn't start with 'def'")
            return None

        return code + "\n"

    except Exception as e:
        logger.warning("LLM function generation failed: %s", e)
        return None


def _extract_test_name(what: str) -> str | None:
    """Extract test name from intention description.

    Handles patterns like:
    - "add test for get_user" -> "test_get_user"
    - "create test_calculate_total"
    - "write test that verifies parse_json" -> "test_parse_json"
    """
    # Pattern: explicit "test_<name>"
    match = re.search(r"(test_\w+)", what, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    # Pattern: "test for <function_name>" or "test <function_name>"
    match = re.search(r"test\s+(?:for\s+|that\s+\w+\s+)?(\w+)", what, re.IGNORECASE)
    if match:
        func_name = match.group(1)
        if func_name.lower() not in ["that", "for", "a", "an", "the"]:
            return f"test_{func_name}"

    return None


def _generate_test_template(test_name: str, description: str) -> str:
    """Generate a simple test template without LLM.

    Creates a minimal test stub using pytest style.
    """
    docstring = f'    """Test {test_name.replace("test_", "").replace("_", " ")}."""'
    body = "    assert False, 'Test not implemented'"

    return f"def {test_name}():\n{docstring}\n{body}\n"


def _generate_test_with_llm(
    test_name: str,
    description: str,
    acceptance: str,
    ctx: "WorkContext",
) -> str | None:
    """Generate test implementation using LLM.

    Uses a simple prompt to generate the test quickly.
    """
    if not ctx.llm:
        return None

    prompt = f"""Generate a Python test function based on this request:

Test name: {test_name}
Description: {description}
Acceptance criteria: {acceptance}

Generate ONLY the test function definition with implementation. No explanations, no markdown.
Use pytest style (assert statements). Include a docstring.
"""

    try:
        response = ctx.llm.generate_text(prompt)
        if not response:
            return None

        # Extract code if wrapped in markdown
        code = response.strip()
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0].strip()
        elif "```" in code:
            code = code.split("```")[1].split("```")[0].strip()

        # Verify it starts with def
        if not code.startswith("def "):
            logger.warning("Generated test doesn't start with 'def'")
            return None

        return code + "\n"

    except Exception as e:
        logger.warning("LLM test generation failed: %s", e)
        return None


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
        FastPathPattern.FIX_IMPORT,
        FastPathPattern.CREATE_FUNCTION,
        FastPathPattern.ADD_TEST,
    ]


def is_pattern_available(pattern: FastPathPattern) -> bool:
    """Check if a pattern handler is available and implemented."""
    return pattern in get_available_patterns()
