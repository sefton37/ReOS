"""Code Mode planning - creates step-by-step plans for code modifications.

The planner analyzes code tasks and generates structured plans that can be
reviewed and approved before execution.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.sandbox import CodeSandbox
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


class CodeStepType(Enum):
    """Types of steps in a code task plan."""

    READ_FILES = "read_files"       # Gather context by reading files
    ANALYZE = "analyze"             # Understand structure/patterns
    PLAN = "plan"                   # Design changes
    WRITE_FILE = "write_file"       # Create or overwrite file
    EDIT_FILE = "edit_file"         # Modify existing file
    CREATE_FILE = "create_file"     # Create new file
    DELETE_FILE = "delete_file"     # Remove file
    RUN_COMMAND = "run_command"     # Shell command in repo
    RUN_TESTS = "run_tests"         # Execute test suite
    VERIFY = "verify"               # Confirm changes work


class ImpactLevel(Enum):
    """Estimated impact of a code change."""

    MINOR = "minor"           # Small change, single file, low risk
    MODERATE = "moderate"     # Multiple files or significant logic change
    MAJOR = "major"           # Architectural change, high risk


@dataclass
class CodeStep:
    """A single step in a code task plan."""

    id: str
    type: CodeStepType
    description: str
    # Step-specific details
    target_path: str | None = None      # File path for file operations
    command: str | None = None          # Command for RUN_COMMAND/RUN_TESTS
    old_content: str | None = None      # For EDIT_FILE - text to replace
    new_content: str | None = None      # For WRITE/EDIT/CREATE - new content
    glob_pattern: str | None = None     # For READ_FILES - pattern to match
    # Execution state
    status: str = "pending"             # pending, in_progress, completed, failed
    result: str | None = None           # Result message after execution
    error: str | None = None            # Error message if failed


@dataclass
class CodeTaskPlan:
    """A complete plan for a code modification task."""

    id: str
    goal: str
    steps: list[CodeStep]
    context_files: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    files_to_delete: list[str] = field(default_factory=list)
    estimated_impact: ImpactLevel = ImpactLevel.MINOR
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Approval state
    approved: bool = False
    rejected: bool = False
    rejection_reason: str | None = None

    def summary(self) -> str:
        """Generate human-readable summary of the plan."""
        lines = [f"## Plan: {self.goal}", ""]

        if self.context_files:
            lines.append(f"**Files to read:** {', '.join(self.context_files)}")
        if self.files_to_modify:
            lines.append(f"**Files to modify:** {', '.join(self.files_to_modify)}")
        if self.files_to_create:
            lines.append(f"**Files to create:** {', '.join(self.files_to_create)}")
        if self.files_to_delete:
            lines.append(f"**Files to delete:** {', '.join(self.files_to_delete)}")

        lines.append(f"**Estimated impact:** {self.estimated_impact.value}")
        lines.append("")
        lines.append("### Steps:")

        for i, step in enumerate(self.steps, 1):
            status_icon = {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(
                step.status, "🔄"
            )
            lines.append(f"{i}. {status_icon} [{step.type.value}] {step.description}")
            if step.target_path:
                lines.append(f"   → {step.target_path}")

        return "\n".join(lines)


def _generate_step_id() -> str:
    """Generate unique step ID."""
    return f"step-{uuid.uuid4().hex[:8]}"


def _generate_plan_id() -> str:
    """Generate unique plan ID."""
    return f"plan-{uuid.uuid4().hex[:12]}"


class CodePlanner:
    """Creates plans for code modifications.

    The planner uses the sandbox to explore the repository and the LLM
    to generate intelligent step-by-step plans for code changes.
    """

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
    ) -> None:
        """Initialize planner.

        Args:
            sandbox: CodeSandbox for repository access.
            llm: Optional LLM provider for LLM-based planning.
        """
        self.sandbox = sandbox
        self._llm = llm

    def create_plan(
        self,
        request: str,
        act: Act,
    ) -> CodeTaskPlan:
        """Create a plan for the given code request.

        Args:
            request: User's code modification request.
            act: The active Act with repository assignment.

        Returns:
            CodeTaskPlan with steps to accomplish the goal.
        """
        # Gather repository context
        repo_context = self._gather_repo_context()

        # Use LLM to generate plan if available
        if self._llm is not None:
            plan = self._generate_plan_with_llm(request, act, repo_context)
            if plan is not None:
                return plan

        # Fallback: create a simple exploration plan
        return self._create_exploration_plan(request, act)

    def create_fix_plan(
        self,
        error_output: str,
        original_plan: CodeTaskPlan | None = None,
    ) -> CodeTaskPlan:
        """Create a plan to fix test/build failures.

        Args:
            error_output: The error message or test output.
            original_plan: Optional original plan that led to the error.

        Returns:
            CodeTaskPlan to fix the errors.
        """
        # Extract file references from error output
        files_mentioned = self._extract_file_references(error_output)

        steps = [
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.READ_FILES,
                description="Read files mentioned in error output",
                glob_pattern=None,  # Will read specific files
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.ANALYZE,
                description="Analyze error and identify root cause",
            ),
        ]

        # Add read steps for each mentioned file
        for file_path in files_mentioned[:5]:  # Limit to 5 files
            steps.append(
                CodeStep(
                    id=_generate_step_id(),
                    type=CodeStepType.READ_FILES,
                    description=f"Read {file_path}",
                    target_path=file_path,
                )
            )

        steps.extend([
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.PLAN,
                description="Design fix based on error analysis",
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.RUN_TESTS,
                description="Verify fix by running tests",
            ),
        ])

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=f"Fix error: {error_output[:100]}...",
            steps=steps,
            context_files=files_mentioned,
            estimated_impact=ImpactLevel.MINOR,
        )

    def _gather_repo_context(self) -> dict[str, Any]:
        """Gather context about the repository."""
        context: dict[str, Any] = {}

        try:
            # Get directory structure
            context["structure"] = self.sandbox.get_structure(max_depth=2)

            # Get git status
            context["git_status"] = self.sandbox.git_status()

            # Find key files
            context["python_files"] = self.sandbox.find_files("**/*.py")[:20]
            context["test_files"] = self.sandbox.find_files("**/test_*.py")[:10]
            context["config_files"] = self.sandbox.find_files(
                "**/pyproject.toml"
            ) + self.sandbox.find_files("**/setup.py")

        except Exception as e:
            logger.warning("Error gathering repo context: %s", e)

        return context

    def _generate_plan_with_llm(
        self,
        request: str,
        act: Act,
        repo_context: dict[str, Any],
    ) -> CodeTaskPlan | None:
        """Use LLM to generate a structured plan."""
        if self._llm is None:
            return None

        system_prompt = """You are a code planning assistant. Given a user request and repository context,
