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
from .play_fs import list_acts as play_list_acts
from .play_fs import read_me_markdown as play_read_me_markdown
from .context_meter import calculate_context_stats, estimate_tokens
from .knowledge_store import KnowledgeStore

# Play RPC handlers (extracted to separate module)
from .rpc_handlers.play import (
    get_current_play_path,
    handle_play_me_read as _handle_play_me_read,
    handle_play_me_write as _handle_play_me_write,
    handle_play_acts_list as _handle_play_acts_list,
    handle_play_acts_set_active as _handle_play_acts_set_active,
    handle_play_acts_create as _handle_play_acts_create,
    handle_play_acts_update as _handle_play_acts_update,
    handle_play_acts_assign_repo as _handle_play_acts_assign_repo,
    handle_play_scenes_list as _handle_play_scenes_list,
    handle_play_scenes_list_all as _handle_play_scenes_list_all,
    handle_play_scenes_create as _handle_play_scenes_create,
    handle_play_scenes_update as _handle_play_scenes_update,
    handle_play_beats_list as _handle_play_beats_list,
    handle_play_beats_create as _handle_play_beats_create,
    handle_play_beats_update as _handle_play_beats_update,
    handle_play_beats_move as _handle_play_beats_move,
    handle_play_kb_list as _handle_play_kb_list,
    handle_play_kb_read as _handle_play_kb_read,
    handle_play_kb_write_preview as _handle_play_kb_write_preview,
    handle_play_kb_write_apply as _handle_play_kb_write_apply,
    handle_play_attachments_list as _handle_play_attachments_list,
    handle_play_attachments_add as _handle_play_attachments_add,
    handle_play_attachments_remove as _handle_play_attachments_remove,
    handle_play_pages_list as _handle_play_pages_list,
    handle_play_pages_tree as _handle_play_pages_tree,
    handle_play_pages_create as _handle_play_pages_create,
    handle_play_pages_update as _handle_play_pages_update,
    handle_play_pages_delete as _handle_play_pages_delete,
    handle_play_pages_move as _handle_play_pages_move,
    handle_play_pages_content_read as _handle_play_pages_content_read,
    handle_play_pages_content_write as _handle_play_pages_content_write,
)

# Provider RPC handlers (extracted to separate module)
from .rpc_handlers.providers import (
    detect_system_hardware as _detect_system_hardware,
    handle_ollama_status as _handle_ollama_status,
    handle_ollama_set_url as _handle_ollama_set_url,
    handle_ollama_set_model as _handle_ollama_set_model,
    handle_ollama_model_info as _handle_ollama_model_info,
    handle_ollama_set_gpu as _handle_ollama_set_gpu,
    handle_ollama_set_context as _handle_ollama_set_context,
    handle_ollama_pull_start as _handle_ollama_pull_start,
    handle_ollama_pull_status as _handle_ollama_pull_status,
    handle_ollama_test_connection as _handle_ollama_test_connection,
    handle_ollama_check_installed as _handle_ollama_check_installed,
    handle_providers_list as _handle_providers_list,
    handle_providers_set as _handle_providers_set,
    handle_anthropic_set_key as _handle_anthropic_set_key,
    handle_anthropic_delete_key as _handle_anthropic_delete_key,
    handle_anthropic_set_model as _handle_anthropic_set_model,
    handle_anthropic_status as _handle_anthropic_status,
)

# Archive RPC handlers (extracted to separate module)
from .rpc_handlers.archive import (
    handle_conversation_archive_preview as _handle_conversation_archive_preview,
    handle_conversation_archive_confirm as _handle_conversation_archive_confirm,
    handle_conversation_archive as _handle_conversation_archive,
    handle_conversation_delete as _handle_conversation_delete,
    handle_archive_list as _handle_archive_list,
    handle_archive_get as _handle_archive_get,
    handle_archive_assess as _handle_archive_assess,
    handle_archive_feedback as _handle_archive_feedback,
    handle_archive_learning_stats as _handle_archive_learning_stats,
)

# Safety RPC handlers (extracted to separate module)
from .rpc_handlers.safety import (
    handle_safety_settings as _handle_safety_settings,
    handle_safety_set_rate_limit as _handle_safety_set_rate_limit,
    handle_safety_set_sudo_limit as _handle_safety_set_sudo_limit,
    handle_safety_set_command_length as _handle_safety_set_command_length,
    handle_safety_set_max_iterations as _handle_safety_set_max_iterations,
    handle_safety_set_wall_clock_timeout as _handle_safety_set_wall_clock_timeout,
)

# Persona RPC handlers (extracted to separate module)
from .rpc_handlers.personas import (
    handle_personas_list as _handle_personas_list,
    handle_persona_get as _handle_persona_get,
    handle_persona_upsert as _handle_persona_upsert,
    handle_persona_set_active as _handle_persona_set_active,
)

