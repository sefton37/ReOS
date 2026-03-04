"""Tests for the codebase index module.

Tests for CodebaseIndexer, AST parsing, and context generation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestFunctionInfo:
    """Tests for FunctionInfo dataclass."""

    def test_function_info_creation(self) -> None:
        """Should create FunctionInfo with all fields."""
        from reos.codebase_index import FunctionInfo

        info = FunctionInfo(
            name="test_func",
            params="arg1, arg2",
            docstring="A test function",
            is_async=True,
        )
        assert info.name == "test_func"
        assert info.params == "arg1, arg2"
        assert info.docstring == "A test function"
        assert info.is_async is True

    def test_function_info_defaults(self) -> None:
        """Should have sensible defaults."""
        from reos.codebase_index import FunctionInfo

        info = FunctionInfo(name="simple")
        assert info.params == ""
        assert info.docstring is None
        assert info.is_async is False

    def test_function_info_to_dict(self) -> None:
        """Should serialize to dict."""
        from reos.codebase_index import FunctionInfo

        info = FunctionInfo(name="test", params="x", is_async=True)
        d = info.to_dict()
        assert d["name"] == "test"
        assert d["params"] == "x"
        assert d["is_async"] is True


class TestClassInfo:
    """Tests for ClassInfo dataclass."""

    def test_class_info_creation(self) -> None:
        """Should create ClassInfo with all fields."""
        from reos.codebase_index import ClassInfo

        info = ClassInfo(
            name="TestClass",
            docstring="A test class",
            methods=["method1", "method2"],
            bases=["BaseClass"],
        )
        assert info.name == "TestClass"
        assert info.docstring == "A test class"
        assert info.methods == ["method1", "method2"]
        assert info.bases == ["BaseClass"]

    def test_class_info_defaults(self) -> None:
        """Should have sensible defaults."""
        from reos.codebase_index import ClassInfo

        info = ClassInfo(name="Simple")
        assert info.docstring is None
        assert info.methods == []
        assert info.bases == []

    def test_class_info_to_dict(self) -> None:
        """Should serialize to dict."""
        from reos.codebase_index import ClassInfo

        info = ClassInfo(name="Test", methods=["foo"])
        d = info.to_dict()
        assert d["name"] == "Test"
        assert d["methods"] == ["foo"]


class TestModuleSummary:
    """Tests for ModuleSummary dataclass."""

    def test_module_summary_creation(self) -> None:
        """Should create ModuleSummary with all fields."""
        from reos.codebase_index import ModuleSummary, ClassInfo, FunctionInfo

        summary = ModuleSummary(
            path="src/test.py",
            language="python",
            docstring="Test module",
            classes=[ClassInfo(name="Test")],
            functions=[FunctionInfo(name="func")],
            exports=["Test", "func"],
        )
        assert summary.path == "src/test.py"
        assert summary.language == "python"
        assert len(summary.classes) == 1
        assert len(summary.functions) == 1

    def test_module_summary_to_dict(self) -> None:
        """Should serialize to dict with nested structures."""
        from reos.codebase_index import ModuleSummary, ClassInfo

        summary = ModuleSummary(
            path="test.py",
            language="python",
            classes=[ClassInfo(name="Foo")],
        )
        d = summary.to_dict()
        assert d["path"] == "test.py"
        assert len(d["classes"]) == 1
        assert d["classes"][0]["name"] == "Foo"


class TestCodebaseIndex:
    """Tests for CodebaseIndex dataclass."""

    def test_codebase_index_creation(self) -> None:
        """Should create CodebaseIndex."""
        from reos.codebase_index import CodebaseIndex, ModuleSummary

        index = CodebaseIndex(
            version="1.0",
            hash="abc123",
            modules=[ModuleSummary(path="test.py", language="python")],
        )
        assert index.version == "1.0"
        assert index.hash == "abc123"
        assert len(index.modules) == 1

    def test_codebase_index_to_dict(self) -> None:
        """Should serialize to dict."""
        from reos.codebase_index import CodebaseIndex, ModuleSummary

        index = CodebaseIndex(
            version="1.0",
            hash="abc123",
            modules=[ModuleSummary(path="test.py", language="python")],
        )
        d = index.to_dict()
        assert d["version"] == "1.0"
        assert d["hash"] == "abc123"
        assert len(d["modules"]) == 1

    def test_codebase_index_from_dict(self) -> None:
        """Should deserialize from dict."""
        from reos.codebase_index import CodebaseIndex

        data = {
            "version": "1.0",
            "hash": "def456",
            "modules": [
                {
                    "path": "src/mod.py",
                    "language": "python",
                    "docstring": "A module",
                    "classes": [
                        {"name": "Foo", "methods": ["bar"], "bases": ["Base"]}
                    ],
                    "functions": [
                        {"name": "baz", "params": "x, y", "is_async": True}
                    ],
                }
            ],
        }
        index = CodebaseIndex.from_dict(data)
        assert index.version == "1.0"
        assert index.hash == "def456"
        assert len(index.modules) == 1
        assert index.modules[0].classes[0].name == "Foo"
        assert index.modules[0].functions[0].is_async is True

    def test_codebase_index_to_context_string(self) -> None:
        """Should generate markdown context string."""
        from reos.codebase_index import CodebaseIndex, ModuleSummary, ClassInfo, FunctionInfo

        index = CodebaseIndex(
            version="1.0",
            hash="test",
            modules=[
                ModuleSummary(
                    path="src/reos/agent.py",
                    language="python",
                    docstring="Agent module for chat",
                    classes=[ClassInfo(name="ChatAgent", methods=["respond", "detect_intent"])],
                    functions=[FunctionInfo(name="create_agent", params="db")],
                )
            ],
        )
        context = index.to_context_string()
        assert "# ReOS Codebase Reference" in context
        assert "ChatAgent" in context
        assert "respond" in context
        assert "create_agent" in context


class TestCodebaseIndexer:
    """Tests for CodebaseIndexer."""

    def test_indexer_creation(self) -> None:
        """Should create indexer with project root."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()
        assert indexer.root is not None
        assert indexer._index is None

    def test_indexer_custom_root(self, tmp_path: Path) -> None:
        """Should accept custom project root."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer(project_root=tmp_path)
        assert indexer.root == tmp_path

    def test_should_index_filters_pycache(self) -> None:
        """Should filter out __pycache__ directories."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()
        path = Path("src/reos/__pycache__/module.cpython-312.pyc")
        assert indexer._should_index(path) is False

    def test_should_index_filters_node_modules(self) -> None:
        """Should filter out node_modules."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()
        path = Path("apps/ui/node_modules/package/index.js")
        assert indexer._should_index(path) is False

    def test_should_index_filters_init(self) -> None:
        """Should filter out __init__.py files."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()
        path = Path("src/reos/__init__.py")
        assert indexer._should_index(path) is False

    def test_should_index_allows_normal_files(self) -> None:
        """Should allow normal source files."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()
        path = Path("src/reos/agent.py")
        assert indexer._should_index(path) is True

    def test_parse_python_simple_module(self, tmp_path: Path) -> None:
        """Should parse simple Python module."""
        from reos.codebase_index import CodebaseIndexer

        # Create a simple Python file
        py_file = tmp_path / "test_module.py"
        py_file.write_text('''
"""Test module docstring."""

def greet(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}"

class Greeter:
    """A greeter class."""

    def say_hello(self):
        """Say hello."""
        pass

    def say_goodbye(self):
        """Say goodbye."""
        pass
''')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_python(py_file)

        assert summary is not None
        assert summary.language == "python"
        assert summary.docstring == "Test module docstring."
        assert len(summary.functions) == 1
        assert summary.functions[0].name == "greet"
        assert len(summary.classes) == 1
        assert summary.classes[0].name == "Greeter"
        assert "say_hello" in summary.classes[0].methods

    def test_parse_python_async_functions(self, tmp_path: Path) -> None:
        """Should detect async functions."""
        from reos.codebase_index import CodebaseIndexer

        py_file = tmp_path / "async_mod.py"
        py_file.write_text('''
async def fetch_data(url: str):
    """Fetch data asynchronously."""
    pass

def sync_func():
    pass
''')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_python(py_file)

        assert summary is not None
        async_func = next(f for f in summary.functions if f.name == "fetch_data")
        sync_func = next(f for f in summary.functions if f.name == "sync_func")
        assert async_func.is_async is True
        assert sync_func.is_async is False

    def test_parse_python_skips_private(self, tmp_path: Path) -> None:
        """Should skip private functions and methods."""
        from reos.codebase_index import CodebaseIndexer

        py_file = tmp_path / "private_mod.py"
        py_file.write_text('''
def public_func():
    pass

def _private_func():
    pass

class Test:
    def public_method(self):
        pass

    def _private_method(self):
        pass
''')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_python(py_file)

        assert summary is not None
        func_names = [f.name for f in summary.functions]
        assert "public_func" in func_names
        assert "_private_func" not in func_names
        method_names = summary.classes[0].methods
        assert "public_method" in method_names
        assert "_private_method" not in method_names

    def test_parse_python_handles_syntax_error(self, tmp_path: Path) -> None:
        """Should handle syntax errors gracefully."""
        from reos.codebase_index import CodebaseIndexer

        py_file = tmp_path / "broken.py"
        py_file.write_text('def broken( # syntax error')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_python(py_file)

        assert summary is None  # Returns None on parse error

    def test_parse_typescript(self, tmp_path: Path) -> None:
        """Should parse TypeScript files."""
        from reos.codebase_index import CodebaseIndexer

        ts_file = tmp_path / "module.ts"
        ts_file.write_text('''
export function greet(name: string): string {
    return `Hello, ${name}`;
}

export async function fetchData(url: string) {
    return fetch(url);
}

export class Greeter {
    greet() {}
}

export const VERSION = "1.0";
''')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_typescript(ts_file)

        assert summary is not None
        assert summary.language == "typescript"
        assert len(summary.exports) >= 3
        assert "greet" in summary.exports
        assert "Greeter" in summary.exports
        # Check async detection
        async_func = next((f for f in summary.functions if f.name == "fetchData"), None)
        assert async_func is not None
        assert async_func.is_async is True

    def test_parse_rust(self, tmp_path: Path) -> None:
        """Should parse Rust files."""
        from reos.codebase_index import CodebaseIndexer

        rs_file = tmp_path / "lib.rs"
        rs_file.write_text('''
//! Module documentation

pub fn greet(name: &str) -> String {
    format!("Hello, {}", name)
}

pub async fn fetch_data(url: &str) -> Result<String, Error> {
    Ok(String::new())
}

pub struct Greeter {
    name: String,
}

pub enum Status {
    Active,
    Inactive,
}
''')

        indexer = CodebaseIndexer(project_root=tmp_path)
        summary = indexer._parse_rust(rs_file)

        assert summary is not None
        assert summary.language == "rust"
        assert summary.docstring == "Module documentation"
        func_names = [f.name for f in summary.functions]
        assert "greet" in func_names
        assert "fetch_data" in func_names
        class_names = [c.name for c in summary.classes]
        assert "Greeter" in class_names
        assert "Status" in class_names


class TestGetCodebaseContext:
    """Tests for the get_codebase_context function."""

    def test_get_codebase_context_returns_string(self) -> None:
        """Should return a non-empty string."""
        from reos.codebase_index import get_codebase_context

        context = get_codebase_context()
        assert isinstance(context, str)
        assert len(context) > 0
        assert "ReOS" in context

    def test_get_codebase_context_force_refresh(self) -> None:
        """Should support force refresh."""
        from reos.codebase_index import get_codebase_context

        # First call
        context1 = get_codebase_context()
        # Force refresh
        context2 = get_codebase_context(force_refresh=True)
        # Both should be valid
        assert len(context1) > 0
        assert len(context2) > 0

    def test_get_codebase_index_returns_index(self) -> None:
        """Should return CodebaseIndex object."""
        from reos.codebase_index import get_codebase_index, CodebaseIndex

        index = get_codebase_index()
        assert isinstance(index, CodebaseIndex)
        assert len(index.modules) > 0


class TestCaching:
    """Tests for caching behavior."""

    def test_cache_uses_hash(self, tmp_path: Path) -> None:
        """Should use hash for cache invalidation."""
        from reos.codebase_index import CodebaseIndexer

        # Create a Python file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        py_file = src_dir / "test.py"
        py_file.write_text('def foo(): pass')

        indexer = CodebaseIndexer(project_root=tmp_path)
        hash1 = indexer._compute_hash()

        # Modify the file
        py_file.write_text('def foo(): pass\ndef bar(): pass')
        hash2 = indexer._compute_hash()

        # Hashes should differ
        assert hash1 != hash2

    def test_indexer_caches_result(self) -> None:
        """Should cache the index after first build."""
        from reos.codebase_index import CodebaseIndexer

        indexer = CodebaseIndexer()

        # First call builds
        index1 = indexer.get_index()
        assert indexer._index is not None

        # Second call should have same hash (content equality)
        index2 = indexer.get_index()
        assert index1.hash == index2.hash  # Same content
