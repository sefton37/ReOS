"""Tests for the RepoMap class."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode.repo_map import RepoMap, IndexResult, FileContext
from reos.code_mode.sandbox import CodeSandbox
from reos.code_mode.symbol_extractor import SymbolKind
from reos.db import Database


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with sample files."""
    # Initialize git repo
    (tmp_path / ".git").mkdir()

    # Create package structure
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text(
        '''"""My application package."""

from .main import run

__all__ = ["run"]
'''
    )

    (src / "main.py").write_text(
        '''"""Main module."""

from .utils import helper
from .models import User

def run():
    """Run the application."""
    user = User(name="test")
    return helper(user)

def other_func():
    """Another function."""
    pass
'''
    )

    (src / "utils.py").write_text(
        '''"""Utility functions."""

def helper(user):
    """Help with something."""
    return f"Hello, {user.name}"

def format_name(name: str) -> str:
    """Format a name."""
    return name.title()

MAX_RETRIES = 3
'''
    )

    (src / "models.py").write_text(
        '''"""Data models."""

from dataclasses import dataclass

@dataclass
class User:
    """A user model."""
    name: str
    email: str = ""

@dataclass
class Product:
    """A product model."""
    id: int
    name: str
'''
    )

    return tmp_path


@pytest.fixture
def db() -> Database:
    """Create an in-memory database."""
    db = Database(":memory:")
    db.migrate()
    return db


@pytest.fixture
def sandbox(temp_repo: Path) -> CodeSandbox:
    """Create a CodeSandbox for the temp repo."""
    return CodeSandbox(temp_repo)


@pytest.fixture
def repo_map(sandbox: CodeSandbox, db: Database) -> RepoMap:
    """Create a RepoMap instance."""
    return RepoMap(sandbox, db)


class TestIndexing:
    """Tests for repository indexing."""

    def test_index_repo(self, repo_map: RepoMap) -> None:
        """Should index all Python files in the repository."""
        result = repo_map.index_repo()

        assert isinstance(result, IndexResult)
        assert result.total_files == 4  # __init__, main, utils, models
        assert result.indexed == 4
        assert result.errors == []

    def test_index_repo_incremental(self, repo_map: RepoMap, temp_repo: Path) -> None:
        """Should skip unchanged files on re-index."""
        # First index
        result1 = repo_map.index_repo()
        assert result1.indexed == 4

        # Second index without changes
        result2 = repo_map.index_repo()
        assert result2.indexed == 0
        assert result2.skipped == 4

        # Modify a file
        (temp_repo / "src" / "myapp" / "utils.py").write_text("# modified\n")

        # Third index should only index changed file
        result3 = repo_map.index_repo()
        assert result3.indexed == 1
        assert result3.skipped == 3

    def test_index_repo_force(self, repo_map: RepoMap) -> None:
        """Should re-index all files when force=True."""
        repo_map.index_repo()

        result = repo_map.index_repo(force=True)
        assert result.indexed == 4
        assert result.skipped == 0


class TestSymbolSearch:
    """Tests for symbol searching."""

    def test_find_symbol(self, repo_map: RepoMap) -> None:
        """Should find symbols by name."""
        repo_map.index_repo()

        symbols = repo_map.find_symbol("run")

        assert len(symbols) >= 1
        assert any(s.name == "run" for s in symbols)

    def test_find_symbol_exact(self, repo_map: RepoMap) -> None:
        """Should find symbols with exact name match."""
        repo_map.index_repo()

        symbols = repo_map.find_symbol_exact("User")

        assert len(symbols) == 1
        assert symbols[0].name == "User"
        assert symbols[0].kind == SymbolKind.CLASS

    def test_find_symbol_with_kind_filter(self, repo_map: RepoMap) -> None:
        """Should filter symbols by kind."""
        repo_map.index_repo()

        # Find only classes
        classes = repo_map.find_symbol("", kind="class")

        assert len(classes) >= 2  # User and Product
        assert all(s.kind == SymbolKind.CLASS for s in classes)

    def test_find_symbol_partial_match(self, repo_map: RepoMap) -> None:
        """Should find symbols with partial name match."""
        repo_map.index_repo()

        symbols = repo_map.find_symbol("format")

        assert len(symbols) >= 1
        assert any(s.name == "format_name" for s in symbols)


