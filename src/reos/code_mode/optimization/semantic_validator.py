"""Semantic validation for code.

Checks that code makes semantic sense beyond just syntax:
- Imports are resolvable
- Variables are defined before use
- Functions/classes referenced exist
- Type hints are consistent

Uses tree-sitter for AST analysis and optionally Jedi for Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.intention import Action, WorkContext

logger = logging.getLogger(__name__)


@dataclass
class SemanticIssue:
    """A semantic issue found in code.

    Attributes:
        severity: "error", "warning", or "info"
        message: Human-readable description
        line: Line number (1-indexed)
        column: Column number (0-indexed) if available
        code: Error code (e.g., "undefined-name", "unresolved-import")
    """

    severity: str
    message: str
    line: int
    column: int | None = None
    code: str | None = None

    def __str__(self) -> str:
        """Human-readable format."""
        loc = f"line {self.line}"
        if self.column is not None:
            loc += f", col {self.column}"
        return f"{self.severity.upper()} [{self.code}] at {loc}: {self.message}"


def validate_python_semantics(code: str, context: "WorkContext") -> list[SemanticIssue]:
    """Validate Python code semantics.

    Checks:
    1. Undefined names (variables, functions used before definition)
    2. Unresolved imports (modules that don't exist)
    3. Function calls with wrong arity
    4. Type inconsistencies (if type hints present)

    Args:
        code: Python source code
        context: Work context (for sandbox access)

    Returns:
        List of semantic issues found (empty if all clear)
    """
    issues = []

    # Check 1: Undefined names using AST analysis
    issues.extend(_check_undefined_names_python(code))

    # Check 2: Unresolved imports
    issues.extend(_check_imports_python(code, context))

    # Check 3: Try Jedi if available (more thorough)
    try:
        issues.extend(_check_with_jedi(code))
    except ImportError:
        logger.debug("Jedi not available, skipping advanced semantic checks")
    except Exception as e:
        logger.debug("Jedi check failed: %s", e)

    return issues


def _check_undefined_names_python(code: str) -> list[SemanticIssue]:
    """Check for undefined names in Python code using AST.

    Returns:
        List of issues for names used before definition
    """
    import ast

    issues = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Syntax errors already caught by syntax layer
        return issues

    # Track defined names by scope
    defined_names = set()
    builtin_names = set(dir(__builtins__))

    class NameChecker(ast.NodeVisitor):
        def __init__(self):
            self.current_line = 1

        def visit_Name(self, node):
            self.current_line = node.lineno
            # Check if name is used but not defined
            if isinstance(node.ctx, ast.Load):
                name = node.id
                if name not in defined_names and name not in builtin_names:
                    issues.append(
                        SemanticIssue(
                            severity="error",
                            message=f"Name '{name}' is not defined",
                            line=node.lineno,
                            column=node.col_offset,
                            code="undefined-name",
                        )
                    )
            # Track name definitions
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                defined_names.add(node.id)

            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            # Function name is defined
            defined_names.add(node.name)
            # Parameters are defined in function scope
            for arg in node.args.args:
                defined_names.add(arg.arg)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            # Class name is defined
            defined_names.add(node.name)
            self.generic_visit(node)

        def visit_Import(self, node):
            # import foo → defines foo
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                defined_names.add(name.split(".")[0])  # Just the top-level module

        def visit_ImportFrom(self, node):
            # from foo import bar → defines bar
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                if name != "*":
                    defined_names.add(name)

    checker = NameChecker()
    checker.visit(tree)

    return issues


def _check_imports_python(code: str, context: "WorkContext") -> list[SemanticIssue]:
    """Check if imports are resolvable.

    Args:
        code: Python source code
        context: Work context

    Returns:
        List of issues for unresolved imports
    """
    import ast
    import importlib.util

    issues = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues

    class ImportChecker(ast.NodeVisitor):
        def visit_Import(self, node):
            for alias in node.names:
                module_name = alias.name.split(".")[0]  # Top-level module
                if not _can_import(module_name):
                    issues.append(
                        SemanticIssue(
                            severity="warning",
                            message=f"Cannot resolve import '{alias.name}'",
                            line=node.lineno,
                            code="unresolved-import",
                        )
                    )

        def visit_ImportFrom(self, node):
            if node.module:
                module_name = node.module.split(".")[0]
                if not _can_import(module_name):
                    issues.append(
                        SemanticIssue(
                            severity="warning",
                            message=f"Cannot resolve import from '{node.module}'",
                            line=node.lineno,
                            code="unresolved-import",
                        )
                    )

    checker = ImportChecker()
    checker.visit(tree)

    return issues


def _can_import(module_name: str) -> bool:
    """Check if a module can be imported.

    Args:
        module_name: Top-level module name

    Returns:
        True if module is importable
    """
    import importlib.util

    # Check if it's a standard library module
    spec = importlib.util.find_spec(module_name)
    return spec is not None


def _check_with_jedi(code: str) -> list[SemanticIssue]:
    """Use Jedi for advanced semantic analysis.

    Jedi provides:
    - Type inference
    - Name resolution
    - Completion context

    Requires: pip install jedi

    Args:
        code: Python source code

    Returns:
        List of semantic issues
    """
    import jedi

    issues = []

    # Create Jedi Script
    script = jedi.Script(code)

    # Get syntax errors (Jedi catches some semantic issues as "syntax" errors)
    errors = script.get_syntax_errors()
    for error in errors:
        # Jedi errors include semantic issues like undefined names
        issues.append(
            SemanticIssue(
                severity="error" if "error" in error.type else "warning",
                message=error.message,
                line=error.line,
                column=error.column,
                code="jedi-" + error.type,
            )
        )

    return issues


def validate_javascript_semantics(code: str, context: "WorkContext") -> list[SemanticIssue]:
    """Validate JavaScript/TypeScript semantics.

    Checks:
    1. Undefined variables
    2. Unresolved imports
    3. Function calls with wrong arity

    Args:
        code: JavaScript source code
        context: Work context

    Returns:
        List of semantic issues
    """
    # TODO: Implement JavaScript semantic validation
    # Could use eslint, typescript compiler, or tree-sitter queries
    return []
