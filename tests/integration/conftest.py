"""Fixtures for integration tests."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


def run_git(repo: Path, args: list[str]) -> str:
    """Run git command with GPG signing disabled."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@pytest.fixture
def isolated_db_and_play(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate both DB and play storage to temp directory."""
    import reos.db as db_mod

    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path))

    db_path = tmp_path / "reos-test.db"
    db_mod._db_instance = db_mod.Database(db_path=db_path)
    db_mod._db_instance.migrate()
    try:
        yield tmp_path
    finally:
        if db_mod._db_instance is not None:
            db_mod._db_instance.close()
        db_mod._db_instance = None


@pytest.fixture
def integration_git_repo(tmp_path: Path) -> Path:
    """Create a git repo with realistic structure for integration testing."""
    repo = tmp_path / "project"
    repo.mkdir(parents=True)

    run_git(repo, ["init"])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "Integration Test"])

    # Create project structure
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        '''"""Main entry point."""

def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )

    (repo / "src" / "utils.py").write_text(
        '''"""Utility functions."""

def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
''',
        encoding="utf-8",
    )

    (repo / "tests").mkdir()
    (repo / "tests" / "test_utils.py").write_text(
        '''"""Tests for utils."""

from src.utils import add, multiply

def test_add():
    assert add(1, 2) == 3

def test_multiply():
    assert multiply(2, 3) == 6
''',
        encoding="utf-8",
    )

    (repo / "docs").mkdir()
    (repo / "docs" / "tech-roadmap.md").write_text(
        """# Tech Roadmap

## Phase 1: Core Features
- Implement main entry point: src/main.py
- Add utility functions: src/utils.py

## Phase 2: Testing
- Add unit tests: tests/test_utils.py
""",
        encoding="utf-8",
    )

    (repo / "ReOS_charter.md").write_text(
        """# Project Charter

## Purpose
A demonstration project for integration testing.

## Key Files
- src/main.py: Entry point
- src/utils.py: Utilities
""",
        encoding="utf-8",
    )

    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "Initial commit with project structure"])

    return repo


@pytest.fixture
def configured_integration_repo(
    integration_git_repo: Path,
    isolated_db_and_play: Path,
) -> Path:
    """Configure the integration git repo as the active repo."""
    from reos.db import get_db

    db = get_db()
    db.set_state(key="repo_path", value=str(integration_git_repo))
    return integration_git_repo


class MockOllamaClient:
    """Mock Ollama client for deterministic integration tests."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []
        self._default_tool_response = json.dumps({"tool_calls": []})
        self._default_answer = "I analyzed the repository and found no issues."

    def set_tool_response(self, tool_calls: list[dict[str, Any]]) -> None:
        """Set the tool selection response."""
        self._default_tool_response = json.dumps({"tool_calls": tool_calls})

    def set_answer(self, answer: str) -> None:
        """Set the final answer response."""
        self._default_answer = answer

    def chat_json(self, *, system: str, user: str, temperature: float, top_p: float) -> str:
        self.calls.append(
            {"type": "json", "system": system, "user": user, "temperature": temperature, "top_p": top_p}
        )
        return self._default_tool_response

    def chat_text(self, *, system: str, user: str, temperature: float, top_p: float) -> str:
        self.calls.append(
            {"type": "text", "system": system, "user": user, "temperature": temperature, "top_p": top_p}
        )
        return self._default_answer


@pytest.fixture
def mock_ollama() -> MockOllamaClient:
    """Create a mock Ollama client."""
    return MockOllamaClient()


class MockCommitReviewer:
    """Mock commit reviewer for deterministic tests."""

    def __init__(self, review_text: str = "LGTM. No issues found.") -> None:
        self.review_text = review_text
        self.calls: list[Any] = []

    def review(self, input_data: Any) -> str:
        self.calls.append(input_data)
        return self.review_text


@pytest.fixture
def mock_reviewer() -> MockCommitReviewer:
    """Create a mock commit reviewer."""
    return MockCommitReviewer()
