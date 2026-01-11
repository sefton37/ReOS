"""JavaScript/TypeScript parser using tree-sitter.

Provides accurate JavaScript/TypeScript AST parsing for RIVA optimization.
"""

from __future__ import annotations

import logging
from typing import Any

from reos.code_mode.optimization.parsers.base import (
    CodeNode,
    CodeParser,
    ClassNode,
    FunctionNode,
    ImportNode,
    NodeType,
)

logger = logging.getLogger(__name__)

try:
    import tree_sitter_javascript as tsjavascript
    from tree_sitter import Language, Parser

    JAVASCRIPT_LANGUAGE = Language(tsjavascript.language())
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    JAVASCRIPT_LANGUAGE = None


class JavaScriptParser(CodeParser):
    """Tree-sitter-based JavaScript/TypeScript parser."""

    def __init__(self):
        """Initialize JavaScript parser."""
        if not _AVAILABLE:
            raise ImportError(
                "tree-sitter-javascript not available. "
                "Install with: pip install tree-sitter tree-sitter-javascript"
            )

        self.parser = Parser(JAVASCRIPT_LANGUAGE)

    @property
    def language_name(self) -> str:
        """Return 'javascript'."""
        return "javascript"

    def parse(self, code: str) -> Any:
        """Parse JavaScript code into AST.

        Args:
            code: JavaScript source code

        Returns:
            tree-sitter Tree object
        """
        return self.parser.parse(bytes(code, "utf8"))

    def find_functions(self, code: str) -> list[FunctionNode]:
        """Find all function definitions in JavaScript code.

        Args:
            code: JavaScript source code

        Returns:
            List of FunctionNode objects
        """
        tree = self.parse(code)
        functions = []

        # Query for function declarations and expressions
        query = JAVASCRIPT_LANGUAGE.query(
            """
            (function_declaration
                name: (identifier) @name
                parameters: (formal_parameters) @params
            ) @function

            (arrow_function
                parameters: (formal_parameters) @params
            ) @arrow

            (method_definition
                name: (property_identifier) @name
                parameters: (formal_parameters) @params
            ) @method
            """
        )

        captures = query.captures(tree.root_node)

        # Group captures by node
        function_nodes = {}
        for node, capture_name in captures:
            if capture_name in ("function", "arrow", "method"):
                if node.id not in function_nodes:
                    function_nodes[node.id] = {"node": node, "type": capture_name, "name": None, "params": None}
            elif capture_name == "name":
                parent = node.parent
                while parent and parent.id not in function_nodes:
                    parent = parent.parent
                if parent and parent.id in function_nodes:
                    function_nodes[parent.id]["name"] = node.text.decode("utf8")
            elif capture_name == "params":
                parent = node.parent
                if parent and parent.id in function_nodes:
                    function_nodes[parent.id]["params"] = node

        # Convert to FunctionNode objects
        for func_data in function_nodes.values():
            node = func_data["node"]
            name = func_data["name"] or "anonymous"

            # Extract parameters
            params = []
            if func_data["params"]:
                for child in func_data["params"].children:
                    if child.type in ("identifier", "shorthand_property_identifier_pattern"):
                        params.append(child.text.decode("utf8"))
                    elif child.type == "rest_pattern":
                        # ...args
                        for subchild in child.children:
                            if subchild.type == "identifier":
                                params.append("..." + subchild.text.decode("utf8"))

            # Check for async
            is_async = False
            if node.prev_sibling and node.prev_sibling.type == "async":
                is_async = True

            functions.append(
                FunctionNode(
                    type=NodeType.FUNCTION,
                    name=name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    text=node.text.decode("utf8"),
                    parameters=params if params else None,
                    is_async=is_async,
                )
            )

        return functions

    def find_classes(self, code: str) -> list[ClassNode]:
        """Find all class definitions in JavaScript code.

        Args:
            code: JavaScript source code

        Returns:
            List of ClassNode objects
        """
        tree = self.parse(code)
        classes = []

        query = JAVASCRIPT_LANGUAGE.query(
            """
            (class_declaration
                name: (identifier) @name
            ) @class
            """
        )

        captures = query.captures(tree.root_node)

        class_nodes = {}
        for node, capture_name in captures:
            if capture_name == "class":
                class_nodes[node.id] = {"node": node, "name": None}
            elif capture_name == "name":
                parent = node.parent
                if parent and parent.id in class_nodes:
                    class_nodes[parent.id]["name"] = node.text.decode("utf8")

        # Convert to ClassNode objects
        for class_data in class_nodes.values():
            node = class_data["node"]
            name = class_data["name"] or "anonymous"

            # Extract base class (extends)
            base_classes = []
            for child in node.children:
                if child.type == "class_heritage":
                    for subchild in child.children:
                        if subchild.type == "identifier":
                            base_classes.append(subchild.text.decode("utf8"))

            classes.append(
                ClassNode(
                    type=NodeType.CLASS,
                    name=name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    text=node.text.decode("utf8"),
                    base_classes=base_classes if base_classes else None,
                )
            )

        return classes

    def find_imports(self, code: str) -> list[ImportNode]:
        """Find all import statements in JavaScript code.

        Args:
            code: JavaScript source code

        Returns:
            List of ImportNode objects
        """
        tree = self.parse(code)
        imports = []

        query = JAVASCRIPT_LANGUAGE.query(
            """
            (import_statement
                source: (string) @source
            ) @import
            """
        )

        captures = query.captures(tree.root_node)

        import_nodes = {}
        for node, capture_name in captures:
            if capture_name == "import":
                import_nodes[node.id] = {"node": node, "source": None}
            elif capture_name == "source":
                parent = node.parent
                if parent and parent.id in import_nodes:
                    # Remove quotes from source
                    source = node.text.decode("utf8").strip('"\'')
                    import_nodes[parent.id]["source"] = source

        # Convert to ImportNode objects
        for import_data in import_nodes.values():
            node = import_data["node"]
            source = import_data["source"] or "unknown"

            imports.append(
                ImportNode(
                    type=NodeType.IMPORT,
                    name=f"import from {source}",
                    module=source,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    text=node.text.decode("utf8"),
                )
            )

        return imports

    def find_function_calls(self, code: str, function_name: str | None = None) -> list[CodeNode]:
        """Find function calls in JavaScript code.

        Args:
            code: JavaScript source code
            function_name: Optional filter by function name

        Returns:
            List of CodeNode objects
        """
        tree = self.parse(code)
        calls = []

        query = JAVASCRIPT_LANGUAGE.query(
            """
            (call_expression
                function: (identifier) @func_name
            ) @call
            """
        )

        captures = query.captures(tree.root_node)

        call_nodes = {}
        for node, capture_name in captures:
            if capture_name == "call":
                call_nodes[node.id] = {"node": node, "name": None}
            elif capture_name == "func_name":
                parent = node.parent
                if parent and parent.id in call_nodes:
                    call_nodes[parent.id]["name"] = node.text.decode("utf8")

        # Filter and convert
        for call_data in call_nodes.values():
            node = call_data["node"]
            name = call_data["name"] or "unknown"

            # Filter by name if requested
            if function_name and name != function_name:
                continue

            calls.append(
                CodeNode(
                    type=NodeType.CALL,
                    name=name,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    text=node.text.decode("utf8"),
                )
            )

        return calls

    def validate_syntax(self, code: str) -> tuple[bool, str | None]:
        """Validate JavaScript syntax.

        Args:
            code: JavaScript source code

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            tree = self.parse(code)

            # Check for ERROR nodes
            def has_error(node):
                if node.type == "ERROR" or node.is_missing:
                    return True
                for child in node.children:
                    if has_error(child):
                        return True
                return False

            if has_error(tree.root_node):
                return False, "Syntax error detected in code"

            return True, None

        except Exception as e:
            return False, str(e)

    def get_import_location(self, code: str) -> int:
        """Get the best line number to insert a new import.

        Args:
            code: JavaScript source code

        Returns:
            Line number (1-indexed) where import should be inserted
        """
        imports = self.find_imports(code)
        if imports:
            # After last import
            return imports[-1].end_line

        # Start of file
        return 1
