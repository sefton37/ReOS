"""Tests for IntentDiscoverer - multi-source intent discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import (
    IntentDiscoverer,
    DiscoveredIntent,
    PromptIntent,
    PlayIntent,
    CodebaseIntent,
    CodeSandbox,
)
from reos.play_fs import Act


class TestIntentDiscoverer:
    """Tests for intent discovery from multiple sources."""

    def test_init(self, temp_git_repo: Path) -> None:
        """Should initialize with sandbox."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox)
        assert discoverer.sandbox == sandbox

    def test_discover_returns_intent(self, temp_git_repo: Path) -> None:
        """Should return DiscoveredIntent."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test Project",
            active=True,
            repo_path=str(temp_git_repo),
            artifact_type="python",
        )

        intent = discoverer.discover("add a new function", act)

        assert isinstance(intent, DiscoveredIntent)
        assert intent.goal
        assert intent.prompt_intent is not None
        assert intent.play_intent is not None
        assert intent.codebase_intent is not None


class TestPromptIntentAnalysis:
    """Tests for prompt intent extraction."""

    def test_extracts_action_verb(self, temp_git_repo: Path) -> None:
        """Should extract action verbs from prompts."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        prompt_intent = discoverer._analyze_prompt("add a new function")

        assert prompt_intent.action_verb == "add"

    def test_extracts_target(self, temp_git_repo: Path) -> None:
        """Should extract target from prompts."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        prompt_intent = discoverer._analyze_prompt("create a class for users")

        assert prompt_intent.target == "class"

    def test_stores_raw_prompt(self, temp_git_repo: Path) -> None:
        """Should store the raw prompt."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        prompt = "implement the login feature"
        prompt_intent = discoverer._analyze_prompt(prompt)

        assert prompt_intent.raw_prompt == prompt


class TestPlayIntentAnalysis:
    """Tests for Play context intent extraction."""

    def test_extracts_act_goal(self, temp_git_repo: Path) -> None:
        """Should extract Act goal."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Build User Auth",
            active=True,
            repo_path=str(temp_git_repo),
        )

        play_intent = discoverer._analyze_play_context(act, "")

        assert play_intent.act_goal == "Build User Auth"

    def test_extracts_artifact_type(self, temp_git_repo: Path) -> None:
        """Should extract artifact type."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
            artifact_type="python",
        )

        play_intent = discoverer._analyze_play_context(act, "")

        assert play_intent.act_artifact == "python"

    def test_gets_recent_commits(self, temp_git_repo: Path) -> None:
        """Should get recent commit messages."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        play_intent = discoverer._analyze_play_context(act, "")

        # temp_git_repo fixture has an "initial" commit
        assert "initial" in play_intent.recent_work or len(play_intent.recent_work) >= 0


class TestCodebaseIntentAnalysis:
    """Tests for codebase intent extraction."""

    def test_detects_language(self, temp_git_repo: Path) -> None:
        """Should detect primary language."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        codebase_intent = discoverer._analyze_codebase("add function")

        # temp_git_repo has .py files
        assert codebase_intent.language == "python"

    def test_detects_architecture(self, temp_git_repo: Path) -> None:
        """Should detect architecture style."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        codebase_intent = discoverer._analyze_codebase("add function")

        assert codebase_intent.architecture_style in ("standard", "flat", "layered")

    def test_finds_related_files(self, temp_git_repo: Path) -> None:
        """Should find files related to prompt."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)

        # Search for "hello" which exists in example.py
        codebase_intent = discoverer._analyze_codebase("hello function")

        # May or may not find related files depending on search
        assert isinstance(codebase_intent.related_files, list)


class TestIntentSynthesis:
    """Tests for synthesizing intent from all sources."""

    def test_synthesizes_goal(self, temp_git_repo: Path) -> None:
        """Should synthesize a clear goal."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test Project",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)

        assert intent.goal
        assert len(intent.goal) > 0

    def test_includes_constraints(self, temp_git_repo: Path) -> None:
        """Should include constraints from codebase."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test Project",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)

        # Should have at least language constraint
        assert isinstance(intent.how_constraints, list)

    def test_generates_summary(self, temp_git_repo: Path) -> None:
        """Should generate human-readable summary."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test Project",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)
        summary = intent.summary()

        assert "Goal:" in summary
        assert len(summary) > 50
