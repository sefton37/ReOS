"""Tests for dependency graph builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode.dependency_graph import (
    DependencyGraphBuilder,
    ImportInfo,
)


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary repository structure."""
    # Create package structure
    src = tmp_path / "src" / "mypackage"
    src.mkdir(parents=True)

    # Main module
    (src / "__init__.py").write_text("from .core import main\n")
    (src / "core.py").write_text(
        """
from .utils import helper
from .models import User

def main():
    return helper()
"""
    )
    (src / "utils.py").write_text(
        """
import os
from pathlib import Path

def helper():
    return "helper"
"""
    )
    (src / "models.py").write_text(
        """
from dataclasses import dataclass

@dataclass
class User:
    name: str
"""
    )

    # Subpackage
    sub = src / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "handler.py").write_text(
        """
from ..core import main
from ..models import User

def handle():
    main()
"""
    )

    return tmp_path


class TestImportAnalysis:
    """Tests for analyzing import statements."""

    @pytest.fixture
    def builder(self, tmp_path: Path) -> DependencyGraphBuilder:
        """Create a DependencyGraphBuilder."""
        return DependencyGraphBuilder(tmp_path)

    def test_simple_import(self, builder: DependencyGraphBuilder) -> None:
        """Should detect simple import statements."""
        code = "import os"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == "os"
        assert imports[0].import_type == "import"
        assert imports[0].level == 0

    def test_import_with_alias(self, builder: DependencyGraphBuilder) -> None:
        """Should detect imports with aliases."""
        code = "import numpy as np"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == "numpy"
        assert imports[0].symbols == ["np"]

    def test_from_import(self, builder: DependencyGraphBuilder) -> None:
        """Should detect from X import Y statements."""
        code = "from pathlib import Path, PurePath"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == "pathlib"
        assert imports[0].import_type == "from_import"
        assert "Path" in imports[0].symbols
        assert "PurePath" in imports[0].symbols

    def test_relative_import_single_dot(self, builder: DependencyGraphBuilder) -> None:
        """Should detect relative imports with single dot."""
        code = "from .utils import helper"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == "utils"
        assert imports[0].level == 1
        assert "helper" in imports[0].symbols

    def test_relative_import_double_dot(self, builder: DependencyGraphBuilder) -> None:
        """Should detect relative imports with double dots."""
        code = "from ..core import main"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == "core"
        assert imports[0].level == 2

    def test_relative_import_no_module(self, builder: DependencyGraphBuilder) -> None:
        """Should handle 'from . import X' syntax."""
        code = "from . import core"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert imports[0].module == ""
        assert imports[0].level == 1
        assert "core" in imports[0].symbols

    def test_star_import(self, builder: DependencyGraphBuilder) -> None:
        """Should detect star imports."""
        code = "from os.path import *"
        imports = builder.analyze_imports(code)

        assert len(imports) == 1
        assert "*" in imports[0].symbols

    def test_multiple_imports(self, builder: DependencyGraphBuilder) -> None:
        """Should detect multiple import statements."""
        code = """
import os
import sys
from pathlib import Path
from .utils import helper
"""
        imports = builder.analyze_imports(code)

        assert len(imports) == 4

    def test_syntax_error_returns_empty(self, builder: DependencyGraphBuilder) -> None:
        """Should return empty list for syntax errors."""
        code = "import this is not valid python"
        imports = builder.analyze_imports(code)

        assert imports == []


