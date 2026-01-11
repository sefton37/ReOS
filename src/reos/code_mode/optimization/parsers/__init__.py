"""Multi-language AST parsing for RIVA optimization.

This module provides tree-sitter-based parsers for accurate code analysis
across multiple languages. Replaces regex-based extraction with proper
syntax understanding.

Key Benefits:
- Language-agnostic pattern detection
- Handles edge cases that regex misses
- Fast incremental parsing
- Structured query language for AST traversal

Supported Languages:
- Python (via tree-sitter-python)
- JavaScript/TypeScript (via tree-sitter-javascript)
- Rust (future, via tree-sitter-rust)

Usage:
    from reos.code_mode.optimization.parsers import get_parser

    parser = get_parser("python")
    functions = parser.find_functions(code)
    for func in functions:
        print(f"Found function: {func.name} at line {func.start_line}")

Falls back to regex-based extraction if tree-sitter is not available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.optimization.parsers.base import CodeParser

# Track whether tree-sitter is available
_TREE_SITTER_AVAILABLE = False

try:
    import tree_sitter  # noqa: F401

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    pass


def is_tree_sitter_available() -> bool:
    """Check if tree-sitter is installed and available."""
    return _TREE_SITTER_AVAILABLE


def get_parser(language: str) -> "CodeParser | None":
    """Get a parser for the specified language.

    Args:
        language: Language name (python, javascript, typescript, rust, etc.)

    Returns:
        CodeParser instance or None if language not supported

    Example:
        parser = get_parser("python")
        if parser:
            functions = parser.find_functions(code)
    """
    if not _TREE_SITTER_AVAILABLE:
        return None

    language_lower = language.lower()

    if language_lower == "python":
        from reos.code_mode.optimization.parsers.python_parser import PythonParser

        return PythonParser()
    elif language_lower in ("javascript", "js", "typescript", "ts"):
        from reos.code_mode.optimization.parsers.javascript_parser import JavaScriptParser

        return JavaScriptParser()

    return None


def supports_language(language: str) -> bool:
    """Check if a language is supported.

    Args:
        language: Language name

    Returns:
        True if language has a parser available
    """
    return get_parser(language) is not None


__all__ = [
    "get_parser",
    "supports_language",
    "is_tree_sitter_available",
]
