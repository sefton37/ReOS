"""Contract - explicit, testable definition of success.

A Contract is the system's commitment to what will be delivered.
It is:
- Explicit: No ambiguity about what success means
- Testable: Every criterion can be verified programmatically
- Decomposable: Can be broken into smaller contracts
- Grounded: Based on intent, not hallucination

The Contract is what prevents scope creep, hallucination, and
partial implementations. If it's not in the contract, it's not done.
If it's in the contract, it must be verified.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.intent import DiscoveredIntent
    from reos.code_mode.sandbox import CodeSandbox
    from reos.code_mode.test_generator import TestGenerator
    from reos.ollama import OllamaClient

logger = logging.getLogger(__name__)


class ContractStatus(Enum):
    """Status of a contract."""

    DRAFT = "draft"           # Not yet approved
    ACTIVE = "active"         # In progress
    FULFILLED = "fulfilled"   # All criteria met
    FAILED = "failed"         # Cannot be fulfilled
    SUPERSEDED = "superseded" # Replaced by new contract


class CriterionType(Enum):
    """Type of acceptance criterion."""

    FILE_EXISTS = "file_exists"           # A file must exist
    FILE_CONTAINS = "file_contains"       # A file must contain pattern
    FILE_NOT_CONTAINS = "file_not_contains"  # A file must NOT contain pattern
    TESTS_PASS = "tests_pass"             # Tests must pass
    CODE_COMPILES = "code_compiles"       # Code must compile/lint
    FUNCTION_EXISTS = "function_exists"   # A function must exist
    CLASS_EXISTS = "class_exists"         # A class must exist
    COMMAND_SUCCEEDS = "command_succeeds" # Arbitrary command returns 0
    GENERATED_TEST_PASSES = "generated_test_passes"  # Generated test must pass
    CUSTOM = "custom"                     # Custom verification


@dataclass
class TestSpecification:
    """Generated test code for a criterion.

    This represents actual pytest test code that was generated from intent.
    The test code serves as the acceptance criterion - when the test passes,
    the feature is considered complete (test-first development).
    """

    test_code: str           # Full pytest test code including imports
    test_file: str           # Path to test file (e.g., "tests/test_feature.py")
    test_function: str       # Test function name (e.g., "test_add_user")
    imports: list[str] = field(default_factory=list)  # Required imports
    setup_code: str = ""     # Optional setup/fixtures
    rationale: str = ""      # Why this test proves the feature works

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "test_code": self.test_code,
            "test_file": self.test_file,
            "test_function": self.test_function,
            "imports": self.imports,
            "setup_code": self.setup_code,
            "rationale": self.rationale,
        }


@dataclass
class AcceptanceCriterion:
    """A single testable criterion for contract fulfillment."""

    id: str
    type: CriterionType
    description: str
    # Type-specific parameters
    target_file: str | None = None
    pattern: str | None = None
    command: str | None = None
    # Generated test specification (for GENERATED_TEST_PASSES)
    test_spec: TestSpecification | None = None
    # Status
    verified: bool = False
    verification_output: str = ""
    verified_at: datetime | None = None

    def verify(self, sandbox: CodeSandbox) -> bool:
        """Verify this criterion against the sandbox."""
        result = False
        try:
            if self.type == CriterionType.FILE_EXISTS:
                result = self._verify_file_exists(sandbox)
            elif self.type == CriterionType.FILE_CONTAINS:
                result = self._verify_file_contains(sandbox)
            elif self.type == CriterionType.FILE_NOT_CONTAINS:
                result = self._verify_file_not_contains(sandbox)
            elif self.type == CriterionType.TESTS_PASS:
                result = self._verify_tests_pass(sandbox)
            elif self.type == CriterionType.CODE_COMPILES:
                result = self._verify_code_compiles(sandbox)
            elif self.type == CriterionType.FUNCTION_EXISTS:
                result = self._verify_function_exists(sandbox)
            elif self.type == CriterionType.CLASS_EXISTS:
                result = self._verify_class_exists(sandbox)
            elif self.type == CriterionType.COMMAND_SUCCEEDS:
                result = self._verify_command_succeeds(sandbox)
            elif self.type == CriterionType.GENERATED_TEST_PASSES:
                result = self._verify_generated_test_passes(sandbox)
            # else: Custom - cannot auto-verify, result stays False
        except Exception as e:
            self.verification_output = f"Error: {e}"
            result = False

        self.verified = result
        if result:
            self.verified_at = datetime.now(timezone.utc)
        return result

    def _verify_file_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file:
            return False
        try:
            sandbox.read_file(self.target_file, start=1, end=1)
            self.verification_output = f"File exists: {self.target_file}"
            return True
        except Exception:
            self.verification_output = f"File not found: {self.target_file}"
            return False

    def _verify_file_contains(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file or not self.pattern:
            return False
        try:
            matches = sandbox.grep(
                pattern=self.pattern,
                glob_pattern=self.target_file,
                max_results=1,
            )
            if matches:
                self.verification_output = f"Pattern found in {self.target_file}"
                return True
            self.verification_output = f"Pattern not found in {self.target_file}"
            return False
        except Exception as e:
            self.verification_output = f"Error searching: {e}"
            return False

    def _verify_file_not_contains(self, sandbox: CodeSandbox) -> bool:
        if not self.target_file or not self.pattern:
            return False
        try:
            matches = sandbox.grep(
                pattern=self.pattern,
                glob_pattern=self.target_file,
                max_results=1,
            )
            if not matches:
                self.verification_output = f"Pattern correctly absent from {self.target_file}"
                return True
            self.verification_output = f"Pattern incorrectly found in {self.target_file}"
            return False
        except Exception as e:
            self.verification_output = f"Error searching: {e}"
            return False

    def _verify_tests_pass(self, sandbox: CodeSandbox) -> bool:
        command = self.command or "pytest"
        returncode, stdout, stderr = sandbox.run_command(command, timeout=120)
        self.verification_output = stdout[:500] if stdout else stderr[:500]
        return returncode == 0

    def _verify_code_compiles(self, sandbox: CodeSandbox) -> bool:
        # Try common lint/check commands
        commands = [
            ("python -m py_compile", "**/*.py"),
            ("ruff check", "."),
            ("mypy", "."),
        ]
        for cmd, target in commands:
            returncode, stdout, stderr = sandbox.run_command(
                f"{cmd} {target}", timeout=60
            )
            if returncode == 0:
                self.verification_output = "Code compiles successfully"
                return True
        self.verification_output = "Compilation/lint check failed"
        return False

    def _verify_function_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.pattern:  # pattern = function name
            return False
        matches = sandbox.grep(
            pattern=rf"def {self.pattern}\s*\(",
            glob_pattern=self.target_file or "**/*.py",
            max_results=1,
        )
        if matches:
            self.verification_output = f"Function '{self.pattern}' found"
            return True
        self.verification_output = f"Function '{self.pattern}' not found"
        return False

    def _verify_class_exists(self, sandbox: CodeSandbox) -> bool:
        if not self.pattern:  # pattern = class name
            return False
        matches = sandbox.grep(
            pattern=rf"class {self.pattern}\b",
            glob_pattern=self.target_file or "**/*.py",
            max_results=1,
        )
        if matches:
            self.verification_output = f"Class '{self.pattern}' found"
            return True
        self.verification_output = f"Class '{self.pattern}' not found"
        return False

    def _verify_command_succeeds(self, sandbox: CodeSandbox) -> bool:
        """Verify an arbitrary command returns exit code 0."""
        if not self.command:
            self.verification_output = "No command specified"
            return False
        returncode, stdout, stderr = sandbox.run_command(self.command, timeout=120)
        # Capture full output for debugging
        output = stdout if stdout else stderr
        self.verification_output = output[:2000] if output else f"Exit code: {returncode}"
        return returncode == 0

    def _verify_generated_test_passes(self, sandbox: CodeSandbox) -> bool:
        """Verify the generated test passes.

        This method:
        1. Ensures the test file exists (writes it if not)
        2. Runs only the specific generated test function
        3. Reports pass/fail with output
        """
        if not self.test_spec:
            self.verification_output = "No test specification provided"
            return False

        test_file = self.test_spec.test_file
        test_function = self.test_spec.test_function

        # 1. Ensure test file exists - write it if not
        try:
            sandbox.read_file(test_file, start=1, end=1)
        except FileNotFoundError:
            # Write the generated test file
            sandbox.write_file(test_file, self.test_spec.test_code)
            self.verification_output = f"Created test file: {test_file}"

        # 2. Run only the specific generated test
        test_path = f"{test_file}::{test_function}"
        returncode, stdout, stderr = sandbox.run_command(
            f"pytest {test_path} -v --tb=short",
            timeout=60,
        )

        # 3. Capture output
        output = stdout if stdout else stderr
        self.verification_output = output[:2000] if output else f"Exit code: {returncode}"

        return returncode == 0


@dataclass
class ContractStep:
    """A discrete step to fulfill part of the contract."""

    id: str
    description: str
    target_criteria: list[str]  # IDs of criteria this step addresses
    # Implementation details
    action: str                  # "create_file", "edit_file", "run_command"
    target_file: str | None = None
    content: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    command: str | None = None
    # Status
    status: str = "pending"      # pending, in_progress, completed, failed
    result: str = ""
    completed_at: datetime | None = None


@dataclass
class Contract:
    """A contract defining what success means for a task.

    The contract is the system's commitment. It defines:
    - What must be true when complete (acceptance criteria)
    - How to get there (decomposed steps)
    - How to verify completion (testable assertions)
    """

    id: str
    intent_summary: str          # What this contract is for
    acceptance_criteria: list[AcceptanceCriterion]
    steps: list[ContractStep] = field(default_factory=list)
    status: ContractStatus = ContractStatus.DRAFT
    # Hierarchy
    parent_contract_id: str | None = None  # For sub-contracts
    child_contract_ids: list[str] = field(default_factory=list)
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fulfilled_at: datetime | None = None

    def is_fulfilled(self, sandbox: CodeSandbox) -> bool:
        """Check if all acceptance criteria are met."""
        for criterion in self.acceptance_criteria:
            criterion.verified = criterion.verify(sandbox)
            if criterion.verified:
                criterion.verified_at = datetime.now(timezone.utc)

        return all(c.verified for c in self.acceptance_criteria)

    def get_unfulfilled_criteria(self) -> list[AcceptanceCriterion]:
        """Get criteria that have not been verified."""
        return [c for c in self.acceptance_criteria if not c.verified]

    def get_pending_steps(self) -> list[ContractStep]:
        """Get steps that haven't been completed."""
        return [s for s in self.steps if s.status == "pending"]

    def get_next_step(self) -> ContractStep | None:
        """Get the next step to execute."""
        pending = self.get_pending_steps()
        return pending[0] if pending else None

    def summary(self) -> str:
        """Generate human-readable contract summary."""
        lines = [
            f"## Contract: {self.intent_summary}",
            f"**Status:** {self.status.value}",
            "",
            "### Acceptance Criteria:",
        ]

        for i, criterion in enumerate(self.acceptance_criteria, 1):
            status = "✅" if criterion.verified else "⏳"
            lines.append(f"{i}. {status} {criterion.description}")

        if self.steps:
            lines.append("")
            lines.append("### Steps:")
            for i, step in enumerate(self.steps, 1):
                status_icon = {
                    "pending": "⏳",
                    "in_progress": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }.get(step.status, "❓")
                lines.append(f"{i}. {status_icon} {step.description}")

        return "\n".join(lines)


