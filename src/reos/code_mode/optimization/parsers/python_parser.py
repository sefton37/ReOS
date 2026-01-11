"""Python parser using tree-sitter.

Provides accurate Python AST parsing for RIVA optimization fast paths.
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
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser

    PYTHON_LANGUAGE = Language(tspython.language())
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    PYTHON_LANGUAGE = None


class PythonParser(CodeParser):
    """Tree-sitter-based Python parser."""

    def __init__(self):
        """Initialize Python parser."""
        if not _AVAILABLE:
            raise ImportError(
                "tree-sitter-python not available. "
                "Install with: pip install tree-sitter tree-sitter-python"
            )

        self.parser = Parser(PYTHON_LANGUAGE)

    @property
    def language_name(self) -> str:
        """Return 'python'."""
        return "python"

    def parse(self, code: str) -> Any:
        """Parse Python code into AST.

        Args:
            code: Python source code

        Returns:
            tree-sitter Tree object
        """
        return self.parser.parse(bytes(code, "utf8"))

    def find_functions(self, code: str) -> list[FunctionNode]:
        """Find all function definitions in Python code.

        Args:
            code: Python source code

        Returns:
            List of FunctionNode objects
        """
        tree = self.parse(code)
        functions = []

        # Query for function definitions
        # (function_definition name: (identifier) @name) @function
        query = PYTHON_LANGUAGE.query(
            """
            (function_definition
                name: (identifier) @name
                parameters: (parameters) @params
            ) @function
            """
        )

        captures = query.captures(tree.root_node)
        code_bytes = bytes(code, "utf8")

        # Group captures by function node
        function_nodes = {}
        for node, capture_name in captures:
            if capture_name == "function":
                function_nodes[node.id] = {"node": node, "name": None, "params": None}
            elif capture_name == "name":
                # Find parent function
                parent = node.parent
                while parent and parent.type != "function_definition":
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
            name = func_data["name"] or "unknown"

            # Extract parameters
            params = []
            if func_data["params"]:
                for child in func_data["params"].children:
                    if child.type == "identifier":
                        params.append(child.text.decode("utf8"))
                    elif child.type in ("typed_parameter", "default_parameter"):
                        # Get the parameter name
                        for subchild in child.children:
                            if subchild.type == "identifier":
                                params.append(subchild.text.decode("utf8"))
                                break

            # Check for async
            is_async = False
            if node.prev_sibling and node.prev_sibling.type == "async":
                is_async = True

            # Extract decorators
            decorators = []
            prev = node.prev_sibling
            while prev and prev.type == "decorator":
                decorators.insert(0, prev.text.decode("utf8"))
                prev = prev.prev_sibling

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
                    decorators=decorators if decorators else None,
                )
            )

        return functions

    def find_classes(self, code: str) -> list[ClassNode]:
        """Find all class definitions in Python code.

        Args:
            code: Python source code

        Returns:
            List of ClassNode objects
        """
        tree = self.parse(code)
        classes = []

        query = PYTHON_LANGUAGE.query(
            """
            (class_definition
                name: (identifier) @name
            ) @class
            """
        )

        captures = query.captures(tree.root_node)
        code_bytes = bytes(code, "utf8")

        # Group captures
        class_nodes = {}
        for node, capture_name in captures:
            if capture_name == "class":
                class_nodes[node.id] = {"node": node, "name": None}
            elif capture_name == "name":
                parent = node.parent
                while parent and parent.type != "class_definition":
                    parent = parent.parent
                if parent and parent.id in class_nodes:
                    class_nodes[parent.id]["name"] = node.text.decode("utf8")

        # Convert to ClassNode objects
        for class_data in class_nodes.values():
            node = class_data["node"]
            name = class_data["name"] or "unknown"

            # Extract base classes
            base_classes = []
            for child in node.children:
                if child.type == "argument_list":
                    for arg in child.children:
                        if arg.type == "identifier":
                            base_classes.append(arg.text.decode("utf8"))

            # Extract decorators
            decorators = []
            prev = node.prev_sibling
            while prev and prev.type == "decorator":
                decorators.insert(0, prev.text.decode("utf8"))
                prev = prev.prev_sibling

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
                    decorators=decorators if decorators else None,
                )
            )

        return classes

    def find_imports(self, code: str) -> list[ImportNode]:
        """Find all import statements in Python code.

        Args:
            code: Python source code

        Returns:
            List of ImportNode objects
        """
        tree = self.parse(code)
        imports = []

        # Query for both "import" and "from...import"
        query = PYTHON_LANGUAGE.query(
            """
            (import_statement
                name: (dotted_name) @module
            ) @import

            (import_from_statement
                module_name: (dotted_name) @from_module
            ) @from_import
            """
        )

        captures = query.captures(tree.root_node)

        for node, capture_name in captures:
            if capture_name == "import":
                # Regular import statement
                module_name = None
                for child in node.children:
                    if child.type == "dotted_name":
                        module_name = child.text.decode("utf8")
                        break

                if module_name:
                    imports.append(
                        ImportNode(
                            type=NodeType.IMPORT,
                            name=f"import {module_name}",
                            module=module_name,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            start_byte=node.start_byte,
                            end_byte=node.end_byte,
                            text=node.text.decode("utf8"),
                            is_from_import=False,
                        )
                    )

            elif capture_name == "from_import":
                # from X import Y statement
                module_name = None
                imported_names = []

                for child in node.children:
                    if child.type == "dotted_name":
                        module_name = child.text.decode("utf8")
                    elif child.type in ("aliased_import", "dotted_name") and child.parent == node:
                        # Direct child import names
                        for subchild in child.children:
                            if subchild.type in ("identifier", "dotted_name"):
                                imported_names.append(subchild.text.decode("utf8"))

                if module_name:
                    imports.append(
                        ImportNode(
                            type=NodeType.IMPORT,
                            name=f"from {module_name} import ...",
                            module=module_name,
                            names=imported_names if imported_names else None,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            start_byte=node.start_byte,
                            end_byte=node.end_byte,
                            text=node.text.decode("utf8"),
                            is_from_import=True,
                        )
                    )

        return imports

    def find_function_calls(self, code: str, function_name: str | None = None) -> list[CodeNode]:
        """Find function calls in Python code.

        Args:
            code: Python source code
            function_name: Optional filter by function name

        Returns:
            List of CodeNode objects
        """
        tree = self.parse(code)
        calls = []

        query = PYTHON_LANGUAGE.query(
            """
            (call
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
        """Validate Python syntax.

        Args:
            code: Python source code

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            tree = self.parse(code)

            # Check for ERROR nodes in the tree
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
            code: Python source code

        Returns:
            Line number (1-indexed) where import should be inserted
        """
        imports = self.find_imports(code)
        if imports:
            # After last import
            return imports[-1].end_line

        # Check for module docstring
        tree = self.parse(code)
        if tree.root_node.children:
            first_node = tree.root_node.children[0]
            if first_node.type == "expression_statement":
                # Might be a docstring
                for child in first_node.children:
                    if child.type == "string":
                        return first_node.end_point[0] + 2  # After docstring + blank line

        # Start of file
        return 1
