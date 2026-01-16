"""UI RPC server for the ReOS desktop app.

This is a small JSON-RPC 2.0 server over stdio intended to be used by a
TypeScript desktop shell (Tauri).

Design goals:
- Local-only (stdio; no network listener).
- Metadata-first by default.
- Stable, explicit contract between UI and kernel.

This is intentionally *not* MCP; it's a UI-facing RPC layer. We still expose
`tools/list` + `tools/call` by delegating to the existing repo-scoped tool
catalog so the UI can reuse those capabilities.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from . import auth
from .agent import ChatAgent
from .context_sources import VALID_SOURCE_NAMES, DISABLEABLE_SOURCES
from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools
from .security import (
    ValidationError,
    validate_service_name,
    validate_container_id,
    escape_shell_arg,
    is_command_safe,
    check_rate_limit,
    RateLimitExceeded,
    audit_log,
    AuditEventType,
    get_auditor,
    configure_auditor,
    get_rate_limiter,
    DANGEROUS_PATTERNS,
    INJECTION_PATTERNS,
    MAX_COMMAND_LEN,
    MAX_SERVICE_NAME_LEN,
    MAX_CONTAINER_ID_LEN,
    MAX_PACKAGE_NAME_LEN,
)
from .play_fs import add_attachment as play_add_attachment
from .play_fs import create_act as play_create_act
from .play_fs import create_beat as play_create_beat
from .play_fs import create_scene as play_create_scene
from .play_fs import kb_list_files as play_kb_list_files
from .play_fs import kb_read as play_kb_read
from .play_fs import kb_write_apply as play_kb_write_apply
from .play_fs import kb_write_preview as play_kb_write_preview
from .play_fs import list_acts as play_list_acts
from .play_fs import list_attachments as play_list_attachments
from .play_fs import list_beats as play_list_beats
from .play_fs import list_scenes as play_list_scenes
from .play_fs import read_me_markdown as play_read_me_markdown
from .play_fs import remove_attachment as play_remove_attachment
from .play_fs import write_me_markdown as play_write_me_markdown
from .play_fs import set_active_act_id as play_set_active_act_id
from .play_fs import update_act as play_update_act
from .play_fs import update_beat as play_update_beat
from .play_fs import move_beat as play_move_beat
from .play_fs import update_scene as play_update_scene
from .play_fs import assign_repo_to_act as play_assign_repo_to_act
from .context_meter import calculate_context_stats, estimate_tokens
from .knowledge_store import KnowledgeStore
from .compact_extractor import extract_knowledge_from_messages, generate_archive_summary
from .play_fs import play_root

_JSON = dict[str, Any]


def get_current_play_path(db: Database) -> str | None:
    """Get the current play path.

    Returns the path to the play root directory, or None if not available.
    """
    try:
        path = play_root()
        if path.exists():
            return str(path)
        return None
    except Exception:
        return None


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _jsonrpc_error(*, req_id: Any, code: int, message: str, data: Any | None = None) -> _JSON:
    err: _JSON = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _jsonrpc_result(*, req_id: Any, result: Any) -> _JSON:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _readline() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line


def _write(obj: Any) -> None:
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Client closed the pipe (e.g., UI exited). Treat as a clean shutdown.
        raise SystemExit(0) from None


# -------------------------------------------------------------------------
# Authentication handlers (PAM + session management)
# -------------------------------------------------------------------------










def _tools_list() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in list_tools()
        ]
    }


def _handle_tools_call(db: Database, *, name: str, arguments: dict[str, Any] | None) -> Any:
    try:
        return call_tool(db, name=name, arguments=arguments)
    except ToolError as exc:
        # -32602: invalid params
        code = -32602 if exc.code in {"invalid_args", "path_escape"} else -32000
        raise RpcError(code=code, message=exc.message, data=exc.data) from exc


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    return slug[:50]  # Limit length


def _handle_chat_respond(
    db: Database,
    *,
    text: str,
    conversation_id: str | None = None,
    use_code_mode: bool = False,
    agent_type: str | None = None,
    extended_thinking: bool | None = None,
) -> dict[str, Any]:
    agent = ChatAgent(db=db, use_code_mode=use_code_mode)

    # Check for conversational intents (Phase 6)
    if conversation_id:
        intent = agent.detect_intent(text)

        if intent:
            # Handle approval/rejection of pending approvals
            if intent.intent_type in ("approval", "rejection"):
                pending = agent.get_pending_approval_for_conversation(conversation_id)
                if pending:
                    action = "approve" if intent.intent_type == "approval" else "reject"
                    result = _handle_approval_respond(
                        db,
                        approval_id=str(pending["id"]),
                        action=action,
                    )
                    # Return a synthetic response
                    import uuid
                    message_id = uuid.uuid4().hex[:12]
                    if action == "approve":
                        if result.get("status") == "executed":
                            answer = f"Command executed. Return code: {result.get('result', {}).get('return_code', 'unknown')}"
                        else:
                            answer = f"Command execution failed: {result.get('result', {}).get('error', 'unknown error')}"
                    else:
                        answer = "Command rejected."

                    # Store the response
                    db.add_message(
                        message_id=message_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content=answer,
                        message_type="text",
                    )

                    return {
                        "answer": answer,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "message_type": "text",
                        "tool_calls": [],
                        "thinking_steps": [],
                        "pending_approval_id": None,
                        "intent_handled": intent.intent_type,
                    }

            # Handle reference resolution
            if intent.intent_type == "reference" and intent.reference_term:
                resolved = agent.resolve_reference(intent.reference_term, conversation_id)
                if resolved:
                    # Expand the text to include the resolved entity
                    text = text.replace(
                        intent.reference_term,
                        f"{intent.reference_term} ({resolved.get('type', '')}: {resolved.get('name', resolved.get('id', ''))})"
                    )

    response = agent.respond(
        text,
        conversation_id=conversation_id,
        agent_type=agent_type,
        extended_thinking=extended_thinking,
    )
    return {
        "answer": response.answer,
        "conversation_id": response.conversation_id,
        "message_id": response.message_id,
        "message_type": response.message_type,
        "tool_calls": response.tool_calls,
        "thinking_steps": response.thinking_steps,
        "pending_approval_id": response.pending_approval_id,
        "extended_thinking_trace": response.extended_thinking_trace,
    }




# -------------------------------------------------------------------------
# Conversation management handlers
# -------------------------------------------------------------------------








# -------------------------------------------------------------------------
# Approval workflow handlers
# -------------------------------------------------------------------------


def _handle_approval_pending(
    db: Database,
    *,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Get all pending approvals."""
    approvals = db.get_pending_approvals(conversation_id=conversation_id)
    return {
        "approvals": [
            {
                "id": str(a.get("id")),
                "conversation_id": a.get("conversation_id"),
                "command": a.get("command"),
                "explanation": a.get("explanation"),
                "risk_level": a.get("risk_level"),
                "affected_paths": json.loads(a.get("affected_paths") or "[]"),
                "undo_command": a.get("undo_command"),
                "plan_id": a.get("plan_id"),
                "step_id": a.get("step_id"),
                "created_at": a.get("created_at"),
            }
            for a in approvals
        ]
    }


def _handle_approval_respond(
    db: Database,
    *,
    approval_id: str,
    action: str,  # 'approve', 'reject'
    edited_command: str | None = None,
) -> dict[str, Any]:
    """Respond to an approval request."""
    from .linux_tools import execute_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(code=-32602, message=f"Approval not found: {approval_id}")

    if approval.get("status") != "pending":
        raise RpcError(code=-32602, message="Approval already resolved")

    # SECURITY: Rate limit approval actions
    try:
        check_rate_limit("approval")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "approval", "action": action})
        raise RpcError(code=-32429, message=str(e))

    if action == "reject":
        db.resolve_approval(approval_id=approval_id, status="rejected")
        audit_log(AuditEventType.APPROVAL_DENIED, {
            "approval_id": approval_id,
            "original_command": approval.get("command"),
        })
        return {"status": "rejected", "result": None}

    if action == "approve":
        original_command = str(approval.get("command"))
        command = edited_command if edited_command else original_command
        was_edited = edited_command is not None and edited_command != original_command

        # SECURITY: Re-validate command if it was edited
        if was_edited:
            audit_log(AuditEventType.APPROVAL_EDITED, {
                "approval_id": approval_id,
                "original_command": original_command[:200],
                "edited_command": command[:200],
            })

            # Check if edited command is safe
            safe, warning = is_command_safe(command)
            if not safe:
                audit_log(AuditEventType.COMMAND_BLOCKED, {
                    "approval_id": approval_id,
                    "command": command[:200],
                    "reason": warning,
                })
                raise RpcError(
                    code=-32602,
                    message=f"Edited command blocked: {warning}. Cannot bypass safety checks by editing.",
                )

        # SECURITY: Rate limit sudo commands
        if "sudo " in command:
            try:
                check_rate_limit("sudo")
            except RateLimitExceeded as e:
                audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "sudo"})
                raise RpcError(code=-32429, message=str(e))

        # Execute the command
        try:
            result = execute_command(command)
            db.resolve_approval(approval_id=approval_id, status="approved")

            # SECURITY: Log command execution
            get_auditor().log_command_execution(
                command=command,
                success=result.returncode == 0,
                return_code=result.returncode,
                approval_id=approval_id,
                edited=was_edited,
            )

            return {
                "status": "executed",
                "result": {
                    "success": result.returncode == 0,
                    "stdout": result.stdout[:10000] if result.stdout else "",
                    "stderr": result.stderr[:10000] if result.stderr else "",
                    "return_code": result.returncode,
                    "command": command,
                },
            }
        except Exception as exc:
            db.resolve_approval(approval_id=approval_id, status="approved")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "approval_id": approval_id,
                "command": command[:200],
                "error": str(exc),
            }, success=False)
            return {
                "status": "error",
                "result": {"error": str(exc), "command": command},
            }

    raise RpcError(code=-32602, message=f"Invalid action: {action}")


def _handle_approval_explain(
    db: Database,
    *,
    approval_id: str,
) -> dict[str, Any]:
    """Get detailed explanation for an approval."""
    from .linux_tools import preview_command

    approval = db.get_approval(approval_id=approval_id)
    if approval is None:
        raise RpcError(code=-32602, message=f"Approval not found: {approval_id}")

    command = str(approval.get("command"))
    preview = preview_command(command)

    return {
        "command": command,
        "explanation": approval.get("explanation") or preview.description,
        "detailed_explanation": (
            f"Command: {command}\n\n"
            f"Description: {preview.description}\n\n"
            f"Affected paths: {', '.join(preview.affected_paths) if preview.affected_paths else 'None'}\n\n"
            f"Warnings: {', '.join(preview.warnings) if preview.warnings else 'None'}\n\n"
            f"Reversible: {'Yes' if preview.can_undo else 'No'}\n"
            f"Undo command: {preview.undo_command or 'N/A'}"
        ),
        "is_destructive": preview.is_destructive,
        "can_undo": preview.can_undo,
        "undo_command": preview.undo_command,
        "affected_paths": preview.affected_paths,
        "warnings": preview.warnings,
    }