def _generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class ContractBuilder:
    """Builds contracts from discovered intent.

    The builder translates intent into explicit, testable criteria
    and decomposes the work into discrete steps.

    With test_first=True (default), generates actual test code as
    acceptance criteria - implementing test-first development.
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        ollama: OllamaClient | None = None,
        test_generator: TestGenerator | None = None,
        test_first: bool = True,
    ) -> None:
        self.sandbox = sandbox
        self._ollama = ollama
        self._test_generator = test_generator
        self._test_first = test_first

    def build_from_intent(self, intent: DiscoveredIntent) -> Contract:
        """Build a contract from discovered intent.

        Args:
            intent: The discovered intent to build a contract for.

        Returns:
            A Contract with acceptance criteria and steps.
        """
        # Generate acceptance criteria from intent
        criteria = self._generate_criteria(intent)

        # Decompose into steps
        steps = self._decompose_into_steps(intent, criteria)

        return Contract(
            id=_generate_id("contract"),
            intent_summary=intent.goal,
            acceptance_criteria=criteria,
            steps=steps,
            status=ContractStatus.DRAFT,
        )

    def build_gap_contract(
        self,
        original_contract: Contract,
        intent: DiscoveredIntent,
    ) -> Contract:
        """Build a contract for the remaining gap.

        When a contract is partially fulfilled, this creates a new
        contract for what remains.
        """
        # Get unfulfilled criteria
        unfulfilled = original_contract.get_unfulfilled_criteria()

        if not unfulfilled:
            # All done - return empty contract
            return Contract(
                id=_generate_id("contract"),
                intent_summary=f"Gap for: {original_contract.intent_summary}",
                acceptance_criteria=[],
                status=ContractStatus.FULFILLED,
                parent_contract_id=original_contract.id,
            )

        # Build new steps for unfulfilled criteria
        steps = self._decompose_for_criteria(unfulfilled, intent)

        contract = Contract(
            id=_generate_id("contract"),
            intent_summary=f"Remaining: {original_contract.intent_summary}",
            acceptance_criteria=unfulfilled,
            steps=steps,
            status=ContractStatus.DRAFT,
            parent_contract_id=original_contract.id,
        )

        # Link parent to child
        original_contract.child_contract_ids.append(contract.id)

        return contract

    def _generate_criteria(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate acceptance criteria from intent.

        When test_first is enabled, generates actual test code as
        the primary acceptance criterion.
        """
        criteria = []

        # 1. Generate test specification if test_first is enabled
        if self._test_first and self._test_generator is not None:
            try:
                test_spec = self._test_generator.generate(intent)
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.GENERATED_TEST_PASSES,
                        description=f"Generated test passes: {test_spec.test_function}",
                        target_file=test_spec.test_file,
                        test_spec=test_spec,
                    )
                )
                logger.info(
                    "Generated test specification: %s::%s",
                    test_spec.test_file,
                    test_spec.test_function,
                )
            except Exception as e:
                logger.warning("Test generation failed: %s, using standard criteria", e)

        # 2. Add other criteria using LLM or heuristics
        if self._ollama is not None:
            criteria.extend(self._generate_criteria_with_llm(intent))
        else:
            criteria.extend(self._generate_criteria_heuristic(intent))

        return criteria

    def _generate_criteria_heuristic(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate criteria without LLM."""
        criteria = []
        action = intent.prompt_intent.action_verb.lower()
        target = intent.prompt_intent.target.lower()

        # Based on action verb, generate appropriate criteria
        if action in ("create", "add", "write", "implement"):
            if target in ("function", "method"):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.FUNCTION_EXISTS,
                        description=f"Function exists in codebase",
                        pattern=target,  # Will be refined
                    )
                )
            elif target in ("class",):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.CLASS_EXISTS,
                        description=f"Class exists in codebase",
                        pattern=target,
                    )
                )
            elif target in ("file", "module"):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.FILE_EXISTS,
                        description=f"File exists",
                    )
                )
            elif target in ("test",):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.TESTS_PASS,
                        description="Tests pass",
                        command="pytest",
                    )
                )

        # Always add a "code compiles" criterion
        criteria.append(
            AcceptanceCriterion(
                id=_generate_id("criterion"),
                type=CriterionType.CODE_COMPILES,
                description="Code compiles without errors",
            )
        )

        return criteria

    def _generate_criteria_with_llm(
        self,
        intent: DiscoveredIntent,
    ) -> list[AcceptanceCriterion]:
        """Generate criteria using LLM."""
        system = """You define acceptance criteria for code changes.

Given an intent, output JSON with testable criteria:
{
    "criteria": [
        {
            "type": "file_exists|file_contains|tests_pass|function_exists|class_exists",
            "description": "Human-readable description",
            "target_file": "path/to/file.py",  // if applicable
            "pattern": "regex or name",  // if applicable
            "command": "test command"  // if applicable
        }
    ]
}

Make criteria:
- Specific and testable
- Minimal but complete
- Focused on the actual change"""

        context = f"""
GOAL: {intent.goal}
WHAT: {intent.what}
ACTION: {intent.prompt_intent.action_verb}
TARGET: {intent.prompt_intent.target}
LANGUAGE: {intent.codebase_intent.language}
RELATED FILES: {', '.join(intent.codebase_intent.related_files[:5])}
"""

        try:
            response = self._ollama.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            data = json.loads(response)

            criteria = []
            for c in data.get("criteria", []):
                try:
                    ctype = CriterionType(c.get("type", "custom"))
                except ValueError:
                    ctype = CriterionType.CUSTOM

                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=ctype,
                        description=c.get("description", ""),
                        target_file=c.get("target_file"),
                        pattern=c.get("pattern"),
                        command=c.get("command"),
                    )
                )

            # Always add code compiles if not present
            if not any(c.type == CriterionType.CODE_COMPILES for c in criteria):
                criteria.append(
                    AcceptanceCriterion(
                        id=_generate_id("criterion"),
                        type=CriterionType.CODE_COMPILES,
                        description="Code compiles without errors",
                    )
                )

            return criteria

        except Exception as e:
            logger.warning("LLM criteria generation failed: %s", e)
            return self._generate_criteria_heuristic(intent)

    def _decompose_into_steps(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose the contract into discrete steps.

        When test_first is enabled, the first step creates the test file
        (red state), followed by implementation steps.
        """
        steps = []

        # 1. FIRST: Create test file for GENERATED_TEST_PASSES criteria
        for criterion in criteria:
            if (
                criterion.type == CriterionType.GENERATED_TEST_PASSES
                and criterion.test_spec is not None
            ):
                steps.append(
                    ContractStep(
                        id=_generate_id("step"),
                        description=f"Write test: {criterion.test_spec.test_function}",
                        target_criteria=[criterion.id],
                        action="create_file",
                        target_file=criterion.test_spec.test_file,
                        content=criterion.test_spec.test_code,
                    )
                )

        # 2. THEN: Implementation steps (from LLM or heuristics)
        if self._ollama is not None:
            steps.extend(self._decompose_with_llm(intent, criteria))
        else:
            steps.extend(self._decompose_heuristic(intent, criteria))

        return steps

    def _decompose_heuristic(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose without LLM."""
        steps = []
        action = intent.prompt_intent.action_verb.lower()

        if action in ("create", "add", "write"):
            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Create {intent.prompt_intent.target}",
                    target_criteria=[c.id for c in criteria],
                    action="create_file",
                )
            )
        elif action in ("edit", "modify", "update", "fix"):
            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Modify {intent.prompt_intent.target}",
                    target_criteria=[c.id for c in criteria],
                    action="edit_file",
                )
            )

        # Add verification step
        steps.append(
            ContractStep(
                id=_generate_id("step"),
                description="Verify changes",
                target_criteria=[c.id for c in criteria],
                action="run_command",
                command="pytest" if intent.codebase_intent.test_patterns else "echo 'No tests'",
            )
        )

        return steps

    def _decompose_with_llm(
        self,
        intent: DiscoveredIntent,
        criteria: list[AcceptanceCriterion],
    ) -> list[ContractStep]:
        """Decompose using LLM."""
        system = """You decompose code tasks into discrete, atomic steps.

Each step should be the smallest complete unit of work.

Output JSON:
{
    "steps": [
        {
            "description": "What this step does",
            "action": "create_file|edit_file|run_command",
            "target_file": "path/to/file.py",  // if applicable
            "command": "command to run"  // if run_command
        }
    ]
}

Make steps:
- Atomic (one thing at a time)
- Ordered (dependencies first)
- Concrete (no ambiguity)"""

        criteria_desc = "\n".join(f"- {c.description}" for c in criteria)
        context = f"""
GOAL: {intent.goal}
WHAT: {intent.what}
LANGUAGE: {intent.codebase_intent.language}

MUST SATISFY:
{criteria_desc}
"""

        try:
            response = self._ollama.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            data = json.loads(response)

            steps = []
            for s in data.get("steps", []):
                steps.append(
                    ContractStep(
                        id=_generate_id("step"),
                        description=s.get("description", ""),
                        target_criteria=[c.id for c in criteria],
                        action=s.get("action", "edit_file"),
                        target_file=s.get("target_file"),
                        command=s.get("command"),
                    )
                )

            return steps

        except Exception as e:
            logger.warning("LLM decomposition failed: %s", e)
            return self._decompose_heuristic(intent, criteria)

    def _decompose_for_criteria(
        self,
        criteria: list[AcceptanceCriterion],
        intent: DiscoveredIntent,
    ) -> list[ContractStep]:
        """Create steps specifically for unfulfilled criteria."""
        steps = []
        for criterion in criteria:
            steps.append(
                ContractStep(
                    id=_generate_id("step"),
                    description=f"Fulfill: {criterion.description}",
                    target_criteria=[criterion.id],
                    action="edit_file",
                    target_file=criterion.target_file,
                )
            )
        return steps
