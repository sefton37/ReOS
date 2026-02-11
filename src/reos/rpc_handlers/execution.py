"""Code execution and planning RPC handlers.

These handlers manage code execution, planning, diff previews,
and related streaming operations for the Code Mode feature.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, TYPE_CHECKING

from reos.db import Database

from . import RpcError

if TYPE_CHECKING:
    from reos.code_mode import DiffPreviewManager, RepoMap


logger = logging.getLogger(__name__)


# =============================================================================
# Module-level state
# =============================================================================

# Store active reasoning engines and executions per session
_reasoning_engines: dict[str, Any] = {}
_active_executions: dict[str, Any] = {}

# Store active Code Mode streaming executions
_active_code_executions: dict[str, Any] = {}
_code_exec_lock = threading.Lock()

# Store active Code Mode planning contexts (pre-approval phase)
_active_code_plans: dict[str, Any] = {}
_code_plan_lock = threading.Lock()

# Track active diff preview managers per session
_diff_preview_managers: dict[str, "DiffPreviewManager"] = {}

# Track active RepoMap instances per session
_repo_map_instances: dict[str, "RepoMap"] = {}


# =============================================================================
# Helper functions
# =============================================================================


def _get_reasoning_engine(conversation_id: str, db: Database) -> Any:
    """Get or create a reasoning engine for a conversation."""
    from reos.reasoning.engine import ReasoningEngine

    if conversation_id not in _reasoning_engines:
        _reasoning_engines[conversation_id] = ReasoningEngine(db=db)
    return _reasoning_engines[conversation_id]


def _get_diff_preview_manager(session_id: str, repo_path: str | None = None) -> "DiffPreviewManager":
    """Get or create a DiffPreviewManager for a session."""
    from reos.code_mode import CodeSandbox, DiffPreviewManager

    if session_id not in _diff_preview_managers:
        if not repo_path:
            raise RpcError(code=-32602, message="repo_path required for new diff session")
        sandbox = CodeSandbox(Path(repo_path))
        _diff_preview_managers[session_id] = DiffPreviewManager(sandbox)

    return _diff_preview_managers[session_id]


def _get_repo_map(db: Database, session_id: str) -> "RepoMap":
    """Get or create a RepoMap instance for a session."""
    from reos.code_mode import CodeSandbox, RepoMap

    if session_id in _repo_map_instances:
        return _repo_map_instances[session_id]

    # Get repo path from session/sandbox
    if session_id not in _diff_preview_managers:
        raise ValueError(f"No sandbox found for session {session_id}")

    sandbox = _diff_preview_managers[session_id].sandbox
    repo_map = RepoMap(sandbox, db)
    _repo_map_instances[session_id] = repo_map
    return repo_map


# =============================================================================
# Plan Preview Handlers
# =============================================================================


def handle_plan_preview(
    db: Database,
    *,
    request: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Preview a plan for a request without executing it."""
    engine = _get_reasoning_engine(conversation_id, db)
    result = engine.process(request)

    if not result.plan:
        return {
            "has_plan": False,
            "response": result.response,
            "complexity": result.complexity.level.value if result.complexity else None,
        }

    # Format plan steps
    steps = []
    for i, step in enumerate(result.plan.steps):
        risk_info = {}
        if step.risk:
            risk_info = {
                "level": step.risk.level.value if hasattr(step.risk.level, 'value') else str(step.risk.level),
                "requires_confirmation": step.risk.requires_confirmation,
                "reversible": step.risk.reversible,
            }

        steps.append({
            "number": i + 1,
            "id": step.id,
            "title": step.title,
            "command": step.command,
            "explanation": step.explanation,
            "risk": risk_info,
        })

    return {
        "has_plan": True,
        "plan_id": result.plan.id,
        "title": result.plan.title,
        "steps": steps,
        "needs_approval": result.needs_approval,
        "response": result.response,
        "complexity": result.complexity.level.value if result.complexity else None,
    }


# =============================================================================
# Execution Status Handlers
# =============================================================================