# -------------------------------------------------------------------------
# Plan and Execution handlers (Phase 3 - Reasoning System)
# -------------------------------------------------------------------------

# Store active reasoning engines and executions per session
_reasoning_engines: dict[str, Any] = {}
_active_executions: dict[str, Any] = {}

# Store active Code Mode streaming executions
_active_code_executions: dict[str, Any] = {}
_code_exec_lock = threading.Lock()

# Store active Code Mode planning contexts (pre-approval phase)
_active_code_plans: dict[str, Any] = {}
_code_plan_lock = threading.Lock()


def _get_reasoning_engine(conversation_id: str, db: Database) -> Any:
    """Get or create a reasoning engine for a conversation."""
    from .reasoning.engine import ReasoningEngine

    if conversation_id not in _reasoning_engines:
        _reasoning_engines[conversation_id] = ReasoningEngine(db=db)
    return _reasoning_engines[conversation_id]


def _handle_plan_preview(
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






def _handle_execution_status(
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








# -------------------------------------------------------------------------
# Code Mode Diff Preview handlers
# -------------------------------------------------------------------------

# Track active diff preview managers per session
_diff_preview_managers: dict[str, "DiffPreviewManager"] = {}


def _get_diff_preview_manager(session_id: str, repo_path: str | None = None) -> "DiffPreviewManager":
    """Get or create a DiffPreviewManager for a session."""
    from pathlib import Path
    from .code_mode import CodeSandbox, DiffPreviewManager

    if session_id not in _diff_preview_managers:
        if not repo_path:
            raise RpcError(code=-32602, message="repo_path required for new diff session")
        sandbox = CodeSandbox(Path(repo_path))
        _diff_preview_managers[session_id] = DiffPreviewManager(sandbox)

    return _diff_preview_managers[session_id]






def _handle_code_diff_apply(
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


def _handle_code_diff_reject(
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




# -------------------------------------------------------------------------
# Repository Map handlers (Code Mode - semantic code understanding)
# -------------------------------------------------------------------------

# Track active RepoMap instances per session
_repo_map_instances: dict[str, "RepoMap"] = {}


def _get_repo_map(db: Database, session_id: str) -> "RepoMap":
    """Get or create a RepoMap instance for a session."""
    from pathlib import Path

    from .code_mode import CodeSandbox, RepoMap

    if session_id in _repo_map_instances:
        return _repo_map_instances[session_id]

    # Get repo path from session/sandbox
    if session_id not in _diff_preview_managers:
        raise ValueError(f"No sandbox found for session {session_id}")

    sandbox = _diff_preview_managers[session_id].sandbox
    repo_map = RepoMap(sandbox, db)
    _repo_map_instances[session_id] = repo_map
    return repo_map


















# -------------------------------------------------------------------------
# Streaming execution handlers (Phase 4)
# -------------------------------------------------------------------------






def _handle_execution_kill(
    db: Database,
    *,
    execution_id: str,
) -> dict[str, Any]:
    """Kill a running execution.

    Checks both streaming executor and Code Mode executions.
    """
    # First try streaming executor
    from .streaming_executor import get_streaming_executor

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


# -------------------------------------------------------------------------
# Code Mode Streaming Execution handlers
# -------------------------------------------------------------------------




def _handle_code_plan_approve(
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
    import json
    from pathlib import Path
    from .code_mode import (
        CodeSandbox,
        CodeExecutor,
        ExecutionObserver,
        create_execution_context,
    )
    from .code_mode.planner import (
        CodeTaskPlan,
        CodeStep,
        CodeStepType,
        ImpactLevel,
    )
    from .play_fs import list_acts

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
        from .providers import get_provider
        llm = get_provider(db)
    except Exception as e:
        logger.warning("Failed to get LLM provider, falling back to Ollama: %s", e)
        # Fall back to Ollama
        try:
            from .ollama import OllamaClient
            stored_url = db.get_state("ollama_url")
            stored_model = db.get_state("ollama_model")
            if stored_url and stored_model:
                llm = OllamaClient(base_url=stored_url, model=stored_model)
        except Exception as e2:
            logger.error("Failed to initialize Ollama fallback: %s", e2)

    # Get project memory if available
    project_memory = None
    try:
        from .code_mode.project_memory import ProjectMemoryStore
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


def _handle_code_exec_state(
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








# -------------------------------------------------------------------------
# Code Mode Session Logs (for debugging)
# -------------------------------------------------------------------------








# -------------------------------------------------------------------------
# Code Mode Planning handlers (Pre-approval streaming)
# -------------------------------------------------------------------------


def _handle_code_plan_start(
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
    from pathlib import Path
    from .code_mode.streaming import (
        create_planning_context,
        PlanningObserver,
        PlanningCancelledError,
    )
    from .code_mode.intent import IntentDiscoverer
    from .code_mode.contract import ContractBuilder
    from .code_mode import CodeSandbox, CodePlanner
    from .providers import get_provider, check_provider_health
    from .play_fs import list_acts

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


def _handle_code_plan_state(
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




def _handle_code_plan_result(
    db: Database,
    *,
    planning_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Get the final result of a completed planning session.

    This returns the full plan/contract for display and approval.
    """
    from .agent import _generate_id

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
    import json
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


# -------------------------------------------------------------------------
# System Dashboard handlers (Phase 5)
# -------------------------------------------------------------------------


def _handle_system_live_state(db: Database) -> dict[str, Any]:
    """Get comprehensive system state for dashboard."""
    from . import linux_tools

    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "cpu_model": "Unknown",
        "cpu_cores": 0,
        "memory": {"used_mb": 0, "total_mb": 0, "percent": 0.0},
        "disks": [],
        "load_avg": [0.0, 0.0, 0.0],
        "gpu": None,
        "services": [],
        "containers": [],
        "network": [],
        "ports": [],
        "traffic": [],
    }

    # Get system info
    try:
        info = linux_tools.get_system_info()
        result["cpu_percent"] = info.cpu_percent
        result["cpu_model"] = info.cpu_model
        result["cpu_cores"] = info.cpu_cores
        result["memory"] = {
            "used_mb": info.memory_used_mb,
            "total_mb": info.memory_total_mb,
            "percent": info.memory_percent,
        }
        result["disks"] = [
            {
                "mount": "/",
                "used_gb": info.disk_used_gb,
                "total_gb": info.disk_total_gb,
                "percent": info.disk_percent,
            }
        ]
        result["load_avg"] = list(info.load_avg)
        # Add GPU info if available
        if info.gpu_name is not None:
            result["gpu"] = {
                "name": info.gpu_name,
                "percent": info.gpu_percent,
                "memory_used_mb": info.gpu_memory_used_mb,
                "memory_total_mb": info.gpu_memory_total_mb,
            }
    except Exception as e:
        logger.debug("Failed to get system info: %s", e)
        result["_errors"] = result.get("_errors", []) + ["system_info"]

    # Get services (top 10 most relevant)
    try:
        all_services = linux_tools.list_services()
        # Prioritize running services, then sort by name
        sorted_services = sorted(
            all_services,
            key=lambda s: (0 if s.active_state == "active" else 1, s.name)
        )[:10]
        result["services"] = [
            {
                "name": s.name,
                "status": s.active_state,
                "active": s.active_state == "active",
            }
            for s in sorted_services
        ]
    except Exception as e:
        logger.debug("Failed to list services: %s", e)
        result["_errors"] = result.get("_errors", []) + ["services"]

    # Get containers if Docker is available
    try:
        containers = linux_tools.list_docker_containers()
        result["containers"] = [
            {
                "id": c.get("id", "")[:12],
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "status": c.get("status", "unknown"),
                "ports": c.get("ports", ""),
            }
            for c in containers[:10]
        ]
    except Exception as e:
        logger.debug("Failed to list containers (Docker may not be available): %s", e)
        # Don't add to errors - Docker being unavailable is normal

    # Get network interfaces
    try:
        network = linux_tools.get_network_info()
        if "interfaces" in network:
            result["network"] = [
                {
                    "interface": iface.get("name", ""),
                    "ip": iface.get("ipv4", ""),
                    "state": iface.get("state", "unknown"),
                }
                for iface in network["interfaces"][:5]
            ]
    except Exception as e:
        logger.debug("Failed to get network info: %s", e)
        result["_errors"] = result.get("_errors", []) + ["network"]

    # Get listening ports
    try:
        ports = linux_tools.list_listening_ports()
        result["ports"] = [
            {
                "port": p.port,
                "protocol": p.protocol,
                "address": p.address,
                "process": p.process,
                "pid": p.pid,
            }
            for p in ports[:20]  # Limit to 20 ports
        ]
    except Exception as e:
        logger.debug("Failed to list listening ports: %s", e)
        result["_errors"] = result.get("_errors", []) + ["ports"]

    # Get network traffic
    try:
        traffic = linux_tools.get_network_traffic()
        result["traffic"] = [
            {
                "interface": t.interface,
                "rx_bytes": t.rx_bytes,
                "tx_bytes": t.tx_bytes,
                "rx_formatted": linux_tools.format_bytes(t.rx_bytes),
                "tx_formatted": linux_tools.format_bytes(t.tx_bytes),
            }
            for t in traffic
        ]
    except Exception as e:
        logger.debug("Failed to get network traffic: %s", e)
        result["_errors"] = result.get("_errors", []) + ["traffic"]

    return result










def _handle_personas_list(db: Database) -> dict[str, Any]:
    return {"personas": db.iter_agent_personas(), "active_persona_id": db.get_active_persona_id()}


def _handle_persona_get(db: Database, *, persona_id: str) -> dict[str, Any]:
    persona = db.get_agent_persona(persona_id=persona_id)
    return {"persona": persona}


def _handle_persona_upsert(db: Database, *, persona: dict[str, Any]) -> dict[str, Any]:
    required = {
        "id",
        "name",
        "system_prompt",
        "default_context",
        "temperature",
        "top_p",
        "tool_call_limit",
    }
    missing = sorted(required - set(persona.keys()))
    if missing:
        raise RpcError(code=-32602, message=f"persona missing fields: {', '.join(missing)}")

    db.upsert_agent_persona(
        persona_id=str(persona["id"]),
        name=str(persona["name"]),
        system_prompt=str(persona["system_prompt"]),
        default_context=str(persona["default_context"]),
        temperature=float(persona["temperature"]),
        top_p=float(persona["top_p"]),
        tool_call_limit=int(persona["tool_call_limit"]),
    )
    return {"ok": True}


def _handle_persona_set_active(db: Database, *, persona_id: str | None) -> dict[str, Any]:
    if persona_id is not None and not isinstance(persona_id, str):
        raise RpcError(code=-32602, message="persona_id must be a string or null")
    db.set_active_persona_id(persona_id=persona_id)
    return {"ok": True}


# --- Hardware Detection ---

def _detect_system_hardware() -> dict[str, Any]:
    """Detect system hardware for model recommendations."""
    import subprocess
    import os

    result = {
        "ram_gb": 0,
        "gpu_available": False,
        "gpu_name": None,
        "gpu_vram_gb": None,
        "gpu_type": None,  # "nvidia", "amd", "apple", None
        "recommended_max_params": "3b",  # Conservative default
    }

    # Detect RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    result["ram_gb"] = round(kb / 1024 / 1024, 1)
                    break
    except Exception as e:
        logger.debug("Failed to detect RAM from /proc/meminfo: %s", e)

    # Detect NVIDIA GPU
    try:
        nvidia_out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if nvidia_out.returncode == 0 and nvidia_out.stdout.strip():
            lines = nvidia_out.stdout.strip().split("\n")
            if lines:
                parts = lines[0].split(", ")
                if len(parts) >= 2:
                    result["gpu_available"] = True
                    result["gpu_type"] = "nvidia"
                    result["gpu_name"] = parts[0].strip()
                    result["gpu_vram_gb"] = round(int(parts[1]) / 1024, 1)
    except FileNotFoundError:
        logger.debug("nvidia-smi not found - no NVIDIA GPU detected")
    except Exception as e:
        logger.debug("Failed to detect NVIDIA GPU: %s", e)

    # Detect AMD GPU (ROCm)
    if not result["gpu_available"]:
        try:
            rocm_out = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=5
            )
            if rocm_out.returncode == 0 and "GPU" in rocm_out.stdout:
                result["gpu_available"] = True
                result["gpu_type"] = "amd"
                result["gpu_name"] = "AMD GPU (ROCm)"
                # Parse VRAM from rocm-smi output (format varies)
                for line in rocm_out.stdout.split("\n"):
                    if "Total" in line and "MB" in line:
                        try:
                            mb = int("".join(filter(str.isdigit, line.split("Total")[1].split("MB")[0])))
                            result["gpu_vram_gb"] = round(mb / 1024, 1)
                        except (ValueError, IndexError) as e:
                            logger.debug("Failed to parse ROCm VRAM: %s", e)
        except FileNotFoundError:
            logger.debug("rocm-smi not found - no AMD GPU detected")
        except Exception as e:
            logger.debug("Failed to detect AMD GPU: %s", e)

    # Calculate recommended max parameters based on available memory
    # Use the larger of GPU VRAM (for fast inference) or RAM (for CPU offloading)
    # Ollama can use CPU offloading for layers that don't fit in VRAM
    gpu_mem = result["gpu_vram_gb"] or 0
    ram_mem = result["ram_gb"] or 0

    # For recommendations, consider both:
    # - GPU VRAM for fully GPU-accelerated models
    # - System RAM for larger models with CPU offloading
    # Use RAM as the ceiling since Ollama can offload
    available_mem = max(gpu_mem, ram_mem)

    if available_mem:
        if available_mem >= 128:
            result["recommended_max_params"] = "405b"  # Llama 3.1 405B needs ~200GB
        elif available_mem >= 64:
            result["recommended_max_params"] = "70b"
        elif available_mem >= 32:
            result["recommended_max_params"] = "34b"
        elif available_mem >= 16:
            result["recommended_max_params"] = "13b"
        elif available_mem >= 8:
            result["recommended_max_params"] = "8b"
        elif available_mem >= 6:
            result["recommended_max_params"] = "7b"
        elif available_mem >= 4:
            result["recommended_max_params"] = "3b"
        else:
            result["recommended_max_params"] = "1b"

    return result




def _handle_system_open_terminal(_db: Database) -> dict[str, Any]:
    """Open a terminal emulator window."""
    import shutil
    import subprocess

    # Try common Linux terminal emulators in order of preference
    terminals = [
        ["gnome-terminal"],
        ["konsole"],
        ["xfce4-terminal"],
        ["mate-terminal"],
        ["tilix"],
        ["x-terminal-emulator"],
        ["xterm"],
    ]

    for term_cmd in terminals:
        if shutil.which(term_cmd[0]):
            try:
                # Spawn detached from parent process
                subprocess.Popen(
                    term_cmd,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {"success": True, "terminal": term_cmd[0]}
            except Exception as e:
                logger.warning(f"Failed to launch {term_cmd[0]}: {e}")
                continue

    return {"success": False, "error": "No terminal emulator found"}


# --- Ollama Settings Handlers ---

def _handle_ollama_status(db: Database) -> dict[str, Any]:
    """Get Ollama connection status and current settings."""
    from .ollama import check_ollama, list_ollama_models
    from .settings import settings

    # Get stored settings
    stored_url = db.get_state(key="ollama_url")
    stored_model = db.get_state(key="ollama_model")
    stored_gpu_enabled = db.get_state(key="ollama_gpu_enabled")
    stored_num_ctx = db.get_state(key="ollama_num_ctx")

    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    model = stored_model if isinstance(stored_model, str) and stored_model else settings.ollama_model
    gpu_enabled = stored_gpu_enabled != "false"  # Default to true
    num_ctx = int(stored_num_ctx) if isinstance(stored_num_ctx, str) and stored_num_ctx.isdigit() else None

    # Check connection
    health = check_ollama(url=url)

    # List models if reachable
    models: list[str] = []
    if health.reachable:
        try:
            models = list_ollama_models(url=url)
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)

    # Get hardware info
    hardware = _detect_system_hardware()

    return {
        "url": url,
        "model": model,
        "reachable": health.reachable,
        "model_count": health.model_count,
        "error": health.error,
        "available_models": models,
        "gpu_enabled": gpu_enabled,
        "gpu_available": hardware["gpu_available"],
        "gpu_name": hardware["gpu_name"],
        "gpu_vram_gb": hardware["gpu_vram_gb"],
        "num_ctx": num_ctx,
        "hardware": hardware,
    }


def _handle_ollama_set_url(db: Database, *, url: str) -> dict[str, Any]:
    """Set Ollama URL."""
    from .ollama import check_ollama

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        raise RpcError(code=-32602, message="URL must start with http:// or https://")

    # Test connection
    health = check_ollama(url=url)
    if not health.reachable:
        raise RpcError(code=-32010, message=f"Cannot connect to Ollama at {url}: {health.error}")

    db.set_state(key="ollama_url", value=url)
    return {"ok": True, "url": url}


def _handle_ollama_set_model(db: Database, *, model: str) -> dict[str, Any]:
    """Set active Ollama model."""
    from .ollama import list_ollama_models

    stored_url = db.get_state(key="ollama_url")
    from .settings import settings
    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url

    # Verify model exists
    available = list_ollama_models(url=url)
    if model not in available:
        raise RpcError(code=-32602, message=f"Model '{model}' not found. Available: {', '.join(available[:5])}")

    db.set_state(key="ollama_model", value=model)
    return {"ok": True, "model": model}


def _handle_ollama_model_info(db: Database, *, model: str) -> dict[str, Any]:
    """Get detailed info about a model (params, context length, capabilities)."""
    import httpx
    from .settings import settings

    stored_url = db.get_state(key="ollama_url")
    url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    show_url = url.rstrip("/") + "/api/show"

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(show_url, json={"name": model})
            res.raise_for_status()
            data = res.json()

            # Extract relevant info
            details = data.get("details", {})
            model_info = data.get("model_info", {})
            parameters = data.get("parameters", "")
            template = data.get("template", "")
            modelfile = data.get("modelfile", "")

            # Parse parameter count from details or model name
            param_size = details.get("parameter_size", "")
            if not param_size:
                # Try to extract from model name (e.g., "llama3.1:8b" -> "8B")
                for part in model.replace(":", "-").replace("_", "-").split("-"):
                    part_lower = part.lower()
                    if part_lower.endswith("b") and part_lower[:-1].replace(".", "").isdigit():
                        param_size = part.upper()
                        break

            # Get context length from model_info or parameters
            context_length = None
            for key in model_info:
                if "context" in key.lower():
                    val = model_info[key]
                    if isinstance(val, (int, float)):
                        context_length = int(val)
                        break

            # Also check parameters string for num_ctx
            if context_length is None and "num_ctx" in parameters:
                for line in parameters.split("\n"):
                    if "num_ctx" in line:
                        try:
                            context_length = int(line.split()[-1])
                        except (ValueError, IndexError) as e:
                            logger.debug("Failed to parse num_ctx from model parameters: %s", e)

            # Default context lengths by model family
            if context_length is None:
                model_lower = model.lower()
                if "llama3" in model_lower or "llama-3" in model_lower:
                    context_length = 8192
                elif "mistral" in model_lower:
                    context_length = 32768
                elif "codellama" in model_lower:
                    context_length = 16384
                else:
                    context_length = 2048  # Conservative default

            # Detect capabilities
            capabilities = {
                "vision": False,
                "tools": False,
                "thinking": False,
                "embedding": False,
            }

            model_lower = model.lower()
            template_lower = template.lower()
            modelfile_lower = modelfile.lower()
            families = details.get("families", [])

            # Vision capability - check for vision/clip in model info
            if any("vision" in str(v).lower() or "clip" in str(v).lower()
                   for v in model_info.values()):
                capabilities["vision"] = True
            if "llava" in model_lower or "vision" in model_lower or "bakllava" in model_lower:
                capabilities["vision"] = True
            if "clip" in families:
                capabilities["vision"] = True

            # Tools capability - check template for tool markers
            tool_markers = ["<tool_call>", "<function_call>", "[TOOL]", "{{.ToolCall}}", "tools"]
            if any(marker.lower() in template_lower for marker in tool_markers):
                capabilities["tools"] = True
            # Known tool-capable models
            if any(name in model_lower for name in ["llama3.1", "llama3.2", "qwen2.5", "mistral", "mixtral"]):
                capabilities["tools"] = True

            # Thinking/reasoning capability
            thinking_markers = ["<think>", "<thinking>", "reasoning", "chain-of-thought"]
            if any(marker.lower() in template_lower for marker in thinking_markers):
                capabilities["thinking"] = True
            # Known thinking models
            if any(name in model_lower for name in ["deepseek", "qwq", "o1", "reflection"]):
                capabilities["thinking"] = True

            # Embedding capability
            if "embed" in model_lower or details.get("format") == "embedding":
                capabilities["embedding"] = True

            return {
                "model": model,
                "parameter_size": param_size,
                "family": details.get("family", ""),
                "families": families,
                "quantization": details.get("quantization_level", ""),
                "context_length": context_length,
                "format": details.get("format", ""),
                "capabilities": capabilities,
            }
    except Exception as e:
        return {
            "model": model,
            "error": str(e),
            "parameter_size": None,
            "context_length": None,
            "capabilities": {"vision": False, "tools": False, "thinking": False, "embedding": False},
        }


def _handle_ollama_set_gpu(db: Database, *, enabled: bool) -> dict[str, Any]:
    """Enable or disable GPU inference."""
    db.set_state(key="ollama_gpu_enabled", value="true" if enabled else "false")
    return {"ok": True, "gpu_enabled": enabled}


def _handle_ollama_set_context(db: Database, *, num_ctx: int) -> dict[str, Any]:
    """Set context length for inference."""
    if num_ctx < 512:
        raise RpcError(code=-32602, message="Context length must be at least 512")
    if num_ctx > 131072:
        raise RpcError(code=-32602, message="Context length cannot exceed 131072")

    db.set_state(key="ollama_num_ctx", value=str(num_ctx))
    return {"ok": True, "num_ctx": num_ctx}


# Global dict to track ongoing pulls
_active_pulls: dict[str, dict[str, Any]] = {}
_pull_lock = threading.Lock()


def _handle_ollama_pull_start(db: Database, *, model: str) -> dict[str, Any]:
    """Start pulling a new Ollama model in background. Returns pull_id for tracking."""
    import uuid
    from .settings import settings

    stored_url = db.get_state(key="ollama_url")
    base_url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url
    pull_url = base_url.rstrip("/") + "/api/pull"

    pull_id = str(uuid.uuid4())[:8]

    # Initialize pull state
    with _pull_lock:
        _active_pulls[pull_id] = {
            "model": model,
            "status": "starting",
            "progress": 0,
            "total": 0,
            "completed": 0,
            "error": None,
            "done": False,
        }

    def do_pull() -> None:
        import httpx

        try:
            with httpx.Client(timeout=None) as client:
                # Stream the pull to get progress updates
                with client.stream("POST", pull_url, json={"name": model, "stream": True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            with _pull_lock:
                                if pull_id not in _active_pulls:
                                    break
                                pull_state = _active_pulls[pull_id]
                                pull_state["status"] = data.get("status", "downloading")

                                # Update progress if available
                                if "total" in data and "completed" in data:
                                    total = data["total"]
                                    completed = data["completed"]
                                    pull_state["total"] = total
                                    pull_state["completed"] = completed
                                    if total > 0:
                                        pull_state["progress"] = int((completed / total) * 100)

                                # Check for completion
                                if data.get("status") == "success":
                                    pull_state["done"] = True
                                    pull_state["progress"] = 100

                                # Check for error
                                if "error" in data:
                                    pull_state["error"] = data["error"]
                                    pull_state["done"] = True
                        except json.JSONDecodeError:
                            continue

            # Mark as done if we exit cleanly
            with _pull_lock:
                if pull_id in _active_pulls:
                    _active_pulls[pull_id]["done"] = True
                    if _active_pulls[pull_id]["progress"] == 0:
                        _active_pulls[pull_id]["progress"] = 100

        except Exception as e:
            with _pull_lock:
                if pull_id in _active_pulls:
                    _active_pulls[pull_id]["error"] = str(e)
                    _active_pulls[pull_id]["done"] = True

    # Start pull in background thread
    thread = threading.Thread(target=do_pull, daemon=True)
    thread.start()

    return {"pull_id": pull_id, "model": model}


def _handle_ollama_pull_status(*, pull_id: str) -> dict[str, Any]:
    """Get status of an ongoing pull."""
    with _pull_lock:
        if pull_id not in _active_pulls:
            return {"error": "Pull not found", "done": True}

        state = _active_pulls[pull_id].copy()

        # Clean up completed pulls after reporting
        if state["done"]:
            del _active_pulls[pull_id]

        return state




def _handle_ollama_test_connection(db: Database, *, url: str | None = None) -> dict[str, Any]:
    """Test Ollama connection."""
    from .ollama import check_ollama
    from .settings import settings

    if url is None:
        stored_url = db.get_state(key="ollama_url")
        url = stored_url if isinstance(stored_url, str) and stored_url else settings.ollama_url

    health = check_ollama(url=url)
    return {
        "url": url,
        "reachable": health.reachable,
        "model_count": health.model_count,
        "error": health.error,
    }


def _handle_ollama_check_installed(_db: Database) -> dict[str, Any]:
    """Check if Ollama is installed on the system."""
    from .providers import check_ollama_installed, get_ollama_install_command

    return {
        "installed": check_ollama_installed(),
        "install_command": get_ollama_install_command(),
    }


# --- Provider Settings Handlers ---


def _handle_providers_list(db: Database) -> dict[str, Any]:
    """List available LLM providers and current selection."""
    from .providers import (
        list_providers,
        get_current_provider_type,
        check_keyring_available,
        has_api_key,
    )

    current = get_current_provider_type(db)
    providers = list_providers()

    return {
        "current_provider": current,
        "available_providers": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "is_local": p.is_local,
                "requires_api_key": p.requires_api_key,
                "has_api_key": has_api_key(p.id) if p.requires_api_key else None,
            }
            for p in providers
        ],
        "keyring_available": check_keyring_available(),
    }


def _handle_providers_set(db: Database, *, provider: str) -> dict[str, Any]:
    """Set active LLM provider."""
    from .providers import set_provider_type, get_provider_info, LLMError

    info = get_provider_info(provider)
    if not info:
        raise RpcError(code=-32602, message=f"Unknown provider: {provider}")

    try:
        set_provider_type(db, provider)
    except LLMError as e:
        raise RpcError(code=-32010, message=str(e)) from e

    return {"ok": True, "provider": provider}




def _handle_anthropic_set_key(db: Database, *, api_key: str) -> dict[str, Any]:
    """Store Anthropic API key in system keyring."""
    from .providers import store_api_key, AnthropicProvider, check_keyring_available

    if not api_key or len(api_key) < 10:
        raise RpcError(code=-32602, message="Invalid API key format")

    if not check_keyring_available():
        raise RpcError(
            code=-32010,
            message="System keyring not available. Cannot securely store API key.",
        )

    # Test the key before storing
    try:
        provider = AnthropicProvider(api_key=api_key)
        health = provider.check_health()
        if not health.reachable:
            raise RpcError(
                code=-32010,
                message=f"Invalid API key: {health.error or 'Connection failed'}",
            )
    except Exception as e:
        if "RpcError" in str(type(e)):
            raise
        raise RpcError(code=-32010, message=f"API key validation failed: {e}") from e

    # Store the key
    store_api_key("anthropic", api_key)

    return {"ok": True}


def _handle_anthropic_delete_key(_db: Database) -> dict[str, Any]:
    """Delete Anthropic API key from keyring."""
    from .providers import delete_api_key

    deleted = delete_api_key("anthropic")
    return {"ok": deleted}


def _handle_anthropic_set_model(db: Database, *, model: str) -> dict[str, Any]:
    """Set Anthropic model preference."""
    from .providers import CLAUDE_MODELS

    valid_models = [m.name for m in CLAUDE_MODELS]
    if model not in valid_models:
        raise RpcError(
            code=-32602,
            message=f"Invalid model. Valid options: {', '.join(valid_models)}",
        )

    db.set_state(key="anthropic_model", value=model)
    return {"ok": True, "model": model}


def _handle_anthropic_status(db: Database) -> dict[str, Any]:
    """Get Anthropic provider status."""
    from .providers import (
        AnthropicProvider,
        get_api_key,
        has_api_key,
        check_keyring_available,
        CLAUDE_MODELS,
    )
    from dataclasses import asdict

    has_key = has_api_key("anthropic")
    stored_model = db.get_state(key="anthropic_model")
    model = stored_model if stored_model else "claude-sonnet-4-20250514"

    result = {
        "has_api_key": has_key,
        "keyring_available": check_keyring_available(),
        "model": model,
        "available_models": [
            {
                "name": m.name,
                "context_length": m.context_length,
                "capabilities": m.capabilities,
                "description": m.description,
            }
            for m in CLAUDE_MODELS
        ],
    }

    # Test connection if key is available
    if has_key:
        try:
            api_key = get_api_key("anthropic")
            if api_key:
                provider = AnthropicProvider(api_key=api_key, model=model)
                health = provider.check_health()
                result["health"] = asdict(health)
            else:
                result["health"] = {"reachable": False, "error": "No API key found"}
        except Exception as e:
            result["health"] = {"reachable": False, "error": str(e)}
    else:
        result["health"] = {"reachable": False, "error": "No API key configured"}

    return result


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _handle_play_me_read(_db: Database) -> dict[str, Any]:
    return {"markdown": play_read_me_markdown()}


def _handle_play_me_write(_db: Database, *, text: str) -> dict[str, Any]:
    play_write_me_markdown(text)
    return {"ok": True}


def _handle_play_acts_list(_db: Database) -> dict[str, Any]:
    acts, active_id = play_list_acts()
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def _handle_play_acts_set_active(_db: Database, *, act_id: str | None) -> dict[str, Any]:
    """Set active act, or clear it if act_id is None."""
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def _handle_play_scenes_list(_db: Database, *, act_id: str) -> dict[str, Any]:
    scenes = play_list_scenes(act_id=act_id)
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_beats_list(_db: Database, *, act_id: str, scene_id: str) -> dict[str, Any]:
    beats = play_list_beats(act_id=act_id, scene_id=scene_id)
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "stage": b.stage,
                "notes": b.notes,
                "link": b.link,
                "calendar_event_id": b.calendar_event_id,
                "recurrence_rule": b.recurrence_rule,
            }
            for b in beats
        ]
    }


def _handle_play_acts_create(_db: Database, *, title: str, notes: str | None = None) -> dict[str, Any]:
    try:
        acts, created_id = play_create_act(title=title, notes=notes or "")
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "created_act_id": created_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path}
            for a in acts
        ],
    }


def _handle_play_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes, color=color)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def _handle_play_acts_assign_repo(
    _db: Database,
    *,
    act_id: str,
    repo_path: str,
) -> dict[str, Any]:
    """Assign a repository path to an act. Creates the directory if it doesn't exist."""
    from pathlib import Path
    import subprocess

    path = Path(repo_path).expanduser().resolve()

    # Create directory if it doesn't exist
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    # Initialize git repo if not already a git repo
    git_dir = path / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        # Create initial commit to have a valid repo
        readme = path / "README.md"
        if not readme.exists():
            readme.write_text(f"# Project\n\nCreated by ReOS\n")
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), capture_output=True, check=True)

    try:
        acts, _active_id = play_assign_repo_to_act(act_id=act_id, repo_path=str(path))
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc

    return {
        "success": True,
        "repo_path": str(path),
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path}
            for a in acts
        ],
    }


def _handle_play_scenes_create(
    _db: Database,
    *,
    act_id: str,
    title: str,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        scenes = play_create_scene(
            act_id=act_id,
            title=title,
            intent=intent or "",
            status=status or "",
            time_horizon=time_horizon or "",
            notes=notes or "",
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_scenes_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        scenes = play_update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            intent=intent,
            status=status,
            time_horizon=time_horizon,
            notes=notes,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "title": s.title,
                "intent": s.intent,
                "status": s.status,
                "time_horizon": s.time_horizon,
                "notes": s.notes,
            }
            for s in scenes
        ]
    }


def _handle_play_beats_create(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    title: str,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_create_beat(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            stage=stage or "",
            notes=notes or "",
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "stage": b.stage,
                "notes": b.notes,
                "link": b.link,
                "calendar_event_id": b.calendar_event_id,
                "recurrence_rule": b.recurrence_rule,
            }
            for b in beats
        ]
    }


def _handle_play_beats_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,
    beat_id: str,
    title: str | None = None,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_update_beat(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            title=title,
            stage=stage,
            notes=notes,
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": b.beat_id,
                "title": b.title,
                "stage": b.stage,
                "notes": b.notes,
                "link": b.link,
                "calendar_event_id": b.calendar_event_id,
                "recurrence_rule": b.recurrence_rule,
            }
            for b in beats
        ]
    }


def _handle_play_beats_move(
    db: Database,
    *,
    beat_id: str,
    source_act_id: str,
    source_scene_id: str,
    target_act_id: str,
    target_scene_id: str,
) -> dict[str, Any]:
    """Move a Beat from one Scene to another."""
    try:
        result = play_move_beat(
            beat_id=beat_id,
            source_act_id=source_act_id,
            source_scene_id=source_scene_id,
            target_act_id=target_act_id,
            target_scene_id=target_scene_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc

    # After successful move, update CAIRN cache so "What Needs Attention" shows correct Act
    try:
        play_path = get_current_play_path(db)
        if play_path:
            from .cairn.store import CairnStore

            store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
            store.update_beat_location(beat_id, target_act_id, target_scene_id)
    except Exception:
        pass  # Don't fail the move if cache update fails

    return result


def _handle_play_kb_list(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    try:
        files = play_kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"files": files}


def _handle_play_kb_read(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str = "kb.md",
) -> dict[str, Any]:
    try:
        text = play_kb_read(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path)
    except FileNotFoundError as exc:
        raise RpcError(code=-32602, message=f"file not found: {exc}") from exc
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"path": path, "text": text}


def _handle_play_kb_write_preview(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    try:
        res = play_kb_write_preview(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path, text=text)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "path": path,
        "expected_sha256_current": res["sha256_current"],
        **res,
    }


def _handle_play_kb_write_apply(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=-32602, message="expected_sha256_current is required")
    try:
        res = play_kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256_current,
        )
    except ValueError as exc:
        # Surface conflicts as a deterministic JSON-RPC error.
        raise RpcError(code=-32009, message=str(exc)) from exc
    return {"path": path, **res}