class TestImportResolution:
    """Tests for resolving imports to file paths."""

    def test_resolve_absolute_import(self, temp_repo: Path) -> None:
        """Should resolve absolute import to file."""
        builder = DependencyGraphBuilder(temp_repo)

        # Import of a module that exists
        import_info = ImportInfo(module="mypackage.core", import_type="import")
        resolved = builder.resolve_import(import_info, "test.py")

        assert resolved == "src/mypackage/core.py"

    def test_resolve_absolute_import_package(self, temp_repo: Path) -> None:
        """Should resolve import of package to __init__.py."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(module="mypackage", import_type="import")
        resolved = builder.resolve_import(import_info, "test.py")

        assert resolved == "src/mypackage/__init__.py"

    def test_resolve_relative_import_single_level(self, temp_repo: Path) -> None:
        """Should resolve relative import with single dot."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(
            module="utils",
            import_type="from_import",
            level=1,
            symbols=["helper"],
        )
        # From core.py, import .utils
        resolved = builder.resolve_import(import_info, "src/mypackage/core.py")

        assert resolved == "src/mypackage/utils.py"

    def test_resolve_relative_import_parent(self, temp_repo: Path) -> None:
        """Should resolve relative import going to parent package."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(
            module="core",
            import_type="from_import",
            level=2,  # ..
            symbols=["main"],
        )
        # From sub/handler.py, import ..core
        resolved = builder.resolve_import(import_info, "src/mypackage/sub/handler.py")

        assert resolved == "src/mypackage/core.py"

    def test_resolve_external_import_returns_none(self, temp_repo: Path) -> None:
        """Should return None for external (non-repo) imports."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(module="os", import_type="import")
        resolved = builder.resolve_import(import_info, "test.py")

        assert resolved is None

    def test_resolve_nonexistent_module_returns_none(self, temp_repo: Path) -> None:
        """Should return None for imports that don't exist in repo."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(module="mypackage.nonexistent", import_type="import")
        resolved = builder.resolve_import(import_info, "test.py")

        assert resolved is None


class TestGetDependencies:
    """Tests for getting file dependencies."""

    def test_get_dependencies(self, temp_repo: Path) -> None:
        """Should return all dependencies for a file."""
        builder = DependencyGraphBuilder(temp_repo)

        content = (temp_repo / "src" / "mypackage" / "core.py").read_text()
        deps = builder.get_dependencies("src/mypackage/core.py", content)

        # Should find utils and models (relative imports)
        target_files = [dep[0] for dep in deps]
        assert "src/mypackage/utils.py" in target_files
        assert "src/mypackage/models.py" in target_files

    def test_get_dependencies_with_external(self, temp_repo: Path) -> None:
        """Should not include external dependencies."""
        builder = DependencyGraphBuilder(temp_repo)

        content = (temp_repo / "src" / "mypackage" / "utils.py").read_text()
        deps = builder.get_dependencies("src/mypackage/utils.py", content)

        # os and pathlib are external, should not be in deps
        target_files = [dep[0] for dep in deps]
        assert len(target_files) == 0


class TestGetDependents:
    """Tests for finding dependent files."""

    def test_get_dependents(self, temp_repo: Path) -> None:
        """Should find all files that depend on a given file."""
        builder = DependencyGraphBuilder(temp_repo)

        # Read all files
        file_contents = {}
        for py_file in (temp_repo / "src" / "mypackage").rglob("*.py"):
            rel_path = str(py_file.relative_to(temp_repo))
            file_contents[rel_path] = py_file.read_text()

        # Find who depends on utils.py
        dependents = builder.get_dependents("src/mypackage/utils.py", file_contents)

        # core.py imports utils
        assert "src/mypackage/core.py" in dependents

    def test_get_dependents_multiple(self, temp_repo: Path) -> None:
        """Should find multiple dependents."""
        builder = DependencyGraphBuilder(temp_repo)

        # Read all files
        file_contents = {}
        for py_file in (temp_repo / "src" / "mypackage").rglob("*.py"):
            rel_path = str(py_file.relative_to(temp_repo))
            file_contents[rel_path] = py_file.read_text()

        # Find who depends on core.py
        dependents = builder.get_dependents("src/mypackage/core.py", file_contents)

        # __init__.py and sub/handler.py both import core
        assert "src/mypackage/__init__.py" in dependents
        assert "src/mypackage/sub/handler.py" in dependents


class TestCaching:
    """Tests for file resolution caching."""

    def test_cache_hit(self, temp_repo: Path) -> None:
        """Should use cache for repeated lookups."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(module="mypackage.core", import_type="import")

        # First call
        result1 = builder.resolve_import(import_info, "test.py")
        assert result1 is not None

        # Modify cache to verify it's being used
        builder._file_cache["mypackage/core"] = Path("cached/path.py")

        # Second call should use cache
        result2 = builder.resolve_import(import_info, "test.py")
        assert result2 == "cached/path.py"

    def test_clear_cache(self, temp_repo: Path) -> None:
        """Should be able to clear the cache."""
        builder = DependencyGraphBuilder(temp_repo)

        import_info = ImportInfo(module="mypackage.core", import_type="import")
        builder.resolve_import(import_info, "test.py")

        assert len(builder._file_cache) > 0

        builder.clear_cache()

        assert len(builder._file_cache) == 0