# Context RPC handlers (extracted to separate module)
from .rpc_handlers.context import (
    handle_context_stats as _handle_context_stats,
    handle_context_toggle_source as _handle_context_toggle_source,
)

# System/Thunderbird/Autostart RPC handlers (extracted to separate module)
from .rpc_handlers.system import (
    handle_system_live_state as _handle_system_live_state,
    handle_cairn_thunderbird_status as _handle_cairn_thunderbird_status,
    handle_thunderbird_check as _handle_thunderbird_check,
    handle_thunderbird_configure as _handle_thunderbird_configure,
    handle_thunderbird_decline as _handle_thunderbird_decline,
    handle_thunderbird_reset as _handle_thunderbird_reset,
    handle_autostart_get as _handle_autostart_get,
    handle_autostart_set as _handle_autostart_set,
    handle_cairn_attention as _handle_cairn_attention,
)

_JSON = dict[str, Any]


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
# Consciousness Streaming - Real-time visibility into CAIRN's thinking
# -------------------------------------------------------------------------


def _handle_consciousness_start(_db: Database) -> dict[str, Any]:
    """Start a consciousness streaming session.

    Clears previous events and activates event collection.
    Called when user sends a message.
    """
    from .cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    observer.start_session()
    return {"status": "started"}


# -------------------------------------------------------------------------
# Async CAIRN Chat - Background processing for real-time consciousness streaming
# -------------------------------------------------------------------------

import uuid as _uuid
from dataclasses import dataclass as _dataclass
from dataclasses import field as _field

@_dataclass
class _CairnChatContext:
    """Context for an async CAIRN chat request."""
    chat_id: str
    text: str
    conversation_id: str | None
    extended_thinking: bool
    is_complete: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None
    thread: threading.Thread | None = None

_cairn_chat_lock = threading.Lock()
_active_cairn_chats: dict[str, _CairnChatContext] = {}


def _handle_cairn_chat_async(
    db: Database,
    *,
    text: str,
    conversation_id: str | None = None,
    extended_thinking: bool = False,
) -> dict[str, Any]:
    """Start CAIRN chat processing in background thread.

    This allows the RPC server to handle consciousness/poll requests
    while chat is processing, enabling real-time event streaming.

    Returns immediately with a chat_id that can be used to poll for status.
    """
    from .cairn.consciousness_stream import ConsciousnessObserver

    chat_id = _uuid.uuid4().hex[:12]

    # Start consciousness session
    observer = ConsciousnessObserver.get_instance()
    observer.start_session()
    # Debug logging to file
    with open("/tmp/consciousness_debug.log", "a") as f:
        f.write(f"[ASYNC CHAT] Started consciousness session for chat_id={chat_id}\n")

    context = _CairnChatContext(
        chat_id=chat_id,
        text=text,
        conversation_id=conversation_id,
        extended_thinking=extended_thinking,
    )

    def run_chat() -> None:
        """Run the chat in background thread."""
        try:
            result = _handle_chat_respond(
                db,
                text=text,
                conversation_id=conversation_id,
                agent_type="cairn",  # Use CAIRN's IntentEngine for consciousness events
                extended_thinking=extended_thinking,
            )
            context.result = result
            context.is_complete = True
        except Exception as e:
            context.error = str(e)
            context.is_complete = True
        finally:
            # End consciousness session
            observer.end_session()

    # Start background thread
    thread = threading.Thread(target=run_chat, daemon=True)
    context.thread = thread

    # Track the chat
    with _cairn_chat_lock:
        _active_cairn_chats[chat_id] = context

    thread.start()

    return {
        "chat_id": chat_id,
        "status": "started",
    }


def _handle_cairn_chat_status(
    _db: Database,
    *,
    chat_id: str,
) -> dict[str, Any]:
    """Get the status of an async CAIRN chat request.

    Returns the result when complete, or status "processing" if still running.
    """
    with _cairn_chat_lock:
        context = _active_cairn_chats.get(chat_id)

    if not context:
        return {"error": f"Chat {chat_id} not found", "status": "not_found"}

    if not context.is_complete:
        return {"chat_id": chat_id, "status": "processing"}

    if context.error:
        return {"chat_id": chat_id, "status": "error", "error": context.error}

    # Clean up completed chat
    with _cairn_chat_lock:
        _active_cairn_chats.pop(chat_id, None)

    return {
        "chat_id": chat_id,
        "status": "complete",
        "result": context.result,
    }


