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
import sys
from pathlib import Path
from typing import Any

from .agent import ChatAgent
from .db import Database, get_db
from .mcp_tools import ToolError, call_tool, list_tools
from .user import (
    AuthenticationError,
    RecoveryError,
    SessionError,
    UserError,
    UserExistsError,
    UserNotFoundError,
    UserService,
    get_user_service,
)
from .play_fs import create_act as play_create_act
from .play_fs import create_beat as play_create_beat
from .play_fs import create_scene as play_create_scene
from .play_fs import kb_list_files as play_kb_list_files
from .play_fs import kb_read as play_kb_read
from .play_fs import kb_write_apply as play_kb_write_apply
from .play_fs import kb_write_preview as play_kb_write_preview
from .play_fs import list_acts as play_list_acts
from .play_fs import list_beats as play_list_beats
from .play_fs import list_scenes as play_list_scenes
from .play_fs import read_me_markdown as play_read_me_markdown
from .play_fs import set_active_act_id as play_set_active_act_id
from .play_fs import update_act as play_update_act
from .play_fs import update_beat as play_update_beat
from .play_fs import update_scene as play_update_scene

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


def _handle_chat_respond(db: Database, *, text: str) -> dict[str, Any]:
    agent = ChatAgent(db=db)
    answer = agent.respond(text)
    return {"answer": answer}


def _handle_state_get(db: Database, *, key: str) -> dict[str, Any]:
    return {"key": key, "value": db.get_state(key=key)}


def _handle_state_set(db: Database, *, key: str, value: str | None) -> dict[str, Any]:
    db.set_state(key=key, value=value)
    return {"ok": True}


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _handle_play_me_read(_db: Database) -> dict[str, Any]:
    return {"markdown": play_read_me_markdown()}


def _handle_play_acts_list(_db: Database) -> dict[str, Any]:
    acts, active_id = play_list_acts()
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_set_active(_db: Database, *, act_id: str) -> dict[str, Any]:
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
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
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
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
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
            for a in acts
        ],
    }


def _handle_play_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes}
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
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_create_beat(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            status=status or "",
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
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
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
    status: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    try:
        beats = play_update_beat(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            title=title,
            status=status,
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
                "status": b.status,
                "notes": b.notes,
                "link": b.link,
            }
            for b in beats
        ]
    }


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


# ============================================================================
# User Presence Handlers
# ============================================================================


def _handle_user_status(db: Database) -> dict[str, Any]:
    """Check if a user exists and if there's an active session."""
    svc = get_user_service(db)
    has_user = svc.has_user()
    current_user_id = svc.get_current_user_id()
    session = svc.get_session()

    return {
        "has_user": has_user,
        "current_user_id": current_user_id,
        "has_session": session is not None,
        "session_user_id": session.user_id if session else None,
    }


def _handle_user_register(
    db: Database,
    *,
    display_name: str,
    password: str,
    short_bio: str = "",
) -> dict[str, Any]:
    """Register a new user account."""
    svc = get_user_service(db)
    try:
        result = svc.register(
            display_name=display_name,
            password=password,
            short_bio=short_bio,
        )
        return {
            "user_id": result.user_id,
            "display_name": result.display_name,
            "session_id": result.session_id,
            "recovery_phrase": result.recovery_phrase,
        }
    except UserExistsError as exc:
        raise RpcError(code=-32010, message=exc.message) from exc
    except UserError as exc:
        raise RpcError(code=-32011, message=exc.message) from exc


def _handle_user_authenticate(db: Database, *, password: str) -> dict[str, Any]:
    """Authenticate with password."""
    svc = get_user_service(db)
    try:
        result = svc.authenticate(password=password)
        return {
            "user_id": result.user_id,
            "display_name": result.display_name,
            "session_id": result.session_id,
        }
    except UserNotFoundError as exc:
        raise RpcError(code=-32012, message=exc.message) from exc
    except AuthenticationError as exc:
        raise RpcError(code=-32013, message=exc.message) from exc


