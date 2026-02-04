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
    handle_system_open_terminal as _handle_system_open_terminal,
    handle_cairn_thunderbird_status as _handle_cairn_thunderbird_status,
    handle_thunderbird_check as _handle_thunderbird_check,
    handle_thunderbird_configure as _handle_thunderbird_configure,
    handle_thunderbird_decline as _handle_thunderbird_decline,
    handle_thunderbird_reset as _handle_thunderbird_reset,
    handle_autostart_get as _handle_autostart_get,
    handle_autostart_set as _handle_autostart_set,
    handle_cairn_attention as _handle_cairn_attention,
)

# Approval RPC handlers (extracted to separate module)
from .rpc_handlers.approvals import (
    handle_approval_pending as _handle_approval_pending,
    handle_approval_respond as _handle_approval_respond,
    handle_approval_explain as _handle_approval_explain,
)

# Chat RPC handlers (extracted to separate module)
from .rpc_handlers.chat import (
    handle_chat_respond as _handle_chat_respond,
    handle_chat_clear as _handle_chat_clear,
)

# Consciousness/CAIRN chat RPC handlers (extracted to separate module)
from .rpc_handlers.consciousness import (
    handle_consciousness_start as _handle_consciousness_start,
    handle_consciousness_poll as _handle_consciousness_poll,
    handle_consciousness_snapshot as _handle_consciousness_snapshot,
    handle_consciousness_persist as _handle_consciousness_persist,
    handle_cairn_chat_async as _handle_cairn_chat_async,
    handle_cairn_chat_status as _handle_cairn_chat_status,
    handle_handoff_validate_all as _handle_handoff_validate_all,
)

# Reasoning chain RPC handlers (RLHF feedback system)
from .rpc_handlers.reasoning import (
    handle_reasoning_feedback as _handle_reasoning_feedback,
    handle_reasoning_chain_get as _handle_reasoning_chain_get,
    handle_reasoning_chains_list as _handle_reasoning_chains_list,
)

# Execution RPC handlers (extracted to separate module)
from .rpc_handlers.execution import (
    handle_plan_preview as _handle_plan_preview,
    handle_execution_status as _handle_execution_status,
    handle_execution_kill as _handle_execution_kill,
    handle_code_diff_apply as _handle_code_diff_apply,
    handle_code_diff_reject as _handle_code_diff_reject,
    handle_code_plan_approve as _handle_code_plan_approve,
    handle_code_exec_state as _handle_code_exec_state,
    handle_code_plan_start as _handle_code_plan_start,
    handle_code_plan_state as _handle_code_plan_state,
    handle_code_plan_result as _handle_code_plan_result,
)

# Blocks RPC handlers (extracted to separate module)
from .rpc_handlers.blocks import (
    handle_blocks_create as _handle_blocks_create,
    handle_blocks_get as _handle_blocks_get,
    handle_blocks_list as _handle_blocks_list,
    handle_blocks_update as _handle_blocks_update,
    handle_blocks_delete as _handle_blocks_delete,
    handle_blocks_move as _handle_blocks_move,
    handle_blocks_reorder as _handle_blocks_reorder,
    handle_blocks_ancestors as _handle_blocks_ancestors,
    handle_blocks_descendants as _handle_blocks_descendants,
    handle_blocks_page_tree as _handle_blocks_page_tree,
    handle_blocks_page_markdown as _handle_blocks_page_markdown,
    handle_blocks_import_markdown as _handle_blocks_import_markdown,
    handle_blocks_create_scene as _handle_blocks_create_scene,
    handle_blocks_validate_scene as _handle_blocks_validate_scene,
    handle_blocks_rich_text_get as _handle_blocks_rich_text_get,
    handle_blocks_rich_text_set as _handle_blocks_rich_text_set,
    handle_blocks_property_get as _handle_blocks_property_get,
    handle_blocks_property_set as _handle_blocks_property_set,
    handle_blocks_property_delete as _handle_blocks_property_delete,
    handle_blocks_search as _handle_blocks_search,
    handle_blocks_unchecked_todos as _handle_blocks_unchecked_todos,
)