class TestDependencies:
    """Tests for dependency tracking."""

    def test_find_callers(self, repo_map: RepoMap) -> None:
        """Should find files that import a symbol."""
        repo_map.index_repo()

        callers = repo_map.find_callers("helper", "src/myapp/utils.py")

        # main.py imports helper from utils
        assert len(callers) >= 1
        assert any("main.py" in c.file_path for c in callers)

    def test_get_file_context(self, repo_map: RepoMap) -> None:
        """Should get context for a file."""
        repo_map.index_repo()

        context = repo_map.get_file_context("src/myapp/main.py")

        assert context is not None
        assert context.file_path == "src/myapp/main.py"
        assert len(context.symbols) >= 2  # run and other_func
        assert len(context.dependencies) >= 2  # utils and models

    def test_get_file_context_not_indexed(self, repo_map: RepoMap) -> None:
        """Should return None for non-indexed files."""
        context = repo_map.get_file_context("nonexistent.py")
        assert context is None


class TestRelevantContext:
    """Tests for building relevant context."""

    def test_get_relevant_context(self, repo_map: RepoMap) -> None:
        """Should build relevant context for a query."""
        repo_map.index_repo()

        context = repo_map.get_relevant_context("how does the User model work")

        assert "User" in context
        assert len(context) > 0

    def test_get_relevant_context_with_budget(self, repo_map: RepoMap) -> None:
        """Should respect token budget."""
        repo_map.index_repo()

        # Very small budget
        context = repo_map.get_relevant_context("find all functions", token_budget=50)

        # Should be limited in size
        assert len(context) < 500  # Rough estimate

    def test_get_relevant_context_no_matches(self, repo_map: RepoMap) -> None:
        """Should return message when no matches found."""
        repo_map.index_repo()

        context = repo_map.get_relevant_context("xyznonexistent123")

        assert "No relevant code context found" in context


class TestStats:
    """Tests for index statistics."""

    def test_get_stats(self, repo_map: RepoMap) -> None:
        """Should return index statistics."""
        repo_map.index_repo()

        stats = repo_map.get_stats()

        assert stats["files"] == 4
        assert stats["symbols"] > 0
        assert stats["dependencies"] >= 0
        assert stats["embeddings"] == 0  # No embeddings yet


class TestClear:
    """Tests for clearing the index."""

    def test_clear_index(self, repo_map: RepoMap) -> None:
        """Should clear all index data."""
        repo_map.index_repo()
        assert repo_map.get_stats()["files"] == 4

        repo_map.clear_index()

        stats = repo_map.get_stats()
        assert stats["files"] == 0
        assert stats["symbols"] == 0
        assert stats["dependencies"] == 0


class TestIndexResult:
    """Tests for IndexResult dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        result = IndexResult(
            total_files=10,
            indexed=8,
            skipped=2,
            errors=["error1"],
        )

        d = result.to_dict()

        assert d["total_files"] == 10
        assert d["indexed"] == 8
        assert d["skipped"] == 2
        assert d["errors"] == ["error1"]


class TestFileContext:
    """Tests for FileContext dataclass."""

    def test_to_dict(self, repo_map: RepoMap) -> None:
        """Should serialize to dictionary."""
        repo_map.index_repo()

        context = repo_map.get_file_context("src/myapp/main.py")

        d = context.to_dict()

        assert d["file_path"] == "src/myapp/main.py"
        assert isinstance(d["symbols"], list)
        assert isinstance(d["imports"], list)
        assert isinstance(d["dependencies"], list)
