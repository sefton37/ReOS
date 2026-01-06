"""Tests for symbol extraction from Python source files."""

from __future__ import annotations

import pytest

from reos.code_mode.symbol_extractor import (
    SymbolExtractor,
    SymbolKind,
    Symbol,
    Location,
    FileNode,
    compute_file_hash,
)


class TestSymbolExtractor:
    """Tests for the SymbolExtractor class."""

    @pytest.fixture
    def extractor(self) -> SymbolExtractor:
        """Create a SymbolExtractor instance."""
        return SymbolExtractor()

    def test_extract_function(self, extractor: SymbolExtractor) -> None:
        """Should extract a simple function."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert sym.name == "hello"
        assert sym.kind == SymbolKind.FUNCTION
        assert sym.signature == "def hello(name: str) -> str"
        assert sym.docstring == "Say hello."
        assert sym.parent is None

    def test_extract_async_function(self, extractor: SymbolExtractor) -> None:
        """Should extract an async function."""
        code = '''
async def fetch_data(url: str) -> dict:
    """Fetch data from URL."""
    pass
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert sym.name == "fetch_data"
        assert sym.kind == SymbolKind.ASYNC_FUNCTION
        assert "async def" in sym.signature

    def test_extract_class(self, extractor: SymbolExtractor) -> None:
        """Should extract a class."""
        code = '''
class MyClass:
    """A simple class."""
    pass
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert sym.name == "MyClass"
        assert sym.kind == SymbolKind.CLASS
        assert sym.docstring == "A simple class."
        assert sym.signature == "class MyClass:"

    def test_extract_class_with_bases(self, extractor: SymbolExtractor) -> None:
        """Should extract class with base classes."""
        code = '''
class ChildClass(ParentClass, Mixin):
    pass
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert sym.name == "ChildClass"
        assert "ParentClass" in sym.signature
        assert "Mixin" in sym.signature

    def test_extract_methods(self, extractor: SymbolExtractor) -> None:
        """Should extract class methods with correct parent."""
        code = '''
class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
'''
        symbols = extractor.extract("test.py", code)

        # Should have class + 2 methods
        assert len(symbols) == 3

        class_sym = next(s for s in symbols if s.kind == SymbolKind.CLASS)
        assert class_sym.name == "Calculator"

        methods = [s for s in symbols if s.kind == SymbolKind.METHOD]
        assert len(methods) == 2

        add_method = next(m for m in methods if m.name == "add")
        assert add_method.parent == "Calculator"
        assert add_method.qualified_name == "Calculator.add"

    def test_extract_async_method(self, extractor: SymbolExtractor) -> None:
        """Should extract async methods."""
        code = '''
class AsyncHandler:
    async def handle(self, request):
        pass
'''
        symbols = extractor.extract("test.py", code)

        method = next(s for s in symbols if s.name == "handle")
        assert method.kind == SymbolKind.ASYNC_METHOD
        assert method.parent == "AsyncHandler"

    def test_extract_decorated_function(self, extractor: SymbolExtractor) -> None:
        """Should extract decorators."""
        code = '''
@staticmethod
@cache
def cached_func():
    pass
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert "staticmethod" in sym.decorators
        assert "cache" in sym.decorators

    def test_extract_variable(self, extractor: SymbolExtractor) -> None:
        """Should extract module-level variables."""
        code = '''
config = {"debug": True}
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sym = symbols[0]
        assert sym.name == "config"
        assert sym.kind == SymbolKind.VARIABLE

    def test_extract_constant(self, extractor: SymbolExtractor) -> None:
        """Should detect constants (ALL_CAPS)."""
        code = '''
MAX_RETRIES = 3
API_URL = "https://example.com"
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 2
        for sym in symbols:
            assert sym.kind == SymbolKind.CONSTANT

    def test_extract_annotated_variable(self, extractor: SymbolExtractor) -> None:
        """Should extract annotated assignments."""
        code = '''
count: int = 0
name: str
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 2
        count_sym = next(s for s in symbols if s.name == "count")
        assert "int" in count_sym.signature

    def test_location_info(self, extractor: SymbolExtractor) -> None:
        """Should capture correct line numbers."""
        code = '''
def first():
    pass

def second():
    pass
'''
        symbols = extractor.extract("test.py", code)

        first = next(s for s in symbols if s.name == "first")
        second = next(s for s in symbols if s.name == "second")

        assert first.location.line_start == 2
        assert second.location.line_start == 5
        assert first.location.file_path == "test.py"

    def test_syntax_error_returns_empty(self, extractor: SymbolExtractor) -> None:
        """Should return empty list for syntax errors."""
        code = "def broken( this is not valid python"
        symbols = extractor.extract("test.py", code)
        assert symbols == []

    def test_extract_file_node(self, extractor: SymbolExtractor) -> None:
        """Should extract complete FileNode with imports and exports."""
        code = '''
"""Module docstring."""

import os
from pathlib import Path

__all__ = ["public_func", "PublicClass"]

def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    pass
'''
        node = extractor.extract_file_node("mymodule.py", code)

        assert node.path == "mymodule.py"
        assert node.language == "python"
        assert len(node.sha256) == 16

        # Check imports
        assert "os" in node.imports
        assert "pathlib" in node.imports

        # Check exports (from __all__)
        assert "public_func" in node.exports
        assert "PublicClass" in node.exports
        assert "_private_func" not in node.exports

    def test_exports_without_all(self, extractor: SymbolExtractor) -> None:
        """Should export public symbols when no __all__ defined."""
        code = '''
def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    pass

class _PrivateClass:
    pass
'''
        node = extractor.extract_file_node("mymodule.py", code)

        assert "public_func" in node.exports
        assert "PublicClass" in node.exports
        assert "_private_func" not in node.exports
        assert "_PrivateClass" not in node.exports

    def test_complex_function_signature(self, extractor: SymbolExtractor) -> None:
        """Should handle complex function signatures."""
        code = '''
def complex(
    pos_only,
    /,
    regular,
    *args,
    kw_only,
    **kwargs
) -> dict[str, Any]:
    pass
'''
        symbols = extractor.extract("test.py", code)

        assert len(symbols) == 1
        sig = symbols[0].signature
        assert "pos_only" in sig
        assert "/" in sig
        assert "*args" in sig
        assert "kw_only" in sig
        assert "**kwargs" in sig


class TestLocation:
    """Tests for the Location dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        loc = Location(
            file_path="test.py",
            line_start=10,
            line_end=20,
            column_start=4,
            column_end=50,
        )

        d = loc.to_dict()

        assert d["file_path"] == "test.py"
        assert d["line_start"] == 10
        assert d["line_end"] == 20