def _handle_user_logout(db: Database) -> dict[str, Any]:
    """Logout and invalidate session."""
    svc = get_user_service(db)
    svc.logout()
    return {"ok": True}


def _handle_user_card(db: Database) -> dict[str, Any]:
    """Get the current user's card with profile and bio."""
    svc = get_user_service(db)
    try:
        card = svc.get_user_card()
        return {
            "profile": {
                "user_id": card.profile.user_id,
                "display_name": card.profile.display_name,
                "created_at": card.profile.created_at.isoformat(),
                "updated_at": card.profile.updated_at.isoformat(),
            },
            "bio": {
                "short_bio": card.bio.short_bio,
                "full_bio": card.bio.full_bio,
                "skills": card.bio.skills,
                "interests": card.bio.interests,
                "goals": card.bio.goals,
                "context": card.bio.context,
            },
            "has_recovery_phrase": card.has_recovery_phrase,
            "encryption_enabled": card.encryption_enabled,
        }
    except SessionError as exc:
        raise RpcError(code=-32014, message=exc.message) from exc
    except UserNotFoundError as exc:
        raise RpcError(code=-32012, message=exc.message) from exc


def _handle_user_update_profile(
    db: Database,
    *,
    display_name: str | None = None,
    short_bio: str | None = None,
    full_bio: str | None = None,
    skills: list[str] | None = None,
    interests: list[str] | None = None,
    goals: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Update user profile and bio."""
    svc = get_user_service(db)
    try:
        card = svc.update_profile(
            display_name=display_name,
            short_bio=short_bio,
            full_bio=full_bio,
            skills=skills,
            interests=interests,
            goals=goals,
            context=context,
        )
        return {
            "profile": {
                "user_id": card.profile.user_id,
                "display_name": card.profile.display_name,
                "created_at": card.profile.created_at.isoformat(),
                "updated_at": card.profile.updated_at.isoformat(),
            },
            "bio": {
                "short_bio": card.bio.short_bio,
                "full_bio": card.bio.full_bio,
                "skills": card.bio.skills,
                "interests": card.bio.interests,
                "goals": card.bio.goals,
                "context": card.bio.context,
            },
            "has_recovery_phrase": card.has_recovery_phrase,
            "encryption_enabled": card.encryption_enabled,
        }
    except SessionError as exc:
        raise RpcError(code=-32014, message=exc.message) from exc
    except UserError as exc:
        raise RpcError(code=-32011, message=exc.message) from exc


def _handle_user_change_password(
    db: Database,
    *,
    current_password: str,
    new_password: str,
) -> dict[str, Any]:
    """Change password and re-encrypt data."""
    svc = get_user_service(db)
    try:
        result = svc.change_password(
            current_password=current_password,
            new_password=new_password,
        )
        return {
            "user_id": result.user_id,
            "display_name": result.display_name,
            "session_id": result.session_id,
        }
    except AuthenticationError as exc:
        raise RpcError(code=-32013, message=exc.message) from exc
    except SessionError as exc:
        raise RpcError(code=-32014, message=exc.message) from exc
    except UserError as exc:
        raise RpcError(code=-32011, message=exc.message) from exc


def _handle_user_recover(
    db: Database,
    *,
    recovery_phrase: str,
    new_password: str,
) -> dict[str, Any]:
    """Recover account using recovery phrase."""
    svc = get_user_service(db)
    try:
        result = svc.recover_account(
            recovery_phrase=recovery_phrase,
            new_password=new_password,
        )
        return {
            "user_id": result.user_id,
            "display_name": result.display_name,
            "session_id": result.session_id,
            "warning": "Your bio data has been reset because it was encrypted with your old password.",
        }
    except RecoveryError as exc:
        raise RpcError(code=-32015, message=exc.message) from exc
    except UserNotFoundError as exc:
        raise RpcError(code=-32012, message=exc.message) from exc
    except UserError as exc:
        raise RpcError(code=-32011, message=exc.message) from exc


def _handle_user_generate_recovery(db: Database) -> dict[str, Any]:
    """Generate a new recovery phrase."""
    svc = get_user_service(db)
    try:
        recovery_phrase = svc.generate_new_recovery_phrase()
        return {
            "recovery_phrase": recovery_phrase,
            "warning": "Store this phrase securely. It replaces any previous recovery phrase.",
        }
    except SessionError as exc:
        raise RpcError(code=-32014, message=exc.message) from exc


def _handle_user_delete(db: Database, *, password: str) -> dict[str, Any]:
    """Delete user account permanently."""
    svc = get_user_service(db)
    try:
        svc.delete_account(password=password)
        return {"ok": True, "message": "Account deleted permanently."}
    except AuthenticationError as exc:
        raise RpcError(code=-32013, message=exc.message) from exc
    except SessionError as exc:
        raise RpcError(code=-32014, message=exc.message) from exc


def _handle_jsonrpc_request(db: Database, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "jsonrpc-2.0",
                "serverInfo": {"name": "reos-ui-kernel", "version": "0.1.0"},
            }
            return _jsonrpc_result(req_id=req_id, result=result)

        # Notifications can omit id; ignore.
        if req_id is None:
            return None

        if method == "ping":
            return _jsonrpc_result(req_id=req_id, result={"ok": True})

        if method == "tools/list":
            return _jsonrpc_result(req_id=req_id, result=_tools_list())

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
            if not isinstance(text, str) or not text.strip():
                raise RpcError(code=-32602, message="text is required")
            result = _handle_chat_respond(db, text=text)
            return _jsonrpc_result(req_id=req_id, result=result)

        if method == "state/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = params.get("key")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_state_get(db, key=key))

        if method == "state/set":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            key = params.get("key")
            value = params.get("value")
            if not isinstance(key, str) or not key:
                raise RpcError(code=-32602, message="key is required")
            if value is not None and not isinstance(value, str):
                raise RpcError(code=-32602, message="value must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_state_set(db, key=key, value=value))

        if method == "personas/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_personas_list(db))

        if method == "personas/get":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if not isinstance(persona_id, str) or not persona_id:
                raise RpcError(code=-32602, message="persona_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_get(db, persona_id=persona_id))

        if method == "personas/upsert":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona = params.get("persona")
            if not isinstance(persona, dict):
                raise RpcError(code=-32602, message="persona must be an object")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_upsert(db, persona=persona))

        if method == "personas/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            persona_id = params.get("persona_id")
            if persona_id is not None and not isinstance(persona_id, str):
                raise RpcError(code=-32602, message="persona_id must be a string or null")
            return _jsonrpc_result(req_id=req_id, result=_handle_persona_set_active(db, persona_id=persona_id))

        if method == "play/me/read":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_me_read(db))

        if method == "play/acts/list":
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_list(db))

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
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            if title is not None and not isinstance(title, str):
                raise RpcError(code=-32602, message="title must be a string or null")
            if notes is not None and not isinstance(notes, str):
                raise RpcError(code=-32602, message="notes must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_acts_update(db, act_id=act_id, title=title, notes=notes),
            )

        if method == "play/acts/set_active":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            act_id = params.get("act_id")
            if not isinstance(act_id, str) or not act_id:
                raise RpcError(code=-32602, message="act_id is required")
            return _jsonrpc_result(req_id=req_id, result=_handle_play_acts_set_active(db, act_id=act_id))

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
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"status": status, "notes": notes, "link": link}.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_play_beats_create(
                    db,
                    act_id=act_id,
                    scene_id=scene_id,
                    title=title,
                    status=status,
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
            status = params.get("status")
            notes = params.get("notes")
            link = params.get("link")
            for k, v in {"title": title, "status": status, "notes": notes, "link": link}.items():
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
                    status=status,
                    notes=notes,
                    link=link,
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

        # ====================================================================
        # User Presence Methods
        # ====================================================================

        if method == "user/status":
            return _jsonrpc_result(req_id=req_id, result=_handle_user_status(db))

        if method == "user/register":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            display_name = params.get("display_name")
            password = params.get("password")
            short_bio = params.get("short_bio", "")
            if not isinstance(display_name, str) or not display_name.strip():
                raise RpcError(code=-32602, message="display_name is required")
            if not isinstance(password, str) or not password:
                raise RpcError(code=-32602, message="password is required")
            if short_bio is not None and not isinstance(short_bio, str):
                raise RpcError(code=-32602, message="short_bio must be a string")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_register(
                    db,
                    display_name=display_name,
                    password=password,
                    short_bio=short_bio or "",
                ),
            )

        if method == "user/authenticate":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            password = params.get("password")
            if not isinstance(password, str) or not password:
                raise RpcError(code=-32602, message="password is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_authenticate(db, password=password),
            )

        if method == "user/logout":
            return _jsonrpc_result(req_id=req_id, result=_handle_user_logout(db))

        if method == "user/card":
            return _jsonrpc_result(req_id=req_id, result=_handle_user_card(db))

        if method == "user/update_profile":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            display_name = params.get("display_name")
            short_bio = params.get("short_bio")
            full_bio = params.get("full_bio")
            skills = params.get("skills")
            interests = params.get("interests")
            goals = params.get("goals")
            context = params.get("context")
            # Validate string fields
            for k, v in {
                "display_name": display_name,
                "short_bio": short_bio,
                "full_bio": full_bio,
                "goals": goals,
                "context": context,
            }.items():
                if v is not None and not isinstance(v, str):
                    raise RpcError(code=-32602, message=f"{k} must be a string or null")
            # Validate list fields
            for k, v in {"skills": skills, "interests": interests}.items():
                if v is not None:
                    if not isinstance(v, list):
                        raise RpcError(code=-32602, message=f"{k} must be a list or null")
                    if not all(isinstance(item, str) for item in v):
                        raise RpcError(code=-32602, message=f"{k} must be a list of strings")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_update_profile(
                    db,
                    display_name=display_name,
                    short_bio=short_bio,
                    full_bio=full_bio,
                    skills=skills,
                    interests=interests,
                    goals=goals,
                    context=context,
                ),
            )

        if method == "user/change_password":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            current_password = params.get("current_password")
            new_password = params.get("new_password")
            if not isinstance(current_password, str) or not current_password:
                raise RpcError(code=-32602, message="current_password is required")
            if not isinstance(new_password, str) or not new_password:
                raise RpcError(code=-32602, message="new_password is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_change_password(
                    db,
                    current_password=current_password,
                    new_password=new_password,
                ),
            )

        if method == "user/recover":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            recovery_phrase = params.get("recovery_phrase")
            new_password = params.get("new_password")
            if not isinstance(recovery_phrase, str) or not recovery_phrase:
                raise RpcError(code=-32602, message="recovery_phrase is required")
            if not isinstance(new_password, str) or not new_password:
                raise RpcError(code=-32602, message="new_password is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_recover(
                    db,
                    recovery_phrase=recovery_phrase,
                    new_password=new_password,
                ),
            )

        if method == "user/generate_recovery":
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_generate_recovery(db),
            )

        if method == "user/delete":
            if not isinstance(params, dict):
                raise RpcError(code=-32602, message="params must be an object")
            password = params.get("password")
            if not isinstance(password, str) or not password:
                raise RpcError(code=-32602, message="password is required")
            return _jsonrpc_result(
                req_id=req_id,
                result=_handle_user_delete(db, password=password),
            )

        raise RpcError(code=-32601, message=f"Method not found: {method}")

    except RpcError as exc:
        return _jsonrpc_error(req_id=req_id, code=exc.code, message=exc.message, data=exc.data)
    except Exception as exc:  # noqa: BLE001
        return _jsonrpc_error(
            req_id=req_id,
            code=-32099,
            message="Internal error",
            data={"error": str(exc)},
        )


def run_stdio_server() -> None:
    """Run the UI kernel server over stdio."""

    db = get_db()
    db.migrate()

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