def _handle_play_attachments_list(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    try:
        attachments = play_list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


def _handle_play_attachments_add(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> dict[str, Any]:
    try:
        attachments = play_add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            file_path=file_path,
            file_name=file_name,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


def _handle_play_attachments_remove(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    attachment_id: str,
) -> dict[str, Any]:
    try:
        attachments = play_remove_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


# --- Context Meter & Knowledge Management Handlers ---

def _handle_context_stats(
    db: Database,
    *,
    conversation_id: str | None = None,
    context_limit: int | None = None,
    include_breakdown: bool = False,
) -> dict[str, Any]:
    """Get context usage statistics for a conversation."""
    from .agent import ChatAgent
    from .system_state import SteadyStateCollector

    messages: list[dict[str, Any]] = []
    if conversation_id:
        raw_messages = db.get_messages(conversation_id=conversation_id, limit=100)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in raw_messages
        ]

    # Get active act for learned KB
    acts, active_act_id = play_list_acts()
    learned_kb = ""
    store = KnowledgeStore()
    if active_act_id:
        learned_kb = store.get_learned_markdown(active_act_id)

    # Get system state context
    system_state = ""
    try:
        collector = SteadyStateCollector()
        state = collector.refresh_if_stale(max_age_seconds=3600)
        system_state = state.to_context_string()
    except Exception as e:
        logger.debug("Failed to get system state for context stats: %s", e)

    # Get system prompt from persona
    system_prompt = ""
    try:
        persona_id = db.get_active_persona_id()
        if persona_id:
            persona = db.get_agent_persona(persona_id=persona_id)
            if persona:
                system_prompt = persona.get("system_prompt", "")
        if not system_prompt:
            # Default system prompt estimate
            system_prompt = "x" * 8000  # ~2000 tokens
    except Exception as e:
        logger.debug("Failed to get persona for context stats: %s", e)
        system_prompt = "x" * 8000

    # Get play context
    play_context = ""
    try:
        play_context = play_read_me_markdown()
    except Exception as e:
        logger.debug("Failed to get play context for context stats: %s", e)

    # Get context limit from model settings if not provided
    if context_limit is None:
        num_ctx_raw = db.get_state(key="ollama_num_ctx")
        if num_ctx_raw:
            # num_ctx is stored as string, convert to int
            try:
                context_limit = int(num_ctx_raw)
            except (ValueError, TypeError):
                context_limit = 8192
        else:
            # Default to 8K if not set
            context_limit = 8192

    # Get disabled sources from settings
    disabled_sources_str = db.get_state(key="context_disabled_sources")
    disabled_sources: set[str] = set()
    if disabled_sources_str and isinstance(disabled_sources_str, str):
        disabled_sources = set(s.strip() for s in disabled_sources_str.split(",") if s.strip())

    stats = calculate_context_stats(
        messages=messages,
        system_prompt=system_prompt,
        play_context=play_context,
        learned_kb=learned_kb,
        system_state=system_state,
        context_limit=context_limit,
        include_breakdown=include_breakdown,
        disabled_sources=disabled_sources,
    )

    return stats.to_dict()


def _handle_context_toggle_source(
    db: Database,
    *,
    source_name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle a context source on or off."""
    # Get current disabled sources
    disabled_sources_str = db.get_state(key="context_disabled_sources")
    disabled_sources: set[str] = set()
    if disabled_sources_str and isinstance(disabled_sources_str, str):
        disabled_sources = set(s.strip() for s in disabled_sources_str.split(",") if s.strip())

    # Validate source name (using shared constant)
    if source_name not in VALID_SOURCE_NAMES:
        raise RpcError(code=-32602, message=f"Invalid source name: {source_name}")

    # Don't allow disabling non-disableable sources (system_prompt, messages)
    if not enabled and source_name not in DISABLEABLE_SOURCES:
        raise RpcError(code=-32602, message=f"Cannot disable '{source_name}' - it is required for operation")

    # Update disabled sources
    if enabled:
        disabled_sources.discard(source_name)
    else:
        disabled_sources.add(source_name)

    # Save back to db
    db.set_state(key="context_disabled_sources", value=",".join(sorted(disabled_sources)))

    return {"ok": True, "disabled_sources": list(disabled_sources)}


def _handle_archive_save(
    db: Database,
    *,
    conversation_id: str,
    act_id: str | None = None,
    title: str | None = None,
    generate_summary: bool = False,
) -> dict[str, Any]:
    """Archive a conversation."""
    raw_messages = db.get_messages(conversation_id=conversation_id, limit=500)
    if not raw_messages:
        raise RpcError(code=-32602, message="No messages in conversation")

    messages = [
        {
            "role": m["role"],
            "content": m["content"],
            "created_at": m.get("created_at", ""),
        }
        for m in raw_messages
    ]

    summary = ""
    if generate_summary:
        summary = generate_archive_summary(messages)

    store = KnowledgeStore()
    archive = store.save_archive(
        messages=messages,
        act_id=act_id,
        title=title,
        summary=summary,
    )

    return {
        "archive_id": archive.archive_id,
        "title": archive.title,
        "message_count": archive.message_count,
        "archived_at": archive.archived_at,
        "summary": archive.summary,
    }










def _handle_compact_preview(
    db: Database,
    *,
    conversation_id: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Preview knowledge extraction before compacting."""
    raw_messages = db.get_messages(conversation_id=conversation_id, limit=500)
    if not raw_messages:
        raise RpcError(code=-32602, message="No messages in conversation")

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in raw_messages
    ]

    # Get existing knowledge to help LLM avoid duplicates
    store = KnowledgeStore()
    existing_kb = store.get_learned_markdown(act_id)

    # Extract knowledge
    entries = extract_knowledge_from_messages(
        messages,
        existing_knowledge=existing_kb,
    )

    return {
        "entries": entries,
        "message_count": len(messages),
        "existing_entry_count": store.get_learned_entry_count(act_id),
    }


def _handle_compact_apply(
    db: Database,
    *,
    conversation_id: str,
    act_id: str | None = None,
    entries: list[dict[str, str]],
    archive_first: bool = True,
) -> dict[str, Any]:
    """Apply compaction: save knowledge, optionally archive, then can clear chat."""
    store = KnowledgeStore()

    # Optionally archive first
    archive_id = None
    if archive_first:
        raw_messages = db.get_messages(conversation_id=conversation_id, limit=500)
        if raw_messages:
            messages = [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m.get("created_at", ""),
                }
                for m in raw_messages
            ]
            archive = store.save_archive(
                messages=messages,
                act_id=act_id,
                title=None,
                summary="(compacted)",
            )
            archive_id = archive.archive_id

    # Add learned entries
    added = store.add_learned_entries(
        entries=entries,
        act_id=act_id,
        source_archive_id=archive_id,
        deduplicate=True,
    )

    return {
        "added_count": len(added),
        "archive_id": archive_id,
        "total_entries": store.get_learned_entry_count(act_id),
    }