class TestSymbol:
    """Tests for the Symbol dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        sym = Symbol(
            name="test_func",
            kind=SymbolKind.FUNCTION,
            location=Location("test.py", 1, 5),
            signature="def test_func() -> None",
            docstring="Test function.",
        )

        d = sym.to_dict()

        assert d["name"] == "test_func"
        assert d["kind"] == "function"
        assert d["signature"] == "def test_func() -> None"

    def test_qualified_name_no_parent(self) -> None:
        """Should return name when no parent."""
        sym = Symbol(
            name="func",
            kind=SymbolKind.FUNCTION,
            location=Location("test.py", 1, 1),
        )

        assert sym.qualified_name == "func"

    def test_qualified_name_with_parent(self) -> None:
        """Should include parent in qualified name."""
        sym = Symbol(
            name="method",
            kind=SymbolKind.METHOD,
            location=Location("test.py", 1, 1),
            parent="MyClass",
        )

        assert sym.qualified_name == "MyClass.method"


class TestFileNode:
    """Tests for the FileNode dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary including symbols."""
        node = FileNode(
            path="test.py",
            language="python",
            sha256="abc123",
            symbols=[
                Symbol(
                    name="func",
                    kind=SymbolKind.FUNCTION,
                    location=Location("test.py", 1, 5),
                )
            ],
            imports=["os", "sys"],
            exports=["func"],
        )

        d = node.to_dict()

        assert d["path"] == "test.py"
        assert d["language"] == "python"
        assert len(d["symbols"]) == 1
        assert d["imports"] == ["os", "sys"]
        assert d["exports"] == ["func"]


class TestComputeFileHash:
    """Tests for the compute_file_hash function."""

    def test_consistent_hash(self) -> None:
        """Same content should produce same hash."""
        content = "def foo(): pass"
        hash1 = compute_file_hash(content)
        hash2 = compute_file_hash(content)

        assert hash1 == hash2

    def test_different_content_different_hash(self) -> None:
        """Different content should produce different hash."""
        hash1 = compute_file_hash("def foo(): pass")
        hash2 = compute_file_hash("def bar(): pass")

        assert hash1 != hash2

    def test_hash_length(self) -> None:
        """Hash should be truncated to 16 characters."""
        hash_val = compute_file_hash("some content")
        assert len(hash_val) == 16
