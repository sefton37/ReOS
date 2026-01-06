"""Symbol extraction from source code using AST parsing.

Extracts functions, classes, methods, and their metadata from Python source files.
Used by RepoMap to build a searchable symbol table.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SymbolKind(str, Enum):
    """Types of symbols that can be extracted."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    ASYNC_FUNCTION = "async_function"
    ASYNC_METHOD = "async_method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    FROM_IMPORT = "from_import"


@dataclass
class Location:
    """Source location of a symbol."""

    file_path: str
    line_start: int
    line_end: int
    column_start: int = 0
    column_end: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
        }


@dataclass
class Symbol:
    """A code symbol (function, class, method, etc.)."""

    name: str
    kind: SymbolKind
    location: Location
    parent: str | None = None  # For nested symbols (methods in classes)
    signature: str | None = None  # e.g., "def foo(x: int, y: str) -> bool"
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "location": self.location.to_dict(),
            "parent": self.parent,
            "signature": self.signature,
            "docstring": self.docstring,
            "decorators": self.decorators,
        }

    @property
    def qualified_name(self) -> str:
        """Full qualified name including parent."""
        if self.parent:
            return f"{self.parent}.{self.name}"
        return self.name


@dataclass
class FileNode:
    """Represents a parsed file with its symbols and metadata."""

    path: str
    language: str
    sha256: str  # For cache invalidation
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # Imported module paths
    exports: list[str] = field(default_factory=list)  # Exported symbol names

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "path": self.path,
            "language": self.language,
            "sha256": self.sha256,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": self.imports,
            "exports": self.exports,
        }


@dataclass
class DependencyEdge:
    """An import relationship between files."""

    from_file: str
    to_file: str
    import_type: str  # "import", "from_import", "dynamic"
    symbols: list[str] = field(default_factory=list)  # Which symbols are imported

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "from_file": self.from_file,
            "to_file": self.to_file,
            "import_type": self.import_type,
            "symbols": self.symbols,
        }


