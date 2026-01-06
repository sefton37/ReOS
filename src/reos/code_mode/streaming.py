"""Streaming - real-time execution state for UI.

Provides infrastructure for streaming Code Mode execution state to the
Tauri frontend. Users can watch the AI work through phases, see live
test output, and cancel if needed.

Transparency builds trust.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.contract import AcceptanceCriterion, Contract, ContractStep
    from reos.code_mode.executor import DebugDiagnosis, ExecutionResult, LoopStatus
    from reos.code_mode.explorer import StepAlternative


# =============================================================================
# Phase Information
# =============================================================================

PHASE_INFO: dict[str, tuple[int, str, str]] = {
    # status_value: (index, human_name, description)
    "pending": (0, "Pending", "Waiting to start..."),
    "intent": (1, "Intent", "Discovering what you truly want..."),
    "contract": (2, "Contract", "Defining explicit success criteria..."),
    "decompose": (3, "Decompose", "Breaking into atomic steps..."),
    "build": (4, "Build", "Executing implementation steps..."),
    "verify": (5, "Verify", "Testing that changes work..."),
    "debug": (5, "Debug", "Analyzing and fixing failures..."),
    "exploring": (5, "Exploring", "Trying alternative approaches..."),
    "integrate": (6, "Integrate", "Merging verified code..."),
    "gap": (7, "Gap Analysis", "Checking what remains..."),
    "completed": (8, "Complete", "All criteria fulfilled!"),
    "failed": (8, "Failed", "Execution failed"),
    "approval": (8, "Awaiting Approval", "Needs user input"),
}


# =============================================================================
# Execution State Snapshot
# =============================================================================


@dataclass
class ExecutionStateSnapshot:
    """JSON-serializable snapshot of execution state for streaming to UI.

    This is what gets sent to the frontend on every poll. It captures
    everything needed to render the execution inspector panel.
    """

    execution_id: str
    session_id: str
    prompt: str

    # Phase tracking
    status: str  # LoopStatus value (e.g., "build")
    phase: str  # Human name (e.g., "Building")
    phase_description: str  # e.g., "Executing implementation steps..."
    phase_index: int  # 0-8 for progress bar

    # Progress metrics
    iteration: int
    max_iterations: int
    steps_completed: int
    steps_total: int
    criteria_fulfilled: int
    criteria_total: int

    # Current activity
    current_step: dict[str, Any] | None = None  # {description, action, target_file, status}
    current_criterion: dict[str, Any] | None = None  # {description, type, verified}

    # Output (last N lines)
    output_lines: list[str] = field(default_factory=list)

    # Debug info
    debug_attempt: int = 0
    debug_diagnosis: dict[str, Any] | None = None  # {root_cause, failure_type, confidence}

    # Exploration info (multi-path alternatives)
    is_exploring: bool = False
    exploration_alternatives_total: int = 0
    exploration_current_idx: int = 0
    exploration_current_alternative: dict[str, Any] | None = None  # {approach, rationale, score}
    exploration_results: list[dict[str, Any]] = field(default_factory=list)  # [{approach, success}]

    # Files changed
    files_changed: list[str] = field(default_factory=list)

    # Completion
    is_complete: bool = False
    success: bool | None = None
    error: str | None = None
    result_message: str | None = None

    # Timing
    started_at: str = ""  # ISO format
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "prompt": self.prompt,
            "status": self.status,
            "phase": self.phase,
            "phase_description": self.phase_description,
            "phase_index": self.phase_index,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "criteria_fulfilled": self.criteria_fulfilled,
            "criteria_total": self.criteria_total,
            "current_step": self.current_step,
            "current_criterion": self.current_criterion,
            "output_lines": self.output_lines,
            "debug_attempt": self.debug_attempt,
            "debug_diagnosis": self.debug_diagnosis,
            "is_exploring": self.is_exploring,
            "exploration_alternatives_total": self.exploration_alternatives_total,
            "exploration_current_idx": self.exploration_current_idx,
            "exploration_current_alternative": self.exploration_current_alternative,
            "exploration_results": self.exploration_results,
            "files_changed": self.files_changed,
            "is_complete": self.is_complete,
            "success": self.success,
            "error": self.error,
            "result_message": self.result_message,
            "started_at": self.started_at,
            "elapsed_seconds": self.elapsed_seconds,
        }


# =============================================================================
# Code Execution Context
# =============================================================================


@dataclass
class CodeExecutionContext:
    """Tracks a running Code Mode execution on the server side.

    This holds the thread running the execution, the current state snapshot,
    and mechanisms for cancellation and output buffering.
    """

    execution_id: str
    thread: threading.Thread | None = None
    state: ExecutionStateSnapshot | None = None
    output_buffer: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    is_complete: bool = False
    is_cancelled: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)

    result: Any = None  # ExecutionResult when complete
    error: str | None = None

    # Configuration
    max_output_lines: int = 100

    def add_output(self, line: str) -> None:
        """Add a line to the output buffer (thread-safe, rolling)."""
        with self.lock:
            self.output_buffer.append(line)
            # Keep only last N lines
            if len(self.output_buffer) > self.max_output_lines:
                self.output_buffer = self.output_buffer[-self.max_output_lines :]

    def get_output_lines(self) -> list[str]:
        """Get current output lines (thread-safe)."""
        with self.lock:
            return list(self.output_buffer)

    def request_cancel(self) -> None:
        """Request cancellation of the execution."""
        self.is_cancelled = True
        self.cancel_event.set()

    def should_cancel(self) -> bool:
        """Check if cancellation was requested."""
        return self.is_cancelled or self.cancel_event.is_set()

    def update_state(self, **kwargs: Any) -> None:
        """Update state snapshot fields (thread-safe)."""
        with self.lock:
            if self.state is not None:
                for key, value in kwargs.items():
                    if hasattr(self.state, key):
                        setattr(self.state, key, value)


# =============================================================================
# Execution Observer
# =============================================================================


class ExecutionObserver:
    """Observer that hooks into CodeExecutor to capture state changes.

    The observer is called at key points during execution:
    - Phase transitions
    - Step start/complete
    - Criterion verification
    - Debug attempts
    - Command output
    - Completion/failure

    It updates the CodeExecutionContext with the latest state.
    """

    def __init__(self, context: CodeExecutionContext) -> None:
        """Initialize observer with execution context.

        Args:
            context: The CodeExecutionContext to update.
        """
        self.context = context
        self._start_time = datetime.now(timezone.utc)

    def on_phase_change(self, status: LoopStatus) -> None:
        """Called when execution phase changes.

        Args:
            status: The new LoopStatus.
        """
        status_value = status.value
        phase_info = PHASE_INFO.get(status_value, (0, "Unknown", ""))
        phase_index, phase_name, phase_desc = phase_info

        self.context.update_state(
            status=status_value,
            phase=phase_name,
            phase_description=phase_desc,
            phase_index=phase_index,
            elapsed_seconds=self._elapsed_seconds(),
        )

        # Check for cancellation
        if self.context.should_cancel():
            raise ExecutionCancelledError("Execution cancelled by user")

    def on_iteration_start(self, iteration: int, max_iterations: int) -> None:
        """Called when a new iteration starts.

        Args:
            iteration: Current iteration number (1-based).
            max_iterations: Maximum iterations allowed.
        """
        self.context.update_state(
            iteration=iteration,
            max_iterations=max_iterations,
            elapsed_seconds=self._elapsed_seconds(),
        )

    def on_contract_built(self, contract: Contract) -> None:
        """Called when a contract is built.

        Args:
            contract: The Contract that was built.
        """
        self.context.update_state(
            steps_total=len(contract.steps),
            criteria_total=len(contract.acceptance_criteria),
            elapsed_seconds=self._elapsed_seconds(),
        )

    def on_step_start(self, step: ContractStep) -> None:
        """Called when a step starts executing.

        Args:
            step: The ContractStep being executed.
        """
        step_dict = {
            "id": step.id,
            "description": step.description,
            "action": step.action,
            "target_file": step.target_file,
            "status": "in_progress",
        }
        self.context.update_state(
            current_step=step_dict,
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"→ {step.description}")

    def on_step_complete(self, step: ContractStep, success: bool, output: str = "") -> None:
        """Called when a step completes.

        Args:
            step: The ContractStep that completed.
            success: Whether the step succeeded.
            output: Any output from the step.
        """
        step_dict = {
            "id": step.id,
            "description": step.description,
            "action": step.action,
            "target_file": step.target_file,
            "status": "completed" if success else "failed",
        }

        # Update files changed if applicable
        files_changed = list(self.context.state.files_changed) if self.context.state else []
        if step.target_file and step.target_file not in files_changed:
            files_changed.append(step.target_file)

        # Count completed steps
        steps_completed = (self.context.state.steps_completed if self.context.state else 0) + (
            1 if success else 0
        )

        self.context.update_state(
            current_step=step_dict,
            files_changed=files_changed,
            steps_completed=steps_completed,
            elapsed_seconds=self._elapsed_seconds(),
        )

        # Add output
        icon = "✓" if success else "✗"
        self.context.add_output(f"  {icon} {step.description}")
        if output:
            for line in output.split("\n")[:5]:  # First 5 lines
                self.context.add_output(f"    {line}")

    def on_criterion_verified(self, criterion: AcceptanceCriterion) -> None:
        """Called when a criterion is verified.

        Args:
            criterion: The AcceptanceCriterion that was verified.
        """
        criterion_dict = {
            "id": criterion.id,
            "description": criterion.description,
            "type": criterion.type.value,
            "verified": criterion.verified,
        }

        # Count fulfilled criteria
        criteria_fulfilled = (
            self.context.state.criteria_fulfilled if self.context.state else 0
        ) + (1 if criterion.verified else 0)

        self.context.update_state(
            current_criterion=criterion_dict,
            criteria_fulfilled=criteria_fulfilled,
            elapsed_seconds=self._elapsed_seconds(),
        )

        icon = "✓" if criterion.verified else "✗"
        self.context.add_output(f"  {icon} {criterion.description}")

    def on_debug_start(self, attempt: int) -> None:
        """Called when debug analysis starts.

        Args:
            attempt: Current debug attempt number.
        """
        self.context.update_state(
            debug_attempt=attempt,
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"🔧 Debug attempt {attempt}")

    def on_debug_diagnosis(self, diagnosis: DebugDiagnosis) -> None:
        """Called when debug diagnosis is complete.

        Args:
            diagnosis: The DebugDiagnosis result.
        """
        diagnosis_dict = {
            "root_cause": diagnosis.root_cause,
            "failure_type": diagnosis.failure_type,
            "confidence": diagnosis.confidence,
            "needs_more_info": diagnosis.needs_more_info,
        }
        self.context.update_state(
            debug_diagnosis=diagnosis_dict,
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"  Root cause: {diagnosis.root_cause}")
        self.context.add_output(f"  Confidence: {diagnosis.confidence}")

    def on_command_output(self, line: str) -> None:
        """Called when command produces output.

        Args:
            line: A line of command output.
        """
        self.context.add_output(line)

    def on_complete(self, result: ExecutionResult) -> None:
        """Called when execution completes.

        Args:
            result: The final ExecutionResult.
        """
        self.context.result = result
        self.context.is_complete = True

        self.context.update_state(
            is_complete=True,
            success=result.success,
            result_message=result.message,
            files_changed=result.files_changed,
            elapsed_seconds=self._elapsed_seconds(),
        )

        if result.success:
            self.context.add_output(f"✅ Complete: {result.message}")
        else:
            self.context.add_output(f"❌ Failed: {result.message}")

    def on_error(self, error: str) -> None:
        """Called when an error occurs.

        Args:
            error: The error message.
        """
        self.context.error = error
        self.context.is_complete = True

        self.context.update_state(
            is_complete=True,
            success=False,
            error=error,
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"❌ Error: {error}")

    def on_exploration_start(self, step: ContractStep, n_alternatives: int) -> None:
        """Called when exploration begins.

        Args:
            step: The step being explored.
            n_alternatives: Number of alternatives to try.
        """
        self.context.update_state(
            is_exploring=True,
            exploration_alternatives_total=n_alternatives,
            exploration_current_idx=0,
            exploration_results=[],
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"🔀 Exploring {n_alternatives} alternatives for: {step.description}")

    def on_alternative_start(self, step: ContractStep, alt: StepAlternative, idx: int) -> None:
        """Called when trying an alternative.

        Args:
            step: The original step.
            alt: The alternative being tried.
            idx: Zero-based index of the alternative.
        """
        alt_dict = {
            "id": alt.id,
            "approach": alt.approach,
            "rationale": alt.rationale,
            "score": alt.score,
        }
        self.context.update_state(
            exploration_current_idx=idx,
            exploration_current_alternative=alt_dict,
            elapsed_seconds=self._elapsed_seconds(),
        )
        self.context.add_output(f"  → Trying: {alt.approach} (score: {alt.score:.2f})")

    def on_alternative_result(self, alt: StepAlternative, success: bool) -> None:
        """Called after alternative attempt.

        Args:
            alt: The alternative that was tried.
            success: Whether it succeeded.
        """
        result = {"approach": alt.approach, "success": success}
        results = list(self.context.state.exploration_results) if self.context.state else []
        results.append(result)

        self.context.update_state(
            exploration_results=results,
            elapsed_seconds=self._elapsed_seconds(),
        )

        icon = "✓" if success else "✗"
        self.context.add_output(f"    {icon} {alt.approach}")

    def on_exploration_complete(self, step: ContractStep, success: bool) -> None:
        """Called when exploration finishes.

        Args:
            step: The step that was explored.
            success: Whether any alternative succeeded.
        """
        self.context.update_state(
            is_exploring=False,
            exploration_current_alternative=None,
            elapsed_seconds=self._elapsed_seconds(),
        )

        if success:
            self.context.add_output(f"  ✅ Found working alternative")
        else:
            self.context.add_output(f"  ❌ All alternatives exhausted")

    def _elapsed_seconds(self) -> float:
        """Calculate elapsed seconds since start."""
        return (datetime.now(timezone.utc) - self._start_time).total_seconds()


# =============================================================================
# Exceptions
# =============================================================================


class ExecutionCancelledError(Exception):
    """Raised when execution is cancelled by user."""

    pass


# =============================================================================
# Factory Functions
# =============================================================================


def create_execution_context(
    session_id: str,
    prompt: str,
    max_iterations: int = 10,
) -> CodeExecutionContext:
    """Create a new execution context with initial state.

    Args:
        session_id: The session ID.
        prompt: The user's prompt.
        max_iterations: Maximum iterations.

    Returns:
        Initialized CodeExecutionContext.
    """
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    initial_state = ExecutionStateSnapshot(
        execution_id=execution_id,
        session_id=session_id,
        prompt=prompt,
        status="pending",
        phase="Pending",
        phase_description="Waiting to start...",
        phase_index=0,
        iteration=0,
        max_iterations=max_iterations,
        steps_completed=0,
        steps_total=0,
        criteria_fulfilled=0,
        criteria_total=0,
        started_at=now.isoformat(),
    )

    return CodeExecutionContext(
        execution_id=execution_id,
        state=initial_state,
    )