# Memory RPC handlers (hybrid vector-graph memory system)
from .rpc_handlers.memory import (
    handle_memory_relationships_create as _handle_memory_relationships_create,
    handle_memory_relationships_list as _handle_memory_relationships_list,
    handle_memory_relationships_update as _handle_memory_relationships_update,
    handle_memory_relationships_delete as _handle_memory_relationships_delete,
    handle_memory_search as _handle_memory_search,
    handle_memory_related as _handle_memory_related,
    handle_memory_path as _handle_memory_path,
    handle_memory_index_block as _handle_memory_index_block,
    handle_memory_index_batch as _handle_memory_index_batch,
    handle_memory_remove_index as _handle_memory_remove_index,
    handle_memory_extract_relationships as _handle_memory_extract_relationships,
    handle_memory_learn_from_feedback as _handle_memory_learn_from_feedback,
    handle_memory_auto_link as _handle_memory_auto_link,
    handle_memory_stats as _handle_memory_stats,
)

# Documents RPC handlers (knowledge base document management)
from .rpc_handlers.documents import (
    handle_documents_insert as _handle_documents_insert,
    handle_documents_list as _handle_documents_list,
    handle_documents_get as _handle_documents_get,
    handle_documents_delete as _handle_documents_delete,
    handle_documents_get_chunks as _handle_documents_get_chunks,
)

from .rpc_handlers import RpcError

_JSON = dict[str, Any]


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