def compute_file_hash(content: str) -> str:
    """Compute SHA256 hash of file content, truncated to 16 chars."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class SymbolExtractor:
    """Extract symbols from Python source files using AST parsing."""

    def extract(self, file_path: str, content: str) -> list[Symbol]:
        """Parse file and return all symbols.

        Args:
            file_path: Path to the file (for location info)
            content: Source code content

        Returns:
            List of extracted symbols
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Can't parse file, return empty
            return []

        symbols: list[Symbol] = []
        self._extract_from_node(tree, file_path, None, symbols)
        return symbols

    def extract_file_node(self, file_path: str, content: str) -> FileNode:
        """Extract complete file information including symbols and imports.

        Args:
            file_path: Path to the file
            content: Source code content

        Returns:
            FileNode with symbols, imports, and exports
        """
        symbols = self.extract(file_path, content)
        imports = self._extract_imports(content)
        exports = self._extract_exports(content, symbols)

        return FileNode(
            path=file_path,
            language="python",
            sha256=compute_file_hash(content),
            symbols=symbols,
            imports=imports,
            exports=exports,
        )

    def _extract_from_node(
        self,
        node: ast.AST,
        file_path: str,
        parent: str | None,
        symbols: list[Symbol],
    ) -> None:
        """Recursively extract symbols from AST node."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                sym = self._function_to_symbol(child, file_path, parent, is_async=False)
                symbols.append(sym)
            elif isinstance(child, ast.AsyncFunctionDef):
                sym = self._function_to_symbol(child, file_path, parent, is_async=True)
                symbols.append(sym)
            elif isinstance(child, ast.ClassDef):
                sym = self._class_to_symbol(child, file_path, parent)
                symbols.append(sym)
                # Recursively extract methods
                self._extract_from_node(child, file_path, child.name, symbols)
            elif isinstance(child, ast.Assign):
                # Top-level assignments (module variables)
                if parent is None:
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            sym = self._assignment_to_symbol(
                                target, child, file_path, is_constant=False
                            )
                            symbols.append(sym)
            elif isinstance(child, ast.AnnAssign):
                # Annotated assignments
                if parent is None and isinstance(child.target, ast.Name):
                    sym = self._ann_assignment_to_symbol(child, file_path)
                    symbols.append(sym)

    def _function_to_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: str,
        parent: str | None,
        is_async: bool,
    ) -> Symbol:
        """Convert function AST node to Symbol."""
        # Determine kind
        if parent is not None:
            kind = SymbolKind.ASYNC_METHOD if is_async else SymbolKind.METHOD
        else:
            kind = SymbolKind.ASYNC_FUNCTION if is_async else SymbolKind.FUNCTION

        # Build signature
        signature = self._build_function_signature(node, is_async)

        # Extract docstring
        docstring = ast.get_docstring(node)

        # Extract decorators
        decorators = [self._decorator_to_string(d) for d in node.decorator_list]

        return Symbol(
            name=node.name,
            kind=kind,
            location=Location(
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                column_start=node.col_offset,
                column_end=node.end_col_offset or 0,
            ),
            parent=parent,
            signature=signature,
            docstring=docstring,
            decorators=decorators,
        )

    def _class_to_symbol(
        self,
        node: ast.ClassDef,
        file_path: str,
        parent: str | None,
    ) -> Symbol:
        """Convert class AST node to Symbol."""
        # Build signature with base classes
        bases = []
        for base in node.bases:
            bases.append(self._node_to_string(base))

        signature = f"class {node.name}"
        if bases:
            signature += f"({', '.join(bases)})"
        signature += ":"

        # Extract docstring
        docstring = ast.get_docstring(node)

        # Extract decorators
        decorators = [self._decorator_to_string(d) for d in node.decorator_list]

        return Symbol(
            name=node.name,
            kind=SymbolKind.CLASS,
            location=Location(
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                column_start=node.col_offset,
                column_end=node.end_col_offset or 0,
            ),
            parent=parent,
            signature=signature,
            docstring=docstring,
            decorators=decorators,
        )

    def _assignment_to_symbol(
        self,
        target: ast.Name,
        node: ast.Assign,
        file_path: str,
        is_constant: bool,
    ) -> Symbol:
        """Convert assignment to Symbol."""
        # Check if it looks like a constant (ALL_CAPS)
        is_const = target.id.isupper() and "_" in target.id or target.id.isupper()

        return Symbol(
            name=target.id,
            kind=SymbolKind.CONSTANT if is_const else SymbolKind.VARIABLE,
            location=Location(
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                column_start=node.col_offset,
                column_end=node.end_col_offset or 0,
            ),
            parent=None,
            signature=f"{target.id} = ...",
        )

    def _ann_assignment_to_symbol(
        self,
        node: ast.AnnAssign,
        file_path: str,
    ) -> Symbol:
        """Convert annotated assignment to Symbol."""
        target = node.target
        if not isinstance(target, ast.Name):
            raise ValueError("Expected Name node")

        type_annotation = self._node_to_string(node.annotation)
        is_const = target.id.isupper()

        return Symbol(
            name=target.id,
            kind=SymbolKind.CONSTANT if is_const else SymbolKind.VARIABLE,
            location=Location(
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                column_start=node.col_offset,
                column_end=node.end_col_offset or 0,
            ),
            parent=None,
            signature=f"{target.id}: {type_annotation}",
        )

    def _build_function_signature(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_async: bool,
    ) -> str:
        """Build function signature string."""
        prefix = "async def" if is_async else "def"
        args_str = self._args_to_string(node.args)
        returns = ""
        if node.returns:
            returns = f" -> {self._node_to_string(node.returns)}"
        return f"{prefix} {node.name}({args_str}){returns}"

    def _args_to_string(self, args: ast.arguments) -> str:
        """Convert function arguments to string."""
        parts = []

        # Positional-only args (before /)
        for i, arg in enumerate(args.posonlyargs):
            parts.append(self._arg_to_string(arg))
        if args.posonlyargs:
            parts.append("/")

        # Regular args
        num_defaults = len(args.defaults)
        num_args = len(args.args)
        for i, arg in enumerate(args.args):
            arg_str = self._arg_to_string(arg)
            # Check if has default
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                arg_str += "=..."
            parts.append(arg_str)

        # *args
        if args.vararg:
            parts.append(f"*{self._arg_to_string(args.vararg)}")
        elif args.kwonlyargs:
            parts.append("*")

        # Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            arg_str = self._arg_to_string(arg)
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                arg_str += "=..."
            parts.append(arg_str)

        # **kwargs
        if args.kwarg:
            parts.append(f"**{self._arg_to_string(args.kwarg)}")

        return ", ".join(parts)

    def _arg_to_string(self, arg: ast.arg) -> str:
        """Convert single argument to string."""
        if arg.annotation:
            return f"{arg.arg}: {self._node_to_string(arg.annotation)}"
        return arg.arg

    def _decorator_to_string(self, node: ast.expr) -> str:
        """Convert decorator node to string."""
        return self._node_to_string(node)

    def _node_to_string(self, node: ast.expr) -> str:
        """Convert an AST expression node to its string representation."""
        try:
            return ast.unparse(node)
        except Exception:
            # Fallback for older Python or complex nodes
            if isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Attribute):
                return f"{self._node_to_string(node.value)}.{node.attr}"
            elif isinstance(node, ast.Subscript):
                return f"{self._node_to_string(node.value)}[...]"
            return "..."

    def _extract_imports(self, content: str) -> list[str]:
        """Extract all import statements from source."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        return imports

    def _extract_exports(self, content: str, symbols: list[Symbol]) -> list[str]:
        """Determine exported symbols (public API)."""
        # Check for explicit __all__
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            exports = []
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(
                                    elt.value, str
                                ):
                                    exports.append(elt.value)
                            return exports

        # No __all__, export all public (non-underscore) top-level symbols
        return [
            s.name
            for s in symbols
            if s.parent is None and not s.name.startswith("_")
        ]
