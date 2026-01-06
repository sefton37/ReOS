"""Tests for CodePlanner - code task planning for Code Mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import (
    CodePlanner,
    CodeSandbox,
    CodeStepType,
    CodeTaskPlan,
    ImpactLevel,
)
from reos.play_fs import Act


class TestCodePlannerInit:
    """Tests for CodePlanner initialization."""

    def test_init_with_sandbox(self, temp_git_repo: Path) -> None:
        """Should initialize with a CodeSandbox."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        assert planner.sandbox == sandbox

    def test_init_without_ollama(self, temp_git_repo: Path) -> None:
        """Should work without Ollama client."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox, llm=None)

        assert planner._llm is None


class TestCreatePlan:
    """Tests for plan creation."""

    def test_creates_plan_without_llm(self, temp_git_repo: Path) -> None:
        """Should create exploration plan without LLM."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("add a new function", act)

        assert isinstance(plan, CodeTaskPlan)
        assert plan.id.startswith("plan-")
        assert plan.goal == "add a new function"
        assert len(plan.steps) >= 1

    def test_plan_has_required_fields(self, temp_git_repo: Path) -> None:
        """Plan should have all required fields."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("refactor the code", act)

        assert plan.id is not None
        assert plan.goal is not None
        assert plan.steps is not None
        assert plan.estimated_impact is not None
        assert plan.created_at is not None
        assert plan.approved is False
        assert plan.rejected is False

    def test_exploration_plan_has_read_step(self, temp_git_repo: Path) -> None:
        """Exploration plan should include file reading step."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("understand the codebase", act)

        step_types = [s.type for s in plan.steps]
        assert CodeStepType.READ_FILES in step_types

    def test_exploration_plan_has_analyze_step(self, temp_git_repo: Path) -> None:
        """Exploration plan should include analysis step."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("fix the bug", act)

        step_types = [s.type for s in plan.steps]
        assert CodeStepType.ANALYZE in step_types


class TestCreateFixPlan:
    """Tests for fix plan creation from errors."""

    def test_creates_fix_plan_from_error(self, temp_git_repo: Path) -> None:
        """Should create fix plan from error output."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        error = '''
        Traceback (most recent call last):
          File "src/reos/example.py", line 10, in foo
            return bar()
        NameError: name 'bar' is not defined
        '''

        plan = planner.create_fix_plan(error)

        assert isinstance(plan, CodeTaskPlan)
        assert "error" in plan.goal.lower() or "fix" in plan.goal.lower()

    def test_fix_plan_extracts_file_references(self, temp_git_repo: Path) -> None:
        """Should extract file paths from error output."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        error = '''
        File "tests/test_example.py", line 5
        File "src/main.py", line 42
        '''

        plan = planner.create_fix_plan(error)

        # Should have context files from error
        assert len(plan.context_files) >= 1

    def test_fix_plan_includes_verify_step(self, temp_git_repo: Path) -> None:
        """Fix plan should include verification step."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        plan = planner.create_fix_plan("TypeError: expected str")

        step_types = [s.type for s in plan.steps]
        assert CodeStepType.RUN_TESTS in step_types


class TestPlanSummary:
    """Tests for plan summary generation."""

    def test_summary_includes_goal(self, temp_git_repo: Path) -> None:
        """Summary should include the goal."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("add user authentication", act)
        summary = plan.summary()

        assert "add user authentication" in summary

    def test_summary_includes_steps(self, temp_git_repo: Path) -> None:
        """Summary should list all steps."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("refactor", act)
        summary = plan.summary()

        # Should have numbered steps
        assert "1." in summary
        assert "Steps" in summary

    def test_summary_includes_impact(self, temp_git_repo: Path) -> None:
        """Summary should include impact level."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("small fix", act)
        summary = plan.summary()

        assert "impact" in summary.lower()


class TestCodeStep:
    """Tests for CodeStep dataclass."""

    def test_step_has_id(self, temp_git_repo: Path) -> None:
        """Each step should have a unique ID."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("test", act)

        for step in plan.steps:
            assert step.id.startswith("step-")

    def test_step_status_defaults_to_pending(self, temp_git_repo: Path) -> None:
        """Step status should default to pending."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("test", act)

        for step in plan.steps:
            assert step.status == "pending"


class TestImpactLevel:
    """Tests for impact level assessment."""

    def test_default_impact_is_minor(self, temp_git_repo: Path) -> None:
        """Default impact should be minor for exploration plans."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox, llm=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        plan = planner.create_plan("look at files", act)

        assert plan.estimated_impact == ImpactLevel.MINOR


class TestRepoContext:
    """Tests for repository context gathering."""

    def test_gathers_structure(self, temp_git_repo: Path) -> None:
        """Should gather repository structure."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        context = planner._gather_repo_context()

        assert "structure" in context

    def test_gathers_git_status(self, temp_git_repo: Path) -> None:
        """Should gather git status."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        context = planner._gather_repo_context()

        assert "git_status" in context

    def test_finds_python_files(self, temp_git_repo: Path) -> None:
        """Should find Python files in repo."""
        sandbox = CodeSandbox(temp_git_repo)
        planner = CodePlanner(sandbox=sandbox)

        context = planner._gather_repo_context()

        assert "python_files" in context
        # temp_git_repo fixture has example.py
        assert len(context["python_files"]) >= 1