# -------------------------------------------------------------------------
# Conversation management handlers
# -------------------------------------------------------------------------








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

        # Debug logging from frontend
        if method == "debug/log":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            msg = params.get("msg", "")
            import sys
            print(f"[JS] {msg}", file=sys.stderr, flush=True)
            return _jsonrpc_result(req_id=req_id, result={"ok": True})

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
            _debug_source = params.get("_debug_source")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_kb_write_preview(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    beat_id=beat_id,
                    path=path,
                    text=text,
                    _debug_source=_debug_source,
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
            _debug_source = params.get("_debug_source")
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
                    _debug_source=_debug_source,
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

        # --- Blocks (Notion-style block editor) ---

        if method == "blocks/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_type = params.get("type")
            act_id = params.get("act_id")
            if not isinstance(block_type, str) or not block_type:
                raise RpcError(code=-32602, message="type is required")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_create(
                    db,
                    type=block_type,
                    act_id=act_id,
                    parent_id=params.get("parent_id"),
                    page_id=params.get("page_id"),
                    scene_id=params.get("scene_id"),
                    position=params.get("position"),
                    rich_text=params.get("rich_text"),
                    properties=params.get("properties"),
                ),
            )

        if method == "blocks/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_get(
                    db,
                    block_id=block_id,
                    include_children=bool(params.get("include_children", False)),
                ),
            )

        if method == "blocks/list":
            if not isinstance(params, dict):
                params = {}
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_list(
                    db,
                    page_id=params.get("page_id"),
                    parent_id=params.get("parent_id"),
                    act_id=params.get("act_id"),
                ),
            )

        if method == "blocks/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_update(
                    db,
                    block_id=block_id,
                    rich_text=params.get("rich_text"),
                    properties=params.get("properties"),
                    position=params.get("position"),
                ),
            )

        if method == "blocks/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_delete(
                    db,
                    block_id=block_id,
                    recursive=params.get("recursive", True),
                ),
            )

        if method == "blocks/move":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_move(
                    db,
                    block_id=block_id,
                    new_parent_id=params.get("new_parent_id"),
                    new_page_id=params.get("new_page_id"),
                    new_position=params.get("new_position"),
                ),
            )

        if method == "blocks/reorder":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_ids = params.get("block_ids")
            if not isinstance(block_ids, list):
                raise RpcError(code=-32602, message="block_ids must be a list")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_reorder(db, block_ids=block_ids),
            )

        if method == "blocks/ancestors":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_ancestors(db, block_id=block_id),
            )

        if method == "blocks/descendants":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_descendants(db, block_id=block_id),
            )

        if method == "blocks/page/tree":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            page_id = params.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_page_tree(db, page_id=page_id),
            )

        if method == "blocks/page/markdown":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            page_id = params.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise RpcError(code=-32602, message="page_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_page_markdown(db, page_id=page_id),
            )

        if method == "blocks/import/markdown":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            markdown = params.get("markdown")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(markdown, str):
                raise RpcError(code=-32602, message="markdown is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_import_markdown(
                    db,
                    act_id=act_id,
                    page_id=params.get("page_id"),
                    markdown=markdown,
                ),
            )

        if method == "blocks/scene/create":
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
                result=_handle_blocks_create_scene(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    parent_id=params.get("parent_id"),
                    page_id=params.get("page_id"),
                    position=params.get("position"),
                ),
            )

        if method == "blocks/scene/validate":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            scene_id = params.get("scene_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(scene_id, str) or not scene_id:
                raise RpcError(code=-32602, message="scene_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_validate_scene(db, block_id=block_id, scene_id=scene_id),
            )

        if method == "blocks/rich_text/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_rich_text_get(db, block_id=block_id),
            )

        if method == "blocks/rich_text/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            spans = params.get("spans")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(spans, list):
                raise RpcError(code=-32602, message="spans must be a list")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_rich_text_set(db, block_id=block_id, spans=spans),
            )

        if method == "blocks/property/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            key = params.get("key")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_property_get(db, block_id=block_id, key=key),
            )

        if method == "blocks/property/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            key = params.get("key")
            value = params.get("value")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_property_set(db, block_id=block_id, key=key, value=value),
            )

        if method == "blocks/property/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            key = params.get("key")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_property_delete(db, block_id=block_id, key=key),
            )

        if method == "blocks/search":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            query = params.get("query")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if not isinstance(query, str) or not query:
                raise RpcError(code=-32602, message="query is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_search(db, act_id=act_id, query=query),
            )

        if method == "blocks/unchecked_todos":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_blocks_unchecked_todos(db, act_id=act_id),
            )

        # --- Memory (Hybrid Vector-Graph Memory System) ---

        if method == "memory/relationships/create":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            source_id = params.get("source_id")
            target_id = params.get("target_id")
            rel_type = params.get("rel_type")
            if not isinstance(source_id, str) or not source_id:
                raise RpcError(code=-32602, message="source_id is required")
            if not isinstance(target_id, str) or not target_id:
                raise RpcError(code=-32602, message="target_id is required")
            if not isinstance(rel_type, str) or not rel_type:
                raise RpcError(code=-32602, message="rel_type is required")
            confidence = params.get("confidence", 1.0)
            weight = params.get("weight", 1.0)
            source = params.get("source", "user")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_relationships_create(
                    db,
                    source_id=source_id,
                    target_id=target_id,
                    rel_type=rel_type,
                    confidence=confidence,
                    weight=weight,
                    source=source,
                ),
            )

        if method == "memory/relationships/list":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            direction = params.get("direction", "both")
            rel_types = params.get("rel_types")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_relationships_list(
                    db,
                    block_id=block_id,
                    direction=direction,
                    rel_types=rel_types,
                ),
            )

        if method == "memory/relationships/update":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            relationship_id = params.get("relationship_id")
            if not isinstance(relationship_id, str) or not relationship_id:
                raise RpcError(code=-32602, message="relationship_id is required")
            confidence = params.get("confidence")
            weight = params.get("weight")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_relationships_update(
                    db,
                    relationship_id=relationship_id,
                    confidence=confidence,
                    weight=weight,
                ),
            )

        if method == "memory/relationships/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            relationship_id = params.get("relationship_id")
            if not isinstance(relationship_id, str) or not relationship_id:
                raise RpcError(code=-32602, message="relationship_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_relationships_delete(
                    db,
                    relationship_id=relationship_id,
                ),
            )

        if method == "memory/search":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            query = params.get("query")
            if not isinstance(query, str) or not query.strip():
                raise RpcError(code=-32602, message="query is required")
            act_id = params.get("act_id")
            max_results = params.get("max_results", 20)
            include_graph = params.get("include_graph", True)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_search(
                    db,
                    query=query,
                    act_id=act_id,
                    max_results=max_results,
                    include_graph=include_graph,
                ),
            )

        if method == "memory/related":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            depth = params.get("depth", 2)
            rel_types = params.get("rel_types")
            direction = params.get("direction", "both")
            max_nodes = params.get("max_nodes", 50)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_related(
                    db,
                    block_id=block_id,
                    depth=depth,
                    rel_types=rel_types,
                    direction=direction,
                    max_nodes=max_nodes,
                ),
            )

        if method == "memory/path":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            start_id = params.get("start_id")
            end_id = params.get("end_id")
            if not isinstance(start_id, str) or not start_id:
                raise RpcError(code=-32602, message="start_id is required")
            if not isinstance(end_id, str) or not end_id:
                raise RpcError(code=-32602, message="end_id is required")
            max_depth = params.get("max_depth", 5)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_path(
                    db,
                    start_id=start_id,
                    end_id=end_id,
                    max_depth=max_depth,
                ),
            )

        if method == "memory/index/block":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_index_block(db, block_id=block_id),
            )

        if method == "memory/index/batch":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_ids = params.get("block_ids")
            if not isinstance(block_ids, list):
                raise RpcError(code=-32602, message="block_ids must be a list")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_index_batch(db, block_ids=block_ids),
            )

        if method == "memory/index/remove":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_remove_index(db, block_id=block_id),
            )

        if method == "memory/extract":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            block_id = params.get("block_id")
            content = params.get("content")
            if not isinstance(block_id, str) or not block_id:
                raise RpcError(code=-32602, message="block_id is required")
            if not isinstance(content, str):
                raise RpcError(code=-32602, message="content is required")
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_extract_relationships(
                    db,
                    block_id=block_id,
                    content=content,
                    act_id=act_id,
                ),
            )

        if method == "memory/learn":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            chain_block_id = params.get("chain_block_id")
            rating = params.get("rating")
            if not isinstance(chain_block_id, str) or not chain_block_id:
                raise RpcError(code=-32602, message="chain_block_id is required")
            if not isinstance(rating, int) or rating < 1 or rating > 5:
                raise RpcError(code=-32602, message="rating must be an integer 1-5")
            corrected_block_id = params.get("corrected_block_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_learn_from_feedback(
                    db,
                    chain_block_id=chain_block_id,
                    rating=rating,
                    corrected_block_id=corrected_block_id,
                ),
            )

        if method == "memory/auto_link":
            if not isinstance(params, dict):
                params = {}
            act_id = params.get("act_id")
            threshold = params.get("threshold", 0.8)
            max_links = params.get("max_links", 3)
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_auto_link(
                    db,
                    act_id=act_id,
                    threshold=threshold,
                    max_links=max_links,
                ),
            )

        if method == "memory/stats":
            if not isinstance(params, dict):
                params = {}
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_memory_stats(db, act_id=act_id),
            )

        # --- Documents (Knowledge Base Document Management) ---

        if method == "documents/insert":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            file_path = params.get("file_path")
            if not isinstance(file_path, str) or not file_path:
                raise RpcError(code=-32602, message="file_path is required")
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_documents_insert(db, file_path=file_path, act_id=act_id),
            )

        if method == "documents/list":
            if not isinstance(params, dict):
                params = {}
            act_id = params.get("act_id")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_documents_list(db, act_id=act_id),
            )

        if method == "documents/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            document_id = params.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                raise RpcError(code=-32602, message="document_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_documents_get(db, document_id=document_id),
            )

        if method == "documents/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            document_id = params.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                raise RpcError(code=-32602, message="document_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_documents_delete(db, document_id=document_id),
            )

        if method == "documents/chunks":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            document_id = params.get("document_id")
            if not isinstance(document_id, str) or not document_id:
                raise RpcError(code=-32602, message="document_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_documents_get_chunks(db, document_id=document_id),
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

        # -------------------------------------------------------------------------
        # Reasoning Chain & RLHF Feedback (consciousness persistence)
        # -------------------------------------------------------------------------

        if method == "consciousness/persist":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            conversation_id = params.get("conversation_id")
            user_message_id = params.get("user_message_id")
            response_message_id = params.get("response_message_id")
            act_id = params.get("act_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise RpcError(code=-32602, message="conversation_id is required")
            if not isinstance(user_message_id, str) or not user_message_id:
                raise RpcError(code=-32602, message="user_message_id is required")
            if not isinstance(response_message_id, str) or not response_message_id:
                raise RpcError(code=-32602, message="response_message_id is required")
            if act_id is not None and not isinstance(act_id, str):
                raise RpcError(code=-32602, message="act_id must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_consciousness_persist(
                    db,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    response_message_id=response_message_id,
                    act_id=act_id,
                ),
            )

        if method == "reasoning/feedback":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            chain_block_id = params.get("chain_block_id")
            rating = params.get("rating")
            comment = params.get("comment")
            if not isinstance(chain_block_id, str) or not chain_block_id:
                raise RpcError(code=-32602, message="chain_block_id is required")
            if not isinstance(rating, int):
                raise RpcError(code=-32602, message="rating must be an integer (1 or 5)")
            if comment is not None and not isinstance(comment, str):
                raise RpcError(code=-32602, message="comment must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_reasoning_feedback(
                    db,
                    chain_block_id=chain_block_id,
                    rating=rating,
                    comment=comment,
                ),
            )

        if method == "reasoning/chain":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            chain_block_id = params.get("chain_block_id")
            if not isinstance(chain_block_id, str) or not chain_block_id:
                raise RpcError(code=-32602, message="chain_block_id is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_reasoning_chain_get(db, chain_block_id=chain_block_id),
            )

        if method == "reasoning/list":
            if not isinstance(params, dict):
                params = {}
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_reasoning_chains_list(
                    db,
                    act_id=params.get("act_id"),
                    feedback_status=params.get("feedback_status"),
                    limit=params.get("limit", 50),
                    offset=params.get("offset", 0),
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
    except (ValueError, TypeError) as exc:
        # Parameter validation errors from handlers
        logger.warning(
            "RPC parameter error [%s] method=%s: %s",
            correlation_id,
            method,
            exc,
        )
        return _jsonrpc_error(
            req_id=req_id,
            code=-32602,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        # Convert domain errors to structured RPC errors
        from .errors import TalkingRockError, get_error_code, record_error
        if isinstance(exc, TalkingRockError):
            logger.warning(
                "RPC domain error [%s] method=%s: %s",
                correlation_id,
                method,
                exc.message,
            )
            return _jsonrpc_error(
                req_id=req_id,
                code=get_error_code(exc),
                message=exc.message,
                data=exc.to_dict(),
            )
        # Unexpected internal errors — log with full traceback
        logger.exception(
            "RPC internal error [%s] method=%s: %s",
            correlation_id,
            method,
            exc,
        )
        record_error(
            source="ui_rpc_server",
            operation=f"rpc:{method}",
            exc=exc,
            context={"correlation_id": correlation_id, "req_id": req_id},
            db=db,
        )
        return _jsonrpc_error(
            req_id=req_id,
            code=-32603,
            message=f"Internal error in {method}",
            data={"error_type": type(exc).__name__, "correlation_id": correlation_id},
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
    print("[ui_rpc_server] ========== PYTHON BACKEND STARTING ==========", file=sys.stderr, flush=True)

    db = get_db()
    db.migrate()

    # Load persisted safety settings
    _load_persisted_safety_settings(db)
    print("[ui_rpc_server] Backend ready, waiting for requests...", file=sys.stderr, flush=True)

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
