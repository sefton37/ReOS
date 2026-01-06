"""Executor - the main execution loop for Code Mode.

The execution loop follows a principled cycle:
1. INTENT - Discover what the user truly wants
2. CONTRACT - Define explicit, testable success criteria
3. DECOMPOSE - Break into atomic steps
4. BUILD - Execute the most concrete step
5. VERIFY - Test that step fulfills its part
6. INTEGRATE - Merge verified code
7. GAP - Check what remains, loop until complete

Each phase uses a different perspective to ensure appropriate focus.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reos.code_mode.contract import (
    Contract,
    ContractBuilder,
    ContractStatus,
    ContractStep,
)
from reos.code_mode.intent import DiscoveredIntent, IntentDiscoverer
from reos.code_mode.perspectives import (
    ENGINEER,
    Phase,
    PerspectiveManager,
)
from reos.code_mode.sandbox import CodeSandbox

if TYPE_CHECKING:
    from reos.ollama import OllamaClient
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


class LoopStatus(Enum):
    """Status of the execution loop."""

    PENDING = "pending"             # Not started
    DISCOVERING_INTENT = "intent"   # Phase 1
    BUILDING_CONTRACT = "contract"  # Phase 2
    DECOMPOSING = "decompose"       # Phase 3
    BUILDING = "build"              # Phase 4
    VERIFYING = "verify"            # Phase 5
    DEBUGGING = "debug"             # Phase 5.5 - Analyzing failures
    INTEGRATING = "integrate"       # Phase 6
    ANALYZING_GAP = "gap"           # Phase 7
    COMPLETED = "completed"         # All done
    FAILED = "failed"               # Unrecoverable error
    AWAITING_APPROVAL = "approval"  # Needs user input


@dataclass
class LoopIteration:
    """Record of a single iteration through the loop."""

    iteration_number: int
    started_at: datetime
    completed_at: datetime | None = None
    phase_reached: Phase | None = None
    contract_id: str | None = None
    steps_completed: int = 0
    criteria_fulfilled: int = 0
    criteria_total: int = 0
    gap_remaining: str = ""
    error: str | None = None


@dataclass
class ExecutionState:
    """Complete state of an execution session."""

    session_id: str
    prompt: str
    status: LoopStatus = LoopStatus.PENDING
    # Core objects
    intent: DiscoveredIntent | None = None
    current_contract: Contract | None = None
    # History
    iterations: list[LoopIteration] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)
    # Metadata
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    max_iterations: int = 10
    current_iteration: int = 0


@dataclass
class DebugDiagnosis:
    """Result of debugging a failure."""

    root_cause: str
    failure_type: str  # code_bug, test_bug, environment, missing_dependency, configuration
    fix_location: dict[str, str]  # {"file": "path", "area": "function/lines"}
    fix_action: dict[str, str]  # {"old_str": "...", "new_str": "..."}
    confidence: str  # high, medium, low
    needs_more_info: bool = False
    raw_output: str = ""


@dataclass
class StepResult:
    """Result of executing a single step."""

    success: bool
    step_id: str
    output: str
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    debug_attempts: int = 0  # How many times we've tried to debug this step


@dataclass
class ExecutionResult:
    """Final result of the execution loop."""

    success: bool
    message: str
    state: ExecutionState
    files_changed: list[str] = field(default_factory=list)
    total_iterations: int = 0


class CodeExecutor:
    """Executes the code mode loop.

    The executor orchestrates the full cycle:
    Intent -> Contract -> Decompose -> Build -> Verify -> Integrate -> Gap -> Repeat

    Each phase uses a different perspective for appropriate focus.
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        ollama: OllamaClient | None = None,
    ) -> None:
        self.sandbox = sandbox
        self._ollama = ollama
        self._perspectives = PerspectiveManager(ollama)
        self._intent_discoverer = IntentDiscoverer(sandbox, ollama)
        self._contract_builder = ContractBuilder(sandbox, ollama)

    def execute(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str = "",
        max_iterations: int = 10,
        auto_approve: bool = False,
    ) -> ExecutionResult:
        """Execute the full code mode loop.

        Args:
            prompt: The user's request.
            act: The active Act with context.
            knowledge_context: Optional KB context.
            max_iterations: Maximum loop iterations.
            auto_approve: If True, skip approval prompts.

        Returns:
            ExecutionResult with outcome and state.
        """
        import uuid

        state = ExecutionState(
            session_id=f"exec-{uuid.uuid4().hex[:8]}",
            prompt=prompt,
            max_iterations=max_iterations,
        )

        try:
            # Phase 1: Discover Intent
            state.status = LoopStatus.DISCOVERING_INTENT
            state.intent = self._discover_intent(prompt, act, knowledge_context)

            # Main loop
            while state.current_iteration < max_iterations:
                iteration = self._run_iteration(state, act, auto_approve)
                state.iterations.append(iteration)
                state.current_iteration += 1

                if iteration.error:
                    state.status = LoopStatus.FAILED
                    break

                # Check if complete
                if state.current_contract and state.current_contract.is_fulfilled(self.sandbox):
                    state.status = LoopStatus.COMPLETED
                    state.completed_at = datetime.now(timezone.utc)
                    break

            # Build result
            files_changed = self._collect_changed_files(state)

            return ExecutionResult(
                success=state.status == LoopStatus.COMPLETED,
                message=self._generate_result_message(state),
                state=state,
                files_changed=files_changed,
                total_iterations=state.current_iteration,
            )

        except Exception as e:
            logger.exception("Execution failed: %s", e)
            state.status = LoopStatus.FAILED
            return ExecutionResult(
                success=False,
                message=f"Execution failed: {e}",
                state=state,
            )

    def _discover_intent(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str,
    ) -> DiscoveredIntent:
        """Phase 1: Discover intent from all sources."""
        self._perspectives.shift_to(Phase.INTENT)
        return self._intent_discoverer.discover(prompt, act, knowledge_context)

    def _run_iteration(
        self,
        state: ExecutionState,
        act: Act,
        auto_approve: bool,
    ) -> LoopIteration:
        """Run a single iteration of the loop."""
        iteration = LoopIteration(
            iteration_number=state.current_iteration + 1,
            started_at=datetime.now(timezone.utc),
        )

        try:
            # Phase 2: Build or update contract
            if state.current_contract is None:
                state.status = LoopStatus.BUILDING_CONTRACT
                iteration.phase_reached = Phase.CONTRACT
                state.current_contract = self._build_contract(state.intent)
                state.contracts.append(state.current_contract)
                iteration.contract_id = state.current_contract.id
                iteration.criteria_total = len(state.current_contract.acceptance_criteria)

            contract = state.current_contract

            # Phase 3: Decompose (already done in contract building)
            state.status = LoopStatus.DECOMPOSING
            iteration.phase_reached = Phase.DECOMPOSE

            # Phase 4: Build - execute next step
            next_step = contract.get_next_step()
            debug_attempts = getattr(next_step, '_debug_attempts', 0) if next_step else 0

            if next_step:
                state.status = LoopStatus.BUILDING
                iteration.phase_reached = Phase.BUILD
                step_result = self._execute_step(next_step, state.intent, act)

                if step_result.success:
                    next_step.status = "completed"
                    next_step.result = step_result.output
                    next_step.completed_at = datetime.now(timezone.utc)
                    iteration.steps_completed += 1

                    # Phase 5: Verify
                    state.status = LoopStatus.VERIFYING
                    iteration.phase_reached = Phase.VERIFY
                    verification_passed = self._verify_step(next_step, contract)

                    # Phase 5.5: Debug if verification failed
                    if not verification_passed and debug_attempts < 3:
                        state.status = LoopStatus.DEBUGGING
                        iteration.phase_reached = Phase.DEBUG
                        debug_result = self._debug_failure(
                            next_step, contract, step_result, state.intent, act
                        )
                        if debug_result:
                            # Applied a fix - mark step as pending to retry in next iteration
                            next_step.status = "pending"
                            # Store debug attempts on step for next iteration
                            next_step._debug_attempts = debug_attempts + 1  # type: ignore
                            # Return early - next iteration will retry this step
                            iteration.completed_at = datetime.now(timezone.utc)
                            iteration.gap_remaining = "Debug fix applied, retrying step"
                            return iteration

                    # Phase 6: Integrate (for now, changes are direct)
                    state.status = LoopStatus.INTEGRATING
                    iteration.phase_reached = Phase.INTEGRATE
                else:
                    # Build step failed - try to debug
                    if debug_attempts < 3:
                        state.status = LoopStatus.DEBUGGING
                        iteration.phase_reached = Phase.DEBUG
                        debug_result = self._debug_failure(
                            next_step, contract, step_result, state.intent, act
                        )
                        if debug_result:
                            # Store debug attempts on step for next iteration
                            next_step._debug_attempts = debug_attempts + 1  # type: ignore
                            # Return early - next iteration will retry this step
                            iteration.completed_at = datetime.now(timezone.utc)
                            iteration.gap_remaining = "Debug fix applied, retrying step"
                            return iteration

                    next_step.status = "failed"
                    next_step.result = step_result.error or "Unknown error"

            # Phase 7: Gap Analysis
            state.status = LoopStatus.ANALYZING_GAP
            iteration.phase_reached = Phase.GAP_ANALYSIS

            # Check fulfillment
            fulfilled = [c for c in contract.acceptance_criteria if c.verified]
            iteration.criteria_fulfilled = len(fulfilled)

            # If not all fulfilled, create gap contract
            unfulfilled = contract.get_unfulfilled_criteria()
            if unfulfilled and not contract.get_pending_steps():
                # All steps done but criteria not met - need new approach
                gap_contract = self._contract_builder.build_gap_contract(
                    contract, state.intent  # type: ignore
                )
                state.current_contract = gap_contract
                state.contracts.append(gap_contract)
                iteration.gap_remaining = f"{len(unfulfilled)} criteria unfulfilled"

            iteration.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.exception("Iteration failed: %s", e)
            iteration.error = str(e)
            iteration.completed_at = datetime.now(timezone.utc)

        return iteration

    def _build_contract(self, intent: DiscoveredIntent | None) -> Contract:
        """Phase 2: Build contract from intent."""
        self._perspectives.shift_to(Phase.CONTRACT)
        if intent is None:
            raise ValueError("Cannot build contract without intent")
        return self._contract_builder.build_from_intent(intent)

    def _execute_step(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> StepResult:
        """Phase 4: Execute a single step."""
        self._perspectives.shift_to(Phase.BUILD)
        step.status = "in_progress"

        try:
            if step.action == "create_file":
                return self._execute_create_file(step, intent, act)
            elif step.action == "edit_file":
                return self._execute_edit_file(step, intent, act)
            elif step.action == "run_command":
                return self._execute_command(step)
            else:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error=f"Unknown action: {step.action}",
                )
        except Exception as e:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error=str(e),
            )

    def _execute_create_file(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> StepResult:
        """Execute a file creation step."""
        if not step.target_file:
            # Need to determine target file
            if intent and intent.codebase_intent.related_files:
                # Use a related file's directory
                related = intent.codebase_intent.related_files[0]
                step.target_file = str(Path(related).parent / "new_file.py")
            else:
                step.target_file = "src/new_file.py"

        # Generate content using LLM
        content = self._generate_file_content(step, intent, act)

        if not content:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error="Could not generate file content",
            )

        # Write the file
        result = self.sandbox.write_file(step.target_file, content)

        return StepResult(
            success=True,
            step_id=step.id,
            output=f"Created {step.target_file}",
            files_changed=[step.target_file],
        )

    def _execute_edit_file(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> StepResult:
        """Execute a file edit step."""
        if not step.target_file:
            # Try to determine from intent
            if intent and intent.codebase_intent.related_files:
                step.target_file = intent.codebase_intent.related_files[0]
            else:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error="No target file specified",
                )

        # Read current content
        try:
            current_content = self.sandbox.read_file(step.target_file)
        except Exception as e:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error=f"Cannot read file: {e}",
            )

        # Generate edit using LLM
        edit_result = self._generate_edit(step, current_content, intent, act)

        if not edit_result:
            return StepResult(
                success=False,
                step_id=step.id,
                output="",
                error="Could not generate edit",
            )

        old_str, new_str = edit_result

        if old_str and new_str:
            try:
                self.sandbox.edit_file(step.target_file, old_str, new_str)
                return StepResult(
                    success=True,
                    step_id=step.id,
                    output=f"Edited {step.target_file}",
                    files_changed=[step.target_file],
                )
            except Exception as e:
                return StepResult(
                    success=False,
                    step_id=step.id,
                    output="",
                    error=f"Edit failed: {e}",
                )

        return StepResult(
            success=False,
            step_id=step.id,
            output="",
            error="No valid edit generated",
        )

    def _execute_command(self, step: ContractStep) -> StepResult:
        """Execute a command step."""
        command = step.command or "echo 'No command'"
        returncode, stdout, stderr = self.sandbox.run_command(command)

        return StepResult(
            success=returncode == 0,
            step_id=step.id,
            output=stdout[:1000] if stdout else stderr[:1000],
            error=stderr if returncode != 0 else None,
        )

    def _generate_file_content(
        self,
        step: ContractStep,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> str:
        """Generate content for a new file."""
        if self._ollama is None:
            return f"# {step.description}\n# TODO: Implement\n"

        context = f"""
STEP: {step.description}
TARGET FILE: {step.target_file}
LANGUAGE: {intent.codebase_intent.language if intent else 'python'}
CONVENTIONS: {', '.join(intent.codebase_intent.conventions) if intent else 'standard'}
"""

        response = self._perspectives.invoke(
            Phase.BUILD,
            f"Write the complete file content for: {step.description}",
            context=context,
        )

        # Extract code from response
        return self._extract_code(response)

    def _generate_edit(
        self,
        step: ContractStep,
        current_content: str,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> tuple[str, str] | None:
        """Generate an edit (old_str, new_str) for a file."""
        if self._ollama is None:
            return None

        context = f"""
STEP: {step.description}
TARGET FILE: {step.target_file}

CURRENT FILE CONTENT:
```
{current_content[:2000]}
```

Output JSON with:
{{"old_str": "exact text to replace", "new_str": "replacement text"}}
"""

        try:
            response = self._perspectives.invoke_json(
                Phase.BUILD,
                f"Generate the minimal edit for: {step.description}",
                context=context,
            )
            data = json.loads(response)
            return data.get("old_str"), data.get("new_str")
        except Exception as e:
            logger.warning("Edit generation failed: %s", e)
            return None

    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response."""
        # Look for code blocks
        if "```" in response:
            parts = response.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Odd indices are code blocks
                    # Remove language identifier if present
                    lines = part.strip().split("\n")
                    if lines and lines[0] in ("python", "py", "typescript", "ts", "javascript", "js"):
                        return "\n".join(lines[1:])
                    return part.strip()

        # No code block, return as-is
        return response.strip()

    def _verify_step(self, step: ContractStep, contract: Contract) -> bool:
        """Phase 5: Verify a step's output.

        Returns:
            True if all target criteria are verified, False otherwise.
        """
        self._perspectives.shift_to(Phase.VERIFY)

        all_passed = True
        # Verify related criteria
        for criterion_id in step.target_criteria:
            for criterion in contract.acceptance_criteria:
                if criterion.id == criterion_id:
                    criterion.verified = criterion.verify(self.sandbox)
                    if criterion.verified:
                        criterion.verified_at = datetime.now(timezone.utc)
                    else:
                        all_passed = False

        return all_passed

    def _debug_failure(
        self,
        step: ContractStep,
        contract: Contract,
        step_result: StepResult,
        intent: DiscoveredIntent | None,
        act: Act,
    ) -> bool:
        """Phase 5.5: Debug a failure and attempt to fix it.

        Args:
            step: The step that failed.
            contract: The current contract.
            step_result: The result of the failed step.
            intent: The discovered intent.
            act: The active Act.

        Returns:
            True if a fix was applied and we should retry, False otherwise.
        """
        self._perspectives.shift_to(Phase.DEBUG)

        if self._ollama is None:
            return False

        # Gather failure information
        failed_criteria = [
            c for c in contract.acceptance_criteria
            if c.id in step.target_criteria and not c.verified
        ]

        if not failed_criteria and not step_result.error:
            return False  # No clear failure to debug

        # Build context for debugger
        error_output = step_result.error or ""
        verification_outputs = "\n".join(
            f"- {c.description}: {c.verification_output}"
            for c in failed_criteria
        )

        # Read the file that was changed if available
        file_content = ""
        if step.target_file:
            try:
                file_content = self.sandbox.read_file(step.target_file)
            except Exception:
                pass

        context = f"""
STEP DESCRIPTION: {step.description}
TARGET FILE: {step.target_file or 'N/A'}
STEP ACTION: {step.action}

ERROR OUTPUT:
{error_output}

FAILED VERIFICATIONS:
{verification_outputs if verification_outputs else 'No specific verification failures'}

FILE CONTENT (if relevant):
```
{file_content[:3000] if file_content else 'N/A'}
```
"""

        try:
            response = self._perspectives.invoke_json(
                Phase.DEBUG,
                "Analyze this failure and provide a fix.",
                context=context,
            )
            data = json.loads(response)

            diagnosis = DebugDiagnosis(
                root_cause=data.get("root_cause", "Unknown"),
                failure_type=data.get("failure_type", "unknown"),
                fix_location=data.get("fix_location", {}),
                fix_action=data.get("fix_action", {}),
                confidence=data.get("confidence", "low"),
                needs_more_info=data.get("needs_more_info", False),
                raw_output=response,
            )

            # Apply fix if confident enough
            if diagnosis.confidence in ("high", "medium") and not diagnosis.needs_more_info:
                fix_applied = self._apply_debug_fix(diagnosis, step)
                if fix_applied:
                    logger.info(
                        "Applied debug fix: %s (confidence: %s)",
                        diagnosis.root_cause,
                        diagnosis.confidence,
                    )
                    return True

            logger.warning(
                "Debug diagnosis: %s (confidence: %s, needs_more_info: %s)",
                diagnosis.root_cause,
                diagnosis.confidence,
                diagnosis.needs_more_info,
            )
            return False

        except Exception as e:
            logger.warning("Debug analysis failed: %s", e)
            return False

    def _apply_debug_fix(self, diagnosis: DebugDiagnosis, step: ContractStep) -> bool:
        """Apply a fix from debug diagnosis.

        Args:
            diagnosis: The debug diagnosis with fix information.
            step: The step being fixed.

        Returns:
            True if fix was applied successfully.
        """
        fix_action = diagnosis.fix_action
        if not fix_action:
            return False

        old_str = fix_action.get("old_str", "")
        new_str = fix_action.get("new_str", "")

        if not old_str or not new_str:
            return False

        # Determine target file
        target_file = diagnosis.fix_location.get("file") or step.target_file
        if not target_file:
            return False

        try:
            self.sandbox.edit_file(target_file, old_str, new_str)
            return True
        except Exception as e:
            logger.warning("Failed to apply debug fix: %s", e)
            return False

    def _collect_changed_files(self, state: ExecutionState) -> list[str]:
        """Collect all files changed during execution."""
        files = set()
        for contract in state.contracts:
            for step in contract.steps:
                if step.status == "completed" and step.target_file:
                    files.add(step.target_file)
        return sorted(files)

    def _generate_result_message(self, state: ExecutionState) -> str:
        """Generate a human-readable result message."""
        if state.status == LoopStatus.COMPLETED:
            files = self._collect_changed_files(state)
            return (
                f"Completed in {state.current_iteration} iteration(s).\n"
                f"Files changed: {', '.join(files) if files else 'none'}"
            )
        elif state.status == LoopStatus.FAILED:
            last_error = ""
            if state.iterations:
                last_error = state.iterations[-1].error or ""
            return f"Failed after {state.current_iteration} iteration(s): {last_error}"
        else:
            return f"Stopped at status: {state.status.value}"

    def preview_plan(self, state: ExecutionState) -> str:
        """Generate a preview of the execution plan."""
        lines = ["## Execution Plan Preview", ""]

        if state.intent:
            lines.append("### Intent")
            lines.append(state.intent.summary())
            lines.append("")

        if state.current_contract:
            lines.append("### Contract")
            lines.append(state.current_contract.summary())
            lines.append("")

        return "\n".join(lines)