def _handle_consciousness_poll(_db: Database, *, since_index: int = 0) -> dict[str, Any]:
    """Poll for new consciousness events.

    Args:
        since_index: Return events starting from this index

    Returns:
        Dict with events list and next_index for pagination
    """
    from .cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    events = observer.poll(since_index)

    # Debug logging to file
    with open("/tmp/consciousness_debug.log", "a") as f:
        f.write(f"[POLL] since_index={since_index}, active={observer.is_active()}, events={len(events)}\n")

    return {
        "events": [
            {
                "type": e.event_type.name,
                "timestamp": e.timestamp.isoformat(),
                "title": e.title,
                "content": e.content,
                "metadata": e.metadata,
            }
            for e in events
        ],
        "next_index": since_index + len(events),
    }


def _handle_consciousness_snapshot(_db: Database) -> dict[str, Any]:
    """Get all events from the current session.

    Returns all events without pagination.
    """
    from .cairn.consciousness_stream import ConsciousnessObserver

    observer = ConsciousnessObserver.get_instance()
    events = observer.get_all()

    return {
        "events": [
            {
                "type": e.event_type.name,
                "timestamp": e.timestamp.isoformat(),
                "title": e.title,
                "content": e.content,
                "metadata": e.metadata,
            }
            for e in events
        ],
    }


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
    "autostart/get": _handle_autostart_get,
    "consciousness/start": _handle_consciousness_start,
    "consciousness/snapshot": _handle_consciousness_snapshot,
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
    "consciousness/poll": (_handle_consciousness_poll, "since_index"),
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

        # Async CAIRN chat for real-time consciousness streaming
        if method == "cairn/chat_async":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            text = params.get("text")
            conversation_id = params.get("conversation_id")
            extended_thinking = params.get("extended_thinking", False)
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
            result = _handle_cairn_chat_async(
                db,
                text=text,
                conversation_id=conversation_id,
                extended_thinking=extended_thinking,
            )
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "cairn/chat_status":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            chat_id = params.get("chat_id")
            if not isinstance(chat_id, str) or not chat_id:
                raise RpcError(code=-32602, message="chat_id is required")
            result = _handle_cairn_chat_status(db, chat_id=chat_id)
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

        if method == "autostart/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            enabled = params.get("enabled")
            if not isinstance(enabled, bool):
                raise RpcError(code=-32602, message="enabled must be a boolean")
            return _jsonrpc_result(req_id=req_id, result=_handle_autostart_set(db, enabled=enabled))

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

        if method == "play/scenes/list_all":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_scenes_list_all(db))

        if method == "play/scenes/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            stage = params.get("stage")
            notes = params.get("notes")
            link = params.get("link")
            calendar_event_id = params.get("calendar_event_id")
            recurrence_rule = params.get("recurrence_rule")
            thunderbird_event_id = params.get("thunderbird_event_id")
            for k, v in {
                "stage": stage,
                "notes": notes,
                "link": link,
                "calendar_event_id": calendar_event_id,
                "recurrence_rule": recurrence_rule,
                "thunderbird_event_id": thunderbird_event_id,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_scenes_create(
                    db,
                    act_id=act_id,
                    title=title,
                    stage=stage,
                    notes=notes,
                    link=link,
                    calendar_event_id=calendar_event_id,
                    recurrence_rule=recurrence_rule,
                    thunderbird_event_id=thunderbird_event_id,
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
            stage = params.get("stage")
            notes = params.get("notes")
            link = params.get("link")
            calendar_event_id = params.get("calendar_event_id")
            recurrence_rule = params.get("recurrence_rule")
            thunderbird_event_id = params.get("thunderbird_event_id")
            for k, v in {
                "title": title,
                "stage": stage,
                "notes": notes,
                "link": link,
                "calendar_event_id": calendar_event_id,
                "recurrence_rule": recurrence_rule,
                "thunderbird_event_id": thunderbird_event_id,
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
                    stage=stage,
                    notes=notes,
                    link=link,
                    calendar_event_id=calendar_event_id,
                    recurrence_rule=recurrence_rule,
                    thunderbird_event_id=thunderbird_event_id,
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

        # --- Page Endpoints (Nested Knowledgebase) ---

        if method == "play/pages/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            parent_page_id = params.get("parent_page_id")
            if parent_page_id is not None and not isinstance(parent_page_id, str):
                raise RpcError(code=-32602, message="parent_page_id must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_list(db, act_id=act_id, parent_page_id=parent_page_id),
            )

        if method == "play/pages/tree":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_tree(db, act_id=act_id),
            )

        if method == "play/pages/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            title = params.get("title")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(title, str) or not title.strip():
                raise RpcError(code=-32602, message="title is required")
            parent_page_id = params.get("parent_page_id")
            icon = params.get("icon")
            for k, v in {"parent_page_id": parent_page_id, "icon": icon}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_create(
                    db, act_id=act_id, title=title.strip(),
                    parent_page_id=parent_page_id, icon=icon
                ),
            )

        if method == "play/pages/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            page_id = params.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            title = params.get("title")
            icon = params.get("icon")
            for k, v in {"title": title, "icon": icon}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_update(db, page_id=page_id, title=title, icon=icon),
            )

        if method == "play/pages/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            page_id = params.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_delete(db, page_id=page_id),
            )

        if method == "play/pages/move":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            page_id = params.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            new_parent_id = params.get("new_parent_id")
            new_position = params.get("new_position")
            if new_parent_id is not None and not isinstance(new_parent_id, str):
                raise RpcError(code=-32602, message="new_parent_id must be a string or null")
            if new_position is not None and not isinstance(new_position, int):
                raise RpcError(code=-32602, message="new_position must be an integer or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_move(
                    db, page_id=page_id, new_parent_id=new_parent_id, new_position=new_position
                ),
            )

        if method == "play/pages/content/read":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            page_id = params.get("page_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_content_read(db, act_id=act_id, page_id=page_id),
            )

        if method == "play/pages/content/write":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            page_id = params.get("page_id")
            text = params.get("text")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            if not isinstance(text, str):
                raise RpcError(code=-32602, message="text is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_pages_content_write(db, act_id=act_id, page_id=page_id, text=text),
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

        # --- Conversation Archive (LLM-driven memory system) ---

        if method == "conversation/archive/preview":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            auto_link = params.get("auto_link", True)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_conversation_archive_preview(
                    db,
                    conversation_id=conversation_id,
                    auto_link=bool(auto_link),
                ),
            )

        if method == "conversation/archive/confirm":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            title = params.get("title")
            summary = params.get("summary")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            if not isinstance(title, str) or not title:
                raise RpcError(code=-32602, message="title is required")
            if not isinstance(summary, str):
                raise RpcError(code=-32602, message="summary is required")
            act_id = params.get("act_id")
            knowledge_entries = params.get("knowledge_entries", [])
            additional_notes = params.get("additional_notes", "")
            rating = params.get("rating")
            if not isinstance(knowledge_entries, list):
                raise RpcError(code=-32602, message="knowledge_entries must be a list")
            if not isinstance(additional_notes, str):
                additional_notes = ""
            if rating is not None and not isinstance(rating, int):
                raise RpcError(code=-32602, message="rating must be an integer or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_conversation_archive_confirm(
                    db,
                    conversation_id=conversation_id,
                    title=title,
                    summary=summary,
                    act_id=act_id,
                    knowledge_entries=knowledge_entries,
                    additional_notes=additional_notes,
                    rating=rating,
                ),
            )

        if method == "conversation/archive":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            act_id = params.get("act_id")
            auto_link = params.get("auto_link", True)
            extract_knowledge = params.get("extract_knowledge", True)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_conversation_archive(
                    db,
                    conversation_id=conversation_id,
                    act_id=act_id,
                    auto_link=bool(auto_link),
                    extract_knowledge=bool(extract_knowledge),
                ),
            )

        if method == "conversation/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            archive_first = params.get("archive_first", False)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_conversation_delete(
                    db,
                    conversation_id=conversation_id,
                    archive_first=bool(archive_first),
                ),
            )

        if method == "archive/list":
            if not isinstance(params, dict):
                params = {}
            act_id = params.get("act_id")
            limit = params.get("limit", 50)
            if act_id is not None and not isinstance(act_id, str):
                raise RpcError(code=-32602, message="act_id must be a string or null")
            if not isinstance(limit, int):
                limit = 50
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_list(db, act_id=act_id, limit=limit),
            )

        if method == "archive/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            archive_id = params.get("archive_id")
            if not isinstance(archive_id, str) or not archive_id:
                raise RpcError(code=-32602, message="archive_id is required")
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_get(db, archive_id=archive_id, act_id=act_id),
            )

        if method == "archive/assess":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            archive_id = params.get("archive_id")
            if not isinstance(archive_id, str) or not archive_id:
                raise RpcError(code=-32602, message="archive_id is required")
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_assess(db, archive_id=archive_id, act_id=act_id),
            )

        if method == "archive/feedback":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            archive_id = params.get("archive_id")
            rating = params.get("rating")
            feedback = params.get("feedback")
            if not isinstance(archive_id, str) or not archive_id:
                raise RpcError(code=-32602, message="archive_id is required")
            if not isinstance(rating, int) or rating < 1 or rating > 5:
                raise RpcError(code=-32602, message="rating must be an integer 1-5")
            if feedback is not None and not isinstance(feedback, str):
                raise RpcError(code=-32602, message="feedback must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_feedback(
                    db, archive_id=archive_id, rating=rating, feedback=feedback
                ),
            )

        if method == "archive/learning_stats":
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_archive_learning_stats(db),
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
