"""Base classes for multi-language code parsing.

Defines the abstract interface that all language parsers must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class NodeType(Enum):
    """Common AST node types across languages."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    IMPORT = "import"
    VARIABLE = "variable"
    PARAMETER = "parameter"
    CALL = "call"
    STRING = "string"
    COMMENT = "comment"


@dataclass
class CodeNode:
    """Represents a node in the AST.

    Attributes:
        type: Type of node (function, class, etc.)
        name: Name of the node (function name, class name, etc.)
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (1-indexed)
        start_byte: Starting byte offset
        end_byte: Ending byte offset
        text: Source text of the node
        children: Child nodes
        metadata: Additional language-specific metadata
    """

    type: NodeType
    name: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    text: str
    children: list["CodeNode"] | None = None
    metadata: dict[str, Any] | None = None

    @property
    def signature(self) -> str:
        """Get the signature of the node (for functions/methods)."""
        if self.metadata and "signature" in self.metadata:
            return self.metadata["signature"]
        return self.name


@dataclass
class FunctionNode(CodeNode):
    """Specialized node for functions."""

    parameters: list[str] | None = None
    return_type: str | None = None
    is_async: bool = False
    decorators: list[str] | None = None

    def __post_init__(self):
        """Ensure type is FUNCTION."""
        self.type = NodeType.FUNCTION


@dataclass
class ClassNode(CodeNode):
    """Specialized node for classes."""

    base_classes: list[str] | None = None
    methods: list[FunctionNode] | None = None
    decorators: list[str] | None = None

    def __post_init__(self):
        """Ensure type is CLASS."""
        self.type = NodeType.CLASS


@dataclass
class ImportNode(CodeNode):
    """Specialized node for imports."""

    module: str
    names: list[str] | None = None  # For "from X import Y, Z"
    alias: str | None = None  # For "import X as Y"
    is_from_import: bool = False

    def __post_init__(self):
        """Ensure type is IMPORT."""
        self.type = NodeType.IMPORT


class CodeParser(ABC):
    """Abstract base class for language-specific parsers.

    Each language parser must implement these methods to provide
    consistent parsing capabilities across languages.
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Return the name of the language this parser handles."""
        pass

    @abstractmethod
    def parse(self, code: str) -> Any:
        """Parse code into an AST.

        Args:
            code: Source code to parse

        Returns:
            Tree-sitter Tree object

        Raises:
            SyntaxError: If code has syntax errors
        """
        pass

    @abstractmethod
    def find_functions(self, code: str) -> list[FunctionNode]:
        """Find all function definitions in the code.

        Args:
            code: Source code to search

        Returns:
            List of FunctionNode objects
        """
        pass

    @abstractmethod
    def find_classes(self, code: str) -> list[ClassNode]:
        """Find all class definitions in the code.

        Args:
            code: Source code to search

        Returns:
            List of ClassNode objects
        """
        pass

    @abstractmethod
    def find_imports(self, code: str) -> list[ImportNode]:
        """Find all import statements in the code.

        Args:
            code: Source code to search

        Returns:
            List of ImportNode objects
        """
        pass

    @abstractmethod
    def find_function_calls(self, code: str, function_name: str | None = None) -> list[CodeNode]:
        """Find function calls in the code.

        Args:
            code: Source code to search
            function_name: Optional - filter by function name

        Returns:
            List of CodeNode objects representing function calls
        """
        pass

    @abstractmethod
    def validate_syntax(self, code: str) -> tuple[bool, str | None]:
        """Validate that code has correct syntax.

        Args:
            code: Source code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        pass

    def find_node_at_position(self, code: str, line: int, column: int) -> CodeNode | None:
        """Find the AST node at a specific position.

        Args:
            code: Source code
            line: Line number (1-indexed)
            column: Column number (0-indexed)

        Returns:
            CodeNode at position or None
        """
        # Default implementation - subclasses can override
        return None

    def get_import_location(self, code: str) -> int:
        """Get the best line number to insert a new import.

        Args:
            code: Source code

        Returns:
            Line number (1-indexed) where import should be inserted
        """
        # Default implementation - after existing imports
        imports = self.find_imports(code)
        if imports:
            return imports[-1].end_line + 1
        return 1