create a structured plan with specific steps.

Output a JSON object with this structure:
{
    "goal": "Brief description of the goal",
    "impact": "minor" | "moderate" | "major",
    "context_files": ["file1.py", "file2.py"],
    "files_to_modify": ["existing_file.py"],
    "files_to_create": ["new_file.py"],
    "steps": [
        {
            "type": "read_files" | "analyze" | "write_file" | "edit_file" | "create_file" | "run_command" | "run_tests" | "verify",
            "description": "What this step does",
            "target_path": "path/to/file.py",  // for file operations
            "command": "pytest tests/"  // for run_command/run_tests
        }
    ]
}

Repository context:
- Artifact type: {artifact_type}
- Python files: {python_files}
- Test files: {test_files}
- Git status: {git_clean}

Be specific about which files to read and modify. Keep plans focused and minimal."""

        try:
            # Format context for prompt
            python_files = ", ".join(repo_context.get("python_files", [])[:10])
            test_files = ", ".join(repo_context.get("test_files", [])[:5])
            git_status = repo_context.get("git_status")
            git_clean = "clean" if git_status and git_status.clean else "has changes"

            response = self._llm.chat_json(
                system=system_prompt.format(
                    artifact_type=act.artifact_type or "unknown",
                    python_files=python_files or "none found",
                    test_files=test_files or "none found",
                    git_clean=git_clean,
                ),
                user=request,
                temperature=0.2,
            )

            plan_data = json.loads(response)
            return self._parse_llm_plan(plan_data)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse LLM plan: %s", e)
            return None
        except Exception as e:
            logger.warning("LLM planning failed: %s", e)
            return None

    def _parse_llm_plan(self, data: dict[str, Any]) -> CodeTaskPlan:
        """Parse LLM response into a CodeTaskPlan."""
        steps = []
        for step_data in data.get("steps", []):
            step_type_str = step_data.get("type", "analyze")
            try:
                step_type = CodeStepType(step_type_str)
            except ValueError:
                step_type = CodeStepType.ANALYZE

            steps.append(
                CodeStep(
                    id=_generate_step_id(),
                    type=step_type,
                    description=step_data.get("description", ""),
                    target_path=step_data.get("target_path"),
                    command=step_data.get("command"),
                )
            )

        impact_str = data.get("impact", "minor")
        try:
            impact = ImpactLevel(impact_str)
        except ValueError:
            impact = ImpactLevel.MINOR

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=data.get("goal", "Code modification"),
            steps=steps,
            context_files=data.get("context_files", []),
            files_to_modify=data.get("files_to_modify", []),
            files_to_create=data.get("files_to_create", []),
            files_to_delete=data.get("files_to_delete", []),
            estimated_impact=impact,
        )

    def _create_exploration_plan(
        self,
        request: str,
        act: Act,
    ) -> CodeTaskPlan:
        """Create a simple exploration-first plan without LLM."""
        steps = [
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.READ_FILES,
                description="Explore repository structure",
                glob_pattern="**/*.py",
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.ANALYZE,
                description=f"Analyze codebase to understand: {request[:100]}",
            ),
            CodeStep(
                id=_generate_step_id(),
                type=CodeStepType.PLAN,
                description="Determine specific files to modify",
            ),
        ]

        return CodeTaskPlan(
            id=_generate_plan_id(),
            goal=request,
            steps=steps,
            estimated_impact=ImpactLevel.MINOR,
        )

    def _extract_file_references(self, error_output: str) -> list[str]:
        """Extract file paths mentioned in error output."""
        import re

        # Common patterns for file references in errors
        patterns = [
            r'File "([^"]+\.py)"',  # Python tracebacks
            r"(\S+\.py):\d+",       # file.py:123 format
            r"in (\S+\.py)",        # "in module.py" format
        ]

        files = set()
        for pattern in patterns:
            for match in re.finditer(pattern, error_output):
                file_path = match.group(1)
                # Filter to relative paths within repo
                if not file_path.startswith("/") or "site-packages" not in file_path:
                    # Clean up absolute paths
                    if "/" in file_path:
                        # Try to extract relative path
                        parts = file_path.split("/")
                        if "src" in parts:
                            idx = parts.index("src")
                            file_path = "/".join(parts[idx:])
                        elif "tests" in parts:
                            idx = parts.index("tests")
                            file_path = "/".join(parts[idx:])
                    files.add(file_path)

        return sorted(files)