def handle_execution_status(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Get the status of an execution.

    Checks both _active_executions (reasoning engine) and _active_code_executions
    (Code Mode streaming) for the execution ID.
    """
    # First check reasoning engine executions
    context = _active_executions.get(execution_id)

    if context:
        completed_steps = []
        for step_id, result in context.step_results.items():
            completed_steps.append({
                "step_id": step_id,
                "success": result.success,
                "output_preview": result.output[:200] if result.output else "",
            })

        return {
            "execution_id": execution_id,
            "state": context.state.value if hasattr(context.state, 'value') else str(context.state),
            "current_step": context.plan.current_step_index if context.plan else 0,
            "total_steps": len(context.plan.steps) if context.plan else 0,
            "completed_steps": completed_steps,
        }

    # Fall through to Code Mode streaming executions
    with _code_exec_lock:
        code_context = _active_code_executions.get(execution_id)

    if code_context:
        # Convert CodeExecutionContext to ExecutionStatusResult format
        state = code_context.state
        completed_steps = []

        # Build completed steps from the state
        if state and state.steps_completed > 0:
            for i in range(state.steps_completed):
                completed_steps.append({
                    "step_id": f"step-{i}",
                    "success": True,
                    "output_preview": "",
                })

        # Map phase to state value
        exec_state = "running"
        if code_context.is_complete:
            exec_state = "completed" if (state and state.success) else "failed"
        elif state:
            exec_state = state.status

        return {
            "execution_id": execution_id,
            "state": exec_state,
            "current_step": state.steps_completed if state else 0,
            "total_steps": state.steps_total if state else 0,
            "completed_steps": completed_steps,
            # Extra fields for richer UI (optional)
            "phase": state.phase if state else None,
            "phase_description": state.phase_description if state else None,
            "output_lines": state.output_lines if state else [],
            "is_complete": code_context.is_complete,
            "success": state.success if state else None,
            "error": code_context.error,
        }

    raise RpcError(code=-32602, message=f"Execution not found: {execution_id}")


def handle_execution_kill(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Kill a running execution.

    Checks both streaming executor and Code Mode executions.
    """
    # First try streaming executor
    from reos.streaming_executor import get_streaming_executor

    executor = get_streaming_executor()
    killed = executor.kill(execution_id)

    if killed:
        return {"ok": True, "message": "Execution killed"}

    # Fall through to Code Mode executions
    with _code_exec_lock:
        code_context = _active_code_executions.get(execution_id)

    if code_context:
        if code_context.is_complete:
            return {"ok": False, "message": "Execution already complete"}
        code_context.request_cancel()
        return {"ok": True, "message": "Cancellation requested"}

    return {"ok": False, "message": "Execution not found or already complete"}


# =============================================================================
# Code Diff Preview Handlers
# =============================================================================


def handle_code_diff_apply(
    db: Database,
    *,
    session_id: str,
    path: str | None = None,
) -> dict[str, Any]:
    """Apply changes - either all or a specific file."""
    if session_id not in _diff_preview_managers:
        raise RpcError(code=-32602, message="No pending changes for this session")

    manager = _diff_preview_managers[session_id]

    if path:
        # Apply single file
        success = manager.apply_file(path)
        if not success:
            raise RpcError(code=-32602, message=f"No pending change for path: {path}")
        return {"ok": True, "applied": [path]}
    else:
        # Apply all
        applied = manager.apply_all()
        # Clean up manager if all changes applied
        if session_id in _diff_preview_managers:
            del _diff_preview_managers[session_id]
        return {"ok": True, "applied": applied}


def handle_code_diff_reject(
    db: Database,
    *,
    session_id: str,
    path: str | None = None,
) -> dict[str, Any]:
    """Reject changes - either all or a specific file."""
    if session_id not in _diff_preview_managers:
        raise RpcError(code=-32602, message="No pending changes for this session")

    manager = _diff_preview_managers[session_id]

    if path:
        # Reject single file
        success = manager.reject_file(path)
        if not success:
            raise RpcError(code=-32602, message=f"No pending change for path: {path}")
        return {"ok": True, "rejected": [path]}
    else:
        # Reject all
        manager.reject_all()
        # Clean up manager
        if session_id in _diff_preview_managers:
            del _diff_preview_managers[session_id]
        return {"ok": True, "rejected": "all"}


# =============================================================================
# Code Plan Approve Handler
# =============================================================================


def handle_code_plan_approve(
    db: Database,
    *,
    conversation_id: str,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Approve and execute a pending Code Mode plan with streaming.

    Gets the pending code plan from the database and starts streaming
    execution that the frontend can poll.

    Returns:
        Dict with execution_id for polling code/exec/state
    """
    from reos.code_mode import (
        CodeSandbox,
        CodeExecutor,
        ExecutionObserver,
        create_execution_context,
    )
    from reos.code_mode.planner import (
        CodeTaskPlan,
        CodeStep,
        CodeStepType,
        ImpactLevel,
    )
    from reos.play_fs import list_acts

    # Get the pending code plan from database
    plan_json = db.get_state(key="pending_code_plan_json")
    if not plan_json:
        raise RpcError(code=-32602, message="No pending code plan to approve")

    try:
        plan_data = json.loads(plan_json)
    except json.JSONDecodeError as e:
        raise RpcError(code=-32602, message=f"Invalid plan data: {e}")

    # Reconstruct the CodeTaskPlan from stored JSON
    plan_context = None
    try:
        steps = []
        for step_data in plan_data.get("steps", []):
            step_type_str = step_data.get("type", "write_file")
            try:
                step_type = CodeStepType(step_type_str)
            except ValueError:
                step_type = CodeStepType.WRITE_FILE

            steps.append(CodeStep(
                id=step_data.get("id", f"step-{len(steps)}"),
                type=step_type,
                description=step_data.get("description", ""),
                target_path=step_data.get("target_path"),
            ))

        impact_str = plan_data.get("estimated_impact", "minor")
        try:
            impact = ImpactLevel(impact_str)
        except ValueError:
            impact = ImpactLevel.MINOR

        plan_context = CodeTaskPlan(
            id=plan_data.get("id", "plan-unknown"),
            goal=plan_data.get("goal", ""),
            steps=steps,
            context_files=plan_data.get("context_files", []),
            files_to_modify=plan_data.get("files_to_modify", []),
            files_to_create=plan_data.get("files_to_create", []),
            files_to_delete=plan_data.get("files_to_delete", []),
            estimated_impact=impact,
        )
    except Exception as e:
        logger.warning("Could not reconstruct plan context: %s", e)
        # Continue without plan context - will discover from scratch

    # Clear the pending plan
    db.set_state(key="pending_code_plan_json", value="")

    # Get the active Act with repo
    acts, active_act_id = list_acts()
    act = None
    if active_act_id:
        for a in acts:
            if a.act_id == active_act_id:
                act = a
                break

    if not act:
        raise RpcError(code=-32602, message="No active Act found")

    if not act.repo_path:
        raise RpcError(code=-32602, message="Active Act has no repository assigned")

    repo_path = act.repo_path
    prompt = plan_data.get("goal", "Execute code plan")
    session_id = conversation_id

    # Create execution context
    context = create_execution_context(
        session_id=session_id,
        prompt=prompt,
        max_iterations=10,
    )

    # Create observer that updates the context
    observer = ExecutionObserver(context)

    # Create sandbox and executor
    sandbox = CodeSandbox(Path(repo_path))

    # Get LLM provider
    llm = None
    try:
        from llm import get_provider
        llm = get_provider(db)
    except Exception as e:
        logger.warning("Failed to get LLM provider, falling back to Ollama: %s", e)
        # Fall back to Ollama
        try:
            from reos.ollama import OllamaClient
            stored_url = db.get_state("ollama_url")
            stored_model = db.get_state("ollama_model")
            if stored_url and stored_model:
                llm = OllamaClient(base_url=stored_url, model=stored_model)
        except Exception as e2:
            logger.error("Failed to initialize Ollama fallback: %s", e2)

    # Get project memory if available
    project_memory = None
    try:
        from reos.code_mode.project_memory import ProjectMemoryStore
        project_memory = ProjectMemoryStore(db=db)
    except Exception as e:
        logger.warning("Failed to initialize project memory: %s", e)

    executor = CodeExecutor(
        sandbox=sandbox,
        llm=llm,
        project_memory=project_memory,
        observer=observer,
    )

    def run_execution() -> None:
        """Run the execution in background thread."""
        try:
            result = executor.execute(
                prompt=prompt,
                act=act,
                max_iterations=10,
                auto_approve=True,
                plan_context=plan_context,  # Reuse plan's analysis!
            )
            context.result = result
            context.is_complete = True
        except Exception as e:
            context.error = str(e)
            context.is_complete = True
            observer.on_error(str(e))

    # Start background thread
    thread = threading.Thread(target=run_execution, daemon=True)
    context.thread = thread

    # Track the execution
    with _code_exec_lock:
        _active_code_executions[context.execution_id] = context

    thread.start()

    return {
        "execution_id": context.execution_id,
        "session_id": session_id,
        "status": "started",
        "prompt": prompt,
    }


# =============================================================================
# Code Execution State Handler
# =============================================================================


def handle_code_exec_state(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Get the current state of a Code Mode execution."""
    with _code_exec_lock:
        context = _active_code_executions.get(execution_id)

    if not context:
        raise RpcError(code=-32602, message=f"Code execution not found: {execution_id}")

    # Get current output lines
    output_lines = context.get_output_lines()

    # Update state with latest output
    if context.state:
        context.state.output_lines = output_lines

        # Return serialized state
        return context.state.to_dict()

    # Fallback if no state
    return {
        "execution_id": execution_id,
        "status": "unknown",
        "is_complete": context.is_complete,
        "error": context.error,
        "output_lines": output_lines,
    }


# =============================================================================
# Code Plan Start Handler
# =============================================================================


def handle_code_plan_start(
    db: Database,
    *,
    prompt: str,
    conversation_id: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Start Code Mode planning in background thread.

    This starts intent discovery and contract building asynchronously,
    allowing the frontend to poll for progress.

    Returns:
        Dict with planning_id for polling code/plan/state
    """
    from reos.code_mode.streaming import (
        create_planning_context,
        PlanningObserver,
        PlanningCancelledError,
    )
    from reos.code_mode.intent import IntentDiscoverer
    from reos.code_mode.contract import ContractBuilder
    from reos.code_mode import CodeSandbox, CodePlanner
    from llm import get_provider, check_provider_health
    from reos.play_fs import list_acts

    # Get the active act
    active_act = None
    acts, active_act_id = list_acts()

    # Use provided act_id or fall back to active_act_id
    target_act_id = act_id or active_act_id
    if target_act_id:
        for act in acts:
            if act.act_id == target_act_id:
                active_act = act
                break

    if not active_act or not active_act.repo_path:
        raise RpcError(
            code=-32602,
            message="No active Act with repository. Please set up an Act first."
        )

    # Check LLM health
    health = check_provider_health(db)
    if not health.reachable:
        raise RpcError(
            code=-32603,
            message=f"Cannot connect to LLM provider: {health.error or 'Unknown error'}"
        )

    # Create planning context
    context = create_planning_context(prompt)
    observer = PlanningObserver(context)

    def run_planning() -> None:
        """Background planning thread."""
        try:
            repo_path = Path(active_act.repo_path)  # type: ignore
            sandbox = CodeSandbox(repo_path)
            llm = get_provider(db)

            # Phase 1: Intent Discovery
            # Set phase to "analyzing_prompt" which maps to "intent" in UI
            observer.on_phase_change("analyzing_prompt")
            observer.on_activity("Starting intent discovery...")
            intent_discoverer = IntentDiscoverer(
                sandbox=sandbox,
                llm=llm,
                observer=observer,
            )

            # The discover() method handles all the sub-activities
            discovered_intent = intent_discoverer.discover(prompt, active_act)
            observer.on_activity(f"Intent discovered: {discovered_intent.goal[:50]}...")

            # Phase 2: Contract Building
            # Set phase to "generating_criteria" which maps to "contract" in UI
            observer.on_phase_change("generating_criteria")
            observer.on_activity("Building acceptance contract...")
            contract_builder = ContractBuilder(
                sandbox=sandbox,
                llm=llm,
                observer=observer,
            )

            contract = contract_builder.build_from_intent(discovered_intent)
            observer.on_activity(f"Contract built with {len(contract.acceptance_criteria)} criteria")

            # Phase 3: Create CodeTaskPlan
            # Set phase to "decomposing" which maps to "decompose" in UI
            observer.on_phase_change("decomposing")
            observer.on_activity("Generating execution plan...")
            planner = CodePlanner(sandbox=sandbox, llm=llm)
            plan = planner.create_plan(request=prompt, act=active_act)
            observer.on_activity(f"Plan created with {len(plan.steps)} steps")

            # Store result
            context.result = {
                "intent": discovered_intent,
                "contract": contract,
                "plan": plan,
            }

            # Planning complete - waiting for user approval
            observer.on_phase_change("ready")  # Maps to "approval" in UI
            observer.on_activity("Plan ready for your approval")
            context.update_state(
                is_complete=True,
                success=True,
                intent_summary=discovered_intent.goal,
                contract_summary=contract.summary(),
                ambiguities=discovered_intent.ambiguities,
                assumptions=discovered_intent.assumptions,
            )
            context.is_complete = True

        except PlanningCancelledError:
            context.error = "Planning cancelled by user"
            context.is_complete = True
            observer.on_phase_change("failed")
            context.update_state(
                is_complete=True,
                success=False,
                error="Cancelled by user",
            )

        except Exception as e:
            logger.exception("Planning failed: %s", e)
            context.error = str(e)
            context.is_complete = True
            observer.on_phase_change("failed")
            context.update_state(
                is_complete=True,
                success=False,
                error=str(e),
            )

    # Start planning thread
    thread = threading.Thread(target=run_planning, daemon=True)
    context.thread = thread

    # Store context
    with _code_plan_lock:
        _active_code_plans[context.planning_id] = context

    thread.start()

    return {
        "planning_id": context.planning_id,
        "status": "started",
        "prompt": prompt,
    }


# =============================================================================
# Code Plan State Handler
# =============================================================================


def handle_code_plan_state(
    db: Database,
    *,
    planning_id: str,
) -> dict[str, Any]:
    """Get the current state of a Code Mode planning session."""
    with _code_plan_lock:
        context = _active_code_plans.get(planning_id)

    if not context:
        raise RpcError(code=-32602, message=f"Planning session not found: {planning_id}")

    # Return serialized state
    if context.state:
        return context.state.to_dict()

    # Fallback
    return {
        "planning_id": planning_id,
        "phase": "unknown",
        "is_complete": context.is_complete,
        "error": context.error,
        "activity_log": [],
    }


# =============================================================================
# Code Plan Result Handler
# =============================================================================


def handle_code_plan_result(
    db: Database,
    *,
    planning_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Get the final result of a completed planning session.

    This returns the full plan/contract for display and approval.
    """
    from reos.agent import _generate_id

    with _code_plan_lock:
        context = _active_code_plans.get(planning_id)

    if not context:
        raise RpcError(code=-32602, message=f"Planning session not found: {planning_id}")

    if not context.is_complete:
        raise RpcError(code=-32602, message="Planning not yet complete")

    if context.error:
        return {
            "success": False,
            "error": context.error,
        }

    result = context.result
    if not result:
        return {
            "success": False,
            "error": "No result available",
        }

    intent = result["intent"]
    contract = result["contract"]
    plan = result["plan"]

    # Build response text (same format as _handle_code_mode in agent.py)
    thinking_log = ""
    if intent.discovery_steps:
        thinking_log = "\n### What ReOS understood:\n"
        for step in intent.discovery_steps[:8]:
            thinking_log += f"- {step}\n"

    clarifications = ""
    if intent.ambiguities:
        clarifications = "\n### Clarification needed:\n"
        for ambiguity in intent.ambiguities:
            clarifications += f"- ❓ {ambiguity}\n"

    assumptions = ""
    if intent.assumptions:
        assumptions = "\n### Assumptions:\n"
        for assumption in intent.assumptions:
            assumptions += f"- 💭 {assumption}\n"

    contract_summary = contract.summary()

    response_text = (
        f"**Code Mode Active** (repo: `{plan.repo_path if hasattr(plan, 'repo_path') else 'unknown'}`)\n"
        f"{thinking_log}"
        f"\n{contract_summary}\n"
        f"{clarifications}{assumptions}\n"
        f"Do you want me to proceed? (yes/no)"
    )

    # Store pending plan for approval flow
    db.set_state(key="pending_code_plan_json", value=json.dumps(plan.to_dict()))
    db.set_state(key="pending_code_plan_id", value=plan.id)

    # Store message
    message_id = _generate_id() if callable(_generate_id) else f"msg-{planning_id}"
    db.add_message(
        message_id=message_id,
        conversation_id=conversation_id,
        role="assistant",
        content=response_text,
        message_type="code_plan_preview",
        metadata=json.dumps({
            "code_mode": True,
            "plan_id": plan.id,
            "contract_id": contract.id,
            "intent_goal": intent.goal,
        }),
    )

    return {
        "success": True,
        "response_text": response_text,
        "message_id": message_id,
        "plan_id": plan.id,
        "contract_id": contract.id,
    }