def _handle_chat_clear(
    db: Database,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    """Clear (delete) a conversation without archiving."""
    # Delete all messages in the conversation
    db.execute(
        "DELETE FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    )
    # Delete the conversation itself
    db.execute(
        "DELETE FROM conversations WHERE conversation_id = ?",
        (conversation_id,),
    )
    return {"ok": True}


# -------------------------------------------------------------------------
# CAIRN (Attention Minder)
# -------------------------------------------------------------------------

def _handle_cairn_thunderbird_status(_db: Database) -> dict[str, Any]:
    """Check if Thunderbird integration is available."""
    from .cairn.thunderbird import ThunderbirdBridge

    bridge = ThunderbirdBridge.auto_detect()
    if bridge is None:
        return {
            "available": False,
            "message": "Thunderbird profile not detected. Install Thunderbird and create a profile to enable calendar and contact integration.",
        }

    status = bridge.get_status()
    return {
        "available": True,
        "profile_path": str(bridge.config.profile_path),
        "has_contacts": status.get("contacts_available", False),
        "has_calendar": status.get("calendar_available", False),
        "contact_count": status.get("contact_count", 0),
    }


def _handle_thunderbird_check(db: Database) -> dict[str, Any]:
    """Check Thunderbird installation and discover profiles."""
    from .cairn.thunderbird import (
        get_thunderbird_integration_state,
        ThunderbirdProfile,
        ThunderbirdAccount,
    )
    from .cairn.store import CairnStore

    # Get integration state from Thunderbird
    integration = get_thunderbird_integration_state()

    # Get stored preferences
    play_path = get_current_play_path(db)
    if play_path:
        store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
        stored_state = store.get_integration_state("thunderbird")
    else:
        stored_state = None

    # Determine integration state
    if stored_state and stored_state["state"] == "declined":
        state = "declined"
    elif stored_state and stored_state["state"] == "active":
        state = "active"
    else:
        state = "not_configured"

    # Serialize profiles
    def serialize_account(acc: ThunderbirdAccount) -> dict:
        return {
            "id": acc.id,
            "name": acc.name,
            "email": acc.email,
            "type": acc.type,
            "server": acc.server,
            "calendars": acc.calendars,
            "address_books": acc.address_books,
        }

    def serialize_profile(prof: ThunderbirdProfile) -> dict:
        return {
            "name": prof.name,
            "path": str(prof.path),
            "is_default": prof.is_default,
            "accounts": [serialize_account(a) for a in prof.accounts],
        }

    return {
        "installed": integration.installed,
        "install_suggestion": integration.install_suggestion,
        "profiles": [serialize_profile(p) for p in integration.profiles],
        "integration_state": state,
        "active_profiles": stored_state["config"].get("active_profiles", []) if stored_state and stored_state["config"] else [],
    }


def _handle_thunderbird_configure(
    db: Database,
    *,
    active_profiles: list[str],
    active_accounts: list[str] | None = None,
    all_active: bool = False,
) -> dict[str, Any]:
    """Configure Thunderbird integration."""
    from .cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")

    config = {
        "active_profiles": active_profiles,
        "active_accounts": active_accounts or [],
        "all_active": all_active,
    }

    store.set_integration_active("thunderbird", config)

    return {"success": True, "config": config}


def _handle_thunderbird_decline(db: Database) -> dict[str, Any]:
    """Mark Thunderbird integration as declined (never ask again)."""
    from .cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
    store.set_integration_declined("thunderbird")

    return {"success": True}


def _handle_thunderbird_reset(db: Database) -> dict[str, Any]:
    """Reset Thunderbird integration (re-enable prompts)."""
    from .cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
    store.clear_integration_decline("thunderbird")

    return {"success": True}


def _handle_cairn_attention(
    db: Database,
    *,
    hours: int = 168,  # 7 days
    limit: int = 10,
) -> dict[str, Any]:
    """Get items that need attention - primarily upcoming calendar events.

    Shows the next 7 days by default for the 'What Needs My Attention' section.
    """
    from .cairn.store import CairnStore
    from .cairn.surfacing import CairnSurfacer
    from .cairn.thunderbird import ThunderbirdBridge

    play_path = get_current_play_path(db)
    if not play_path:
        return {"count": 0, "items": []}

    # Set up CAIRN components
    cairn_db_path = Path(play_path) / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db_path)

    # Get Thunderbird bridge if configured
    thunderbird = None
    tb_state = store.get_integration_state("thunderbird")
    if tb_state and tb_state["state"] == "active":
        thunderbird = ThunderbirdBridge.auto_detect()

    # Create surfacer and get attention items
    surfacer = CairnSurfacer(
        cairn_store=store,
        thunderbird=thunderbird,
    )

    items = surfacer.surface_attention(hours=hours, limit=limit)

    # Build act_id -> title/color lookup from play_fs
    from . import play_fs
    acts, _ = play_fs.list_acts()
    act_info = {a.act_id: {"title": a.title, "color": a.color} for a in acts}

    return {
        "count": len(items),
        "items": [
            {
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "title": item.title,
                "reason": item.reason,
                "urgency": item.urgency,
                "calendar_start": item.calendar_start.isoformat() if item.calendar_start else None,
                "calendar_end": item.calendar_end.isoformat() if item.calendar_end else None,
                "is_recurring": item.is_recurring,
                "recurrence_frequency": item.recurrence_frequency,
                "next_occurrence": item.next_occurrence.isoformat() if item.next_occurrence else None,
                "act_id": item.act_id,
                "scene_id": item.scene_id,
                "act_title": act_info.get(item.act_id, {}).get("title") if item.act_id else None,
                "act_color": act_info.get(item.act_id, {}).get("color") if item.act_id else None,
            }
            for item in items
        ],
    }


# -------------------------------------------------------------------------
# Safety & Security Settings
# -------------------------------------------------------------------------

def _handle_safety_settings(_db: Database) -> dict[str, Any]:
    """Get current safety settings and limits."""
    from . import linux_tools
    from .code_mode import executor as code_executor

    rate_limiter = get_rate_limiter()
    sudo_count, sudo_max = linux_tools.get_sudo_escalation_status()

    # Build rate limits dict
    rate_limits = {}
    for category, config in rate_limiter._limits.items():
        rate_limits[category] = {
            "max_requests": config.max_requests,
            "window_seconds": config.window_seconds,
            "name": config.name,
        }

    return {
        "rate_limits": rate_limits,
        "max_sudo_escalations": sudo_max,
        "current_sudo_count": sudo_count,
        "max_command_length": MAX_COMMAND_LEN,
        "max_iterations": code_executor.ExecutionState.max_iterations,
        "wall_clock_timeout_seconds": code_executor.DEFAULT_WALL_CLOCK_TIMEOUT_SECONDS,
        "max_service_name_length": MAX_SERVICE_NAME_LEN,
        "max_container_id_length": MAX_CONTAINER_ID_LEN,
        "max_package_name_length": MAX_PACKAGE_NAME_LEN,
        "dangerous_pattern_count": len(DANGEROUS_PATTERNS),
        "injection_pattern_count": len(INJECTION_PATTERNS),
    }


def _handle_safety_set_rate_limit(
    _db: Database,
    *,
    category: str,
    max_requests: int,
    window_seconds: float,
) -> dict[str, Any]:
    """Update a rate limit configuration."""
    rate_limiter = get_rate_limiter()

    # Validate bounds
    if max_requests < 1:
        max_requests = 1
    if max_requests > 100:
        max_requests = 100
    if window_seconds < 10:
        window_seconds = 10
    if window_seconds > 600:
        window_seconds = 600

    rate_limiter.configure(category, max_requests, window_seconds)

    return {
        "success": True,
        "category": category,
        "max_requests": max_requests,
        "window_seconds": window_seconds,
    }


def _handle_safety_set_sudo_limit(
    db: Database,
    *,
    max_escalations: int,
) -> dict[str, Any]:
    """Update the sudo escalation limit."""
    from . import linux_tools

    # Validate bounds (1-20)
    if max_escalations < 1:
        max_escalations = 1
    if max_escalations > 20:
        max_escalations = 20

    # Update the module-level constant
    linux_tools._MAX_SUDO_ESCALATIONS = max_escalations

    # Persist to database
    db.set_state(key="safety_sudo_limit", value=str(max_escalations))

    return {
        "success": True,
        "max_escalations": max_escalations,
    }


def _handle_safety_set_command_length(
    db: Database,
    *,
    max_length: int,
) -> dict[str, Any]:
    """Update the maximum command length."""
    from . import security

    # Validate bounds (512-32768)
    if max_length < 512:
        max_length = 512
    if max_length > 32768:
        max_length = 32768

    # Update the module-level constant
    security.MAX_COMMAND_LEN = max_length

    # Persist to database
    db.set_state(key="safety_command_length", value=str(max_length))

    return {
        "success": True,
        "max_length": max_length,
    }


def _handle_safety_set_max_iterations(
    db: Database,
    *,
    max_iterations: int,
) -> dict[str, Any]:
    """Update the maximum iterations for agent execution."""
    from .code_mode import executor as code_executor

    # Validate bounds (3-100)
    if max_iterations < 3:
        max_iterations = 3
    if max_iterations > 100:
        max_iterations = 100

    # Update the dataclass default
    code_executor.ExecutionState.max_iterations = max_iterations

    # Persist to database
    db.set_state(key="safety_max_iterations", value=str(max_iterations))

    return {
        "success": True,
        "max_iterations": max_iterations,
    }


def _handle_safety_set_wall_clock_timeout(
    db: Database,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Update the wall-clock timeout for agent execution."""
    from .code_mode import executor as code_executor

    # Validate bounds (60s - 3600s / 1 hour max)
    if timeout_seconds < 60:
        timeout_seconds = 60
    if timeout_seconds > 3600:
        timeout_seconds = 3600

    # Update the module-level constant
    code_executor.DEFAULT_WALL_CLOCK_TIMEOUT_SECONDS = timeout_seconds

    # Persist to database
    db.set_state(key="safety_wall_clock_timeout", value=str(timeout_seconds))

    return {
        "success": True,
        "timeout_seconds": timeout_seconds,
    }


# -------------------------------------------------------------------------
# Handoff System (Talking Rock Multi-Agent)
# -------------------------------------------------------------------------

# Global state for handoff management (per-session)
# Protected by _handoff_lock for thread safety
_handoff_state: dict[str, Any] = {
    "current_agent": "cairn",  # Default entry point
    "pending_handoff": None,
    "handler": None,
}
_handoff_lock = threading.Lock()


def _get_handoff_handler():
    """Get or create the handoff handler.

    Note: Caller must hold _handoff_lock.
    """
    from reos.handoff import AgentType, SharedToolHandler

    if _handoff_state["handler"] is None:
        current = AgentType(_handoff_state["current_agent"])
        _handoff_state["handler"] = SharedToolHandler(current_agent=current)
    return _handoff_state["handler"]
















def _handle_handoff_validate_all(_db: Database) -> dict[str, Any]:
    """Validate all agent manifests (15-tool cap check)."""
    from reos.handoff import validate_all_manifests

    return validate_all_manifests()



# -------------------------------------------------------------------------
# RPC Handler Registry - Simple handlers dispatched via lookup
# -------------------------------------------------------------------------

from typing import Callable

# Handlers with no params - just call handler(db)
_SIMPLE_HANDLERS: dict[str, Callable[[Database], Any]] = {
    "system/live_state": _handle_system_live_state,
    "personas/list": _handle_personas_list,
    "ollama/status": _handle_ollama_status,
    "system/open-terminal": _handle_system_open_terminal,
    "ollama/check_installed": _handle_ollama_check_installed,
    "providers/list": _handle_providers_list,
    "anthropic/status": _handle_anthropic_status,
    "anthropic/delete_key": _handle_anthropic_delete_key,
    "play/acts/list": _handle_play_acts_list,
    "safety/settings": _handle_safety_settings,
    "cairn/thunderbird/status": _handle_cairn_thunderbird_status,
    "thunderbird/check": _handle_thunderbird_check,
    "thunderbird/reset": _handle_thunderbird_reset,
}

# Handlers with single required string param: (handler, param_name)
_STRING_PARAM_HANDLERS: dict[str, tuple[Callable, str]] = {
    "ollama/set_url": (_handle_ollama_set_url, "url"),
    "ollama/set_model": (_handle_ollama_set_model, "model"),
    "ollama/model_info": (_handle_ollama_model_info, "model"),
    "ollama/pull_start": (_handle_ollama_pull_start, "model"),
    "anthropic/set_key": (_handle_anthropic_set_key, "key"),
    "anthropic/set_model": (_handle_anthropic_set_model, "model"),
    "thunderbird/configure": (_handle_thunderbird_configure, "db_path"),
    "code/diff/apply": (_handle_code_diff_apply, "preview_id"),
    "code/diff/reject": (_handle_code_diff_reject, "preview_id"),
}

# Handlers with NO db param, single string param: (handler, param_name)
_NO_DB_STRING_HANDLERS: dict[str, tuple[Callable, str]] = {
    "ollama/pull_status": (_handle_ollama_pull_status, "pull_id"),
}

# Handlers with single required int param: (handler, param_name)
_INT_PARAM_HANDLERS: dict[str, tuple[Callable, str]] = {
    "safety/set_sudo_limit": (_handle_safety_set_sudo_limit, "max_escalations"),
    "safety/set_command_length": (_handle_safety_set_command_length, "max_length"),
    "safety/set_max_iterations": (_handle_safety_set_max_iterations, "max_iterations"),
    "safety/set_wall_clock_timeout": (_handle_safety_set_wall_clock_timeout, "timeout_seconds"),
}

def _handle_jsonrpc_request(db: Database, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params")

    # Generate correlation ID for request tracing
    correlation_id = uuid.uuid4().hex[:12]

    # Log request entry (DEBUG level for normal requests, skip ping/initialize for noise reduction)
    if method not in ("ping", "initialize"):
        logger.debug(
            "RPC request [%s] method=%s req_id=%s",
            correlation_id,
            method,
            req_id,
        )

    try:
        # Notifications can omit id; ignore.
        if req_id is None:
            return None

        # Authentication methods (Polkit - native system dialog)
        if method == "auth/login":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            username = params.get("username")
            if not isinstance(username, str) or not username:
                raise RpcError(code=-32602, message="username is required")
            # Rate limit login attempts
            try:
                check_rate_limit("auth")
            except RateLimitExceeded as e:
                audit_log(
                    AuditEventType.RATE_LIMIT_EXCEEDED,
                    {"category": "auth", "username": username},
                )
                return _jsonrpc_result(req_id=req_id, result={"success": False, "error": str(e)})
            result = auth.login(username)
            # Audit the attempt
            if result.get("success"):
                audit_log(AuditEventType.AUTH_LOGIN_SUCCESS, {"username": username})
            else:
                audit_log(
                    AuditEventType.AUTH_LOGIN_FAILED,
                    {"username": username, "error": result.get("error", "unknown")},
                )
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "auth/logout":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            session_token = params.get("session_token")
            if not isinstance(session_token, str) or not session_token:
                raise RpcError(code=-32602, message="session_token is required")
            result = auth.logout(session_token)
            if result.get("success"):
                audit_log(AuditEventType.AUTH_LOGOUT, {"session_id": session_token[:16]})
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "auth/validate":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            session_token = params.get("session_token")
            if not isinstance(session_token, str) or not session_token:
                raise RpcError(code=-32602, message="session_token is required")
            return _jsonrpc_result(req_id=req_id, result=auth.validate_session(session_token))

        if method == "auth/refresh":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            session_token = params.get("session_token")
            if not isinstance(session_token, str) or not session_token:
                raise RpcError(code=-32602, message="session_token is required")
            refreshed = auth.refresh_session(session_token)
            return _jsonrpc_result(req_id=req_id, result={"success": refreshed})

        # Fast path: Check simple handler registries first
        if method in _SIMPLE_HANDLERS:
            return _jsonrpc_result(req_id=req_id, result=_SIMPLE_HANDLERS[method](db))

        if method in _STRING_PARAM_HANDLERS:
            handler, param_name = _STRING_PARAM_HANDLERS[method]
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            value = params.get(param_name)
            if not isinstance(value, str) or not value:
                raise RpcError(code=-32602, message=f"{param_name} is required")
            return _jsonrpc_result(req_id=req_id, result=handler(db, **{param_name: value}))

        if method in _NO_DB_STRING_HANDLERS:
            handler, param_name = _NO_DB_STRING_HANDLERS[method]
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            value = params.get(param_name)
            if not isinstance(value, str) or not value:
                raise RpcError(code=-32602, message=f"{param_name} is required")
            return _jsonrpc_result(req_id=req_id, result=handler(**{param_name: value}))

        if method in _INT_PARAM_HANDLERS:
            handler, param_name = _INT_PARAM_HANDLERS[method]
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            value = params.get(param_name)
            if not isinstance(value, int):
                raise RpcError(code=-32602, message=f"{param_name} must be an integer")
            return _jsonrpc_result(req_id=req_id, result=handler(db, **{param_name: value}))

        if method == "tools/call":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str) or not name:
                raise RpcError(code=-32602, message="name is required")
            if arguments is not None and not isinstance(arguments, dict):
                raise RpcError(code=-32602, message="arguments must be an object")
            result = _handle_tools_call(db, name=name, arguments=arguments)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "chat/respond":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = params.get("text")
            conversation_id = params.get("conversation_id")
            use_code_mode = params.get("use_code_mode", False)  # Default is conversational (CAIRN)
            agent_type = params.get("agent_type")  # 'cairn', 'riva', 'reos', or None
            extended_thinking = params.get("extended_thinking")  # None=auto, True=force, False=disable
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise RpcError(code=-32602, message="conversation_id must be a string or null")
            if agent_type is not None and not isinstance(agent_type, str):
                raise RpcError(code=-32602, message="agent_type must be a string or null")
            if extended_thinking is not None and not isinstance(extended_thinking, bool):
                raise RpcError(code=-32602, message="extended_thinking must be a boolean or null")
            result = _handle_chat_respond(
                db,
                text=text,
                conversation_id=conversation_id,
                use_code_mode=use_code_mode,
                agent_type=agent_type,
                extended_thinking=extended_thinking,
            )
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "approval/pending":
            conversation_id = None
            if isinstance(params, dict):
                conversation_id = params.get("conversation_id")
                if conversation_id is not None and not isinstance(conversation_id, str):
                    raise RpcError(code=-32602, message="conversation_id must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_pending(db, conversation_id=conversation_id),
            )

        if method == "approval/respond":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            approval_id = params.get("approval_id")
            action = params.get("action")
            edited_command = params.get("edited_command")
            if not isinstance(approval_id, str) or not approval_id:
                raise RpcError(code=-32602, message="approval_id is required")
            if not isinstance(action, str) or action not in ("approve", "reject"):
                raise RpcError(code=-32602, message="action must be 'approve' or 'reject'")
            if edited_command is not None and not isinstance(edited_command, str):
                raise RpcError(code=-32602, message="edited_command must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_respond(
                    db, approval_id=approval_id, action=action, edited_command=edited_command
                ),
            )

        if method == "approval/explain":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            approval_id = params.get("approval_id")
            if not isinstance(approval_id, str) or not approval_id:
                raise RpcError(code=-32602, message="approval_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_approval_explain(db, approval_id=approval_id),
            )

        # Plan and Execution methods (Phase 3)
        if method == "plan/preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            request = params.get("request")
            conversation_id = params.get("conversation_id")
            if not isinstance(request, str) or not request.strip():
                raise RpcError(code=-32602, message="request is required")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_plan_preview(db, request=request, conversation_id=conversation_id),
            )

        if method == "execution/status":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_status(db, execution_id=execution_id),
            )

        # Streaming execution methods (Phase 4)
        if method == "execution/kill":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_execution_kill(db, execution_id=execution_id),
            )

        # System Dashboard methods (Phase 5)

        if method == "personas/upsert":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona = params.get("persona")
            if not isinstance(persona, dict):
                raise RpcError(code=-32602, message="persona must be an object")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_upsert(db, persona=persona))

        # --- Ollama Settings ---



        if method == "ollama/test_connection":
            if not isinstance(params, dict):
                params = {}
            url = params.get("url")
            return _jsonrpc_result(req_id=req_id, result=_handle_ollama_test_connection(db, url=url))


        if method == "ollama/set_gpu":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            enabled = params.get("enabled")
            if not isinstance(enabled, bool):
                raise RpcError(code=-32602, message="enabled must be a boolean")
            return _jsonrpc_result(req_id=req_id, result=_handle_ollama_set_gpu(db, enabled=enabled))

        if method == "ollama/set_context":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            num_ctx = params.get("num_ctx")
            if not isinstance(num_ctx, int):
                raise RpcError(code=-32602, message="num_ctx must be an integer")
            return _jsonrpc_result(req_id=req_id, result=_handle_ollama_set_context(db, num_ctx=num_ctx))



        if method == "providers/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            provider = params.get("provider")
            if not isinstance(provider, str) or not provider:
                raise RpcError(code=-32602, message="provider is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_providers_set(db, provider=provider))



        if method == "play/me/read":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_me_read(db))

        if method == "play/me/write":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = params.get("text")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_me_write(db, text=text))


        if method == "play/acts/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            title = params.get("title")
            notes = params.get("notes")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            if notes is not None and not isinstance(notes, str):
                raise RpcError(code=-32602, message="notes must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_create(db, title=title, notes=notes))

        if method == "play/acts/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            notes = params.get("notes")
            color = params.get("color")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if title is not None and not isinstance(title, str):
                raise RpcError(code=-32602, message="title must be a string or null")
            if notes is not None and not isinstance(notes, str):
                raise RpcError(code=-32602, message="notes must be a string or null")
            if color is not None and not isinstance(color, str):
                raise RpcError(code=-32602, message="color must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_acts_update(db, act_id=act_id, title=title, notes=notes, color=color),
            )

        if method == "play/acts/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            # act_id can be null to clear the active act
            if act_id is not None and (not isinstance(act_id, str) or not act_id):
                raise RpcError(code=-32602, message="act_id must be a non-empty string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_set_active(db, act_id=act_id))

        if method == "play/acts/assign_repo":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            repo_path = params.get("repo_path")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(repo_path, str) or not repo_path.strip():
                raise RpcError(code=-32602, message="repo_path is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_acts_assign_repo(db, act_id=act_id, repo_path=repo_path),
            )

        if method == "play/scenes/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_scenes_list(db, act_id=act_id))

        if method == "play/scenes/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_create(
                    db,
                    act_id=act_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/scenes/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            title = params.get("title")
            intent = params.get("intent")
            status = params.get("status")
            time_horizon = params.get("time_horizon")
            notes = params.get("notes")
            for k, v in {
                "title": title,
                "intent": intent,
                "status": status,
                "time_horizon": time_horizon,
                "notes": notes,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    intent=intent,
                    status=status,
                    time_horizon=time_horizon,
                    notes=notes,
                ),
            )

        if method == "play/beats/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_list(db, act_id=act_id, scene_id=scene_id),
            )

        if method == "play/beats/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            stage = params.get("stage")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"stage": stage, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_create(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    stage=stage,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/beats/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            if not isinstance(beat_id, str) or not beat_id:
                raise RpcError(code=-32602, message="beat_id is required")
            title = params.get("title")
            stage = params.get("stage")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"title": title, "stage": stage, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_update(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    title=title,
                    stage=stage,
                    notes=notes,
                    link=link,
                ),
            )

        if method == "play/beats/move":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            beat_id = params.get("beat_id")
            source_act_id = params.get("source_act_id")
            source_scene_id = params.get("source_scene_id")
            target_act_id = params.get("target_act_id")
            target_scene_id = params.get("target_scene_id")
            if not isinstance(beat_id, str) or not beat_id:
                raise RpcError(code=-32602, message="beat_id is required")
            if not isinstance(source_act_id, str) or not source_act_id:
                raise RpcError(code=-32602, message="source_act_id is required")
            if not isinstance(source_scene_id, str) or not source_scene_id:
                raise RpcError(code=-32602, message="source_scene_id is required")
            if not isinstance(target_act_id, str) or not target_act_id:
                raise RpcError(code=-32602, message="target_act_id is required")
            if not isinstance(target_scene_id, str) or not target_scene_id:
                raise RpcError(code=-32602, message="target_scene_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_move(
                    db,
                    beat_id=beat_id,
                    source_act_id=source_act_id,
                    source_scene_id=source_scene_id,
                    target_act_id=target_act_id,
                    target_scene_id=target_scene_id,
                ),
            )

        if method == "play/kb/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_list(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id),
            )

        if method == "play/kb/read":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path", "kb.md")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id, "path": path}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_read(db, act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path),
            )

        if method == "play/kb/write_preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path")
            text = params.get("text")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_preview(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                ),
            )

        if method == "play/kb/write_apply":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            path = params.get("path")
            text = params.get("text")
            expected_sha256_current = params.get("expected_sha256_current")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(path, str) or not path:
                raise RpcError(code=-32602, message="path is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            for k, v in {"scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
                raise RpcError(code=-32602, message="expected_sha256_current is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_apply(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                    expected_sha256_current=expected_sha256_current,
                ),
            )

        if method == "play/attachments/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            for k, v in {"act_id": act_id, "scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_attachments_list(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                ),
            )

        if method == "play/attachments/add":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            file_path = params.get("file_path")
            file_name = params.get("file_name")
            if not isinstance(file_path, str) or not file_path:
                raise RpcError(code=-32602, message="file_path is required")
            for k, v in {"act_id": act_id, "scene_id": scene_id, "beat_id": beat_id, "file_name": file_name}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_attachments_add(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    file_path=file_path,
                    file_name=file_name,
                ),
            )

        if method == "play/attachments/remove":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            scene_id = params.get("scene_id")
            beat_id = params.get("beat_id")
            attachment_id = params.get("attachment_id")
            if not isinstance(attachment_id, str) or not attachment_id:
                raise RpcError(code=-32602, message="attachment_id is required")
            for k, v in {"act_id": act_id, "scene_id": scene_id, "beat_id": beat_id}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_attachments_remove(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    attachment_id=attachment_id,
                ),
            )

        # --- Context Meter & Knowledge Management ---

        if method == "context/stats":
            if not isinstance(params, dict):
                params = {}
            conversation_id = params.get("conversation_id")
            context_limit = params.get("context_limit")
            include_breakdown = params.get("include_breakdown", False)
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise RpcError(code=-32602, message="conversation_id must be a string")
            if context_limit is not None and not isinstance(context_limit, int):
                raise RpcError(code=-32602, message="context_limit must be an integer")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_context_stats(
                    db,
                    conversation_id=conversation_id,
                    context_limit=context_limit,
                    include_breakdown=bool(include_breakdown),
                ),
            )

        if method == "context/toggle_source":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            source_name = params.get("source_name")
            enabled = params.get("enabled")
            if not isinstance(source_name, str) or not source_name:
                raise RpcError(code=-32602, message="source_name is required")
            if not isinstance(enabled, bool):
                raise RpcError(code=-32602, message="enabled must be a boolean")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_context_toggle_source(db, source_name=source_name, enabled=enabled),
            )

        if method == "archive/save":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            act_id = params.get("act_id")
            title = params.get("title")
            generate_summary = params.get("generate_summary", False)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_save(
                    db,
                    conversation_id=conversation_id,
                    act_id=act_id,
                    title=title,
                    generate_summary=bool(generate_summary),
                ),
            )

        if method == "compact/preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_compact_preview(db, conversation_id=conversation_id, act_id=act_id),
            )

        if method == "compact/apply":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            entries = params.get("entries", [])
            if not isinstance(entries, list):
                raise RpcError(code=-32602, message="entries must be a list")
            act_id = params.get("act_id")
            archive_first = params.get("archive_first", True)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_compact_apply(
                    db,
                    conversation_id=conversation_id,
                    act_id=act_id,
                    entries=entries,
                    archive_first=bool(archive_first),
                ),
            )

        if method == "chat/clear":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_chat_clear(db, conversation_id=conversation_id),
            )

        # --- Code Mode Diff Preview ---


        if method == "code/plan/approve":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            plan_id = params.get("plan_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_code_plan_approve(
                    db,
                    conversation_id=conversation_id,
                    plan_id=plan_id,
                ),
            )

        if method == "code/exec/state":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            execution_id = params.get("execution_id")
            if not isinstance(execution_id, str) or not execution_id:
                raise RpcError(code=-32602, message="execution_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_code_exec_state(db, execution_id=execution_id),
            )

        # -------------------------------------------------------------------------
        # Code Mode Session Logs (for debugging)
        # -------------------------------------------------------------------------

        # -------------------------------------------------------------------------
        # Code Mode Planning (Pre-approval streaming)
        # -------------------------------------------------------------------------

        if method == "code/plan/start":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            prompt = params.get("prompt")
            conversation_id = params.get("conversation_id")
            act_id = params.get("act_id")
            if not isinstance(prompt, str) or not prompt:
                raise RpcError(code=-32602, message="prompt is required")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_code_plan_start(
                    db,
                    prompt=prompt,
                    conversation_id=conversation_id,
                    act_id=act_id,
                ),
            )

        if method == "code/plan/state":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            planning_id = params.get("planning_id")
            if not isinstance(planning_id, str) or not planning_id:
                raise RpcError(code=-32602, message="planning_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_code_plan_state(db, planning_id=planning_id),
            )

        if method == "code/plan/result":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            planning_id = params.get("planning_id")
            conversation_id = params.get("conversation_id")
            if not isinstance(planning_id, str) or not planning_id:
                raise RpcError(code=-32602, message="planning_id is required")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_code_plan_result(
                    db,
                    planning_id=planning_id,
                    conversation_id=conversation_id,
                ),
            )

        # -------------------------------------------------------------------------
        # CAIRN (Attention Minder)
        # -------------------------------------------------------------------------


        if method == "thunderbird/decline":
            return _jsonrpc_result(req_id=req_id, result=_handle_thunderbird_decline(db))


        if method == "cairn/attention":
            if not isinstance(params, dict):
                params = {}
            hours = params.get("hours", 168)  # 7 days default
            limit = params.get("limit", 10)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_cairn_attention(db, hours=hours, limit=limit),
            )

        # -------------------------------------------------------------------------
        # Safety & Security Settings
        # -------------------------------------------------------------------------


        if method == "safety/set_rate_limit":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            category = params.get("category")
            max_requests = params.get("max_requests")
            window_seconds = params.get("window_seconds")
            if not isinstance(category, str) or not category:
                raise RpcError(code=-32602, message="category is required")
            if not isinstance(max_requests, int):
                raise RpcError(code=-32602, message="max_requests must be an integer")
            if not isinstance(window_seconds, (int, float)):
                raise RpcError(code=-32602, message="window_seconds must be a number")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_safety_set_rate_limit(
                    db,
                    category=category,
                    max_requests=max_requests,
                    window_seconds=float(window_seconds),
                ),
            )




        raise RpcError(code=-32601, message=f"Method not found: {method}")

    except RpcError as exc:
        # Log RPC errors at warning level with correlation ID
        logger.warning(
            "RPC error [%s] method=%s code=%d: %s",
            correlation_id,
            method,
            exc.code,
            exc.message,
        )
        return _jsonrpc_error(req_id=req_id, code=exc.code, message=exc.message, data=exc.data)
    except Exception as exc:  # noqa: BLE001
        # Log internal errors at error level with full traceback
        logger.exception(
            "RPC internal error [%s] method=%s: %s",
            correlation_id,
            method,
            exc,
        )
        # Record for later analysis
        from .errors import record_error
        record_error(
            source="ui_rpc_server",
            operation=f"rpc:{method}",
            exc=exc,
            context={"correlation_id": correlation_id, "req_id": req_id},
            db=db,
        )
        return _jsonrpc_error(
            req_id=req_id,
            code=-32099,
            message="Internal error",
            data={"error": str(exc), "correlation_id": correlation_id},
        )


def _load_persisted_safety_settings(db: Database) -> None:
    """Load safety settings from database on startup.

    This ensures user's safety settings persist across restarts.
    """
    from . import linux_tools
    from . import security
    from .code_mode import executor as code_executor

    # Load sudo limit
    val = db.get_state(key="safety_sudo_limit")
    if val and isinstance(val, str):
        try:
            linux_tools._MAX_SUDO_ESCALATIONS = int(val)
            logger.debug("Loaded safety_sudo_limit: %s", val)
        except ValueError:
            pass

    # Load command length
    val = db.get_state(key="safety_command_length")
    if val and isinstance(val, str):
        try:
            security.MAX_COMMAND_LEN = int(val)
            logger.debug("Loaded safety_command_length: %s", val)
        except ValueError:
            pass

    # Load max iterations
    val = db.get_state(key="safety_max_iterations")
    if val and isinstance(val, str):
        try:
            code_executor.ExecutionState.max_iterations = int(val)
            logger.debug("Loaded safety_max_iterations: %s", val)
        except ValueError:
            pass

    # Load wall clock timeout
    val = db.get_state(key="safety_wall_clock_timeout")
    if val and isinstance(val, str):
        try:
            code_executor.DEFAULT_WALL_CLOCK_TIMEOUT_SECONDS = int(val)
            logger.debug("Loaded safety_wall_clock_timeout: %s", val)
        except ValueError:
            pass


def run_stdio_server() -> None:
    """Run the UI kernel server over stdio."""

    db = get_db()
    db.migrate()

    # Load persisted safety settings
    _load_persisted_safety_settings(db)

    while True:
        line = _readline()
        if line is None:
            return

        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(req, dict):
            continue

        resp = _handle_jsonrpc_request(db, req)
        if resp is not None:
            _write(resp)


def main() -> None:
    run_stdio_server()


if __name__ == "__main__":
    main()
