"""RPC handler for natural language → shell command proposals.

Wraps ``shell_propose.propose_command_with_trace()`` behind the Cairn RPC
dispatch convention so the Tauri frontend can call ``reos/propose``.

Returns model_name and latency_ms in the response so the frontend can include
them in subsequent user_action telemetry events.  Also surfaces RAG fields
(undo_hint, rag_safety_level) from the trace when available.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Soft-risky patterns live in shell_propose so converse.py can import the same list.
# Keep a module-level alias for any code that still references _SOFT_RISKY_PATTERNS here.
from reos.shell_propose import SOFT_RISKY_PATTERNS as _SOFT_RISKY_PATTERNS  # noqa: E402


def handle_reos_propose(db: Any = None, *, natural_language: str) -> dict[str, Any]:
    """Propose a conversational response and optional shell command.

    Parameters
    ----------
    db : Any
        Cairn database handle (unused — kept for dispatch compatibility).
    natural_language : str
        The user's natural language input (typically captured from a
        "command not found" shell error).

    Returns
    -------
    dict with keys:
        message     : str        — conversational response (always present on success)
        command     : str | None — proposed shell command, or None if not applicable
        success     : bool       — True when message was generated; False only on LLM failure
        model_name  : str | None — Ollama model used (None on failure)
        latency_ms  : int | None — wall-clock inference time in ms (None on failure)
    """
    from reos.shell_propose import propose_command_with_trace
    from reos.telemetry import record_event

    try:
        trace = propose_command_with_trace(natural_language)
        message = trace.message
        command = trace.command
        model_name = trace.model_name
        latency_ms = trace.latency_ms
        attempt_count = trace.attempt_count
    except Exception as exc:
        logger.warning("propose_command_with_trace failed: %s", exc)
        # Fire-and-forget telemetry for the failure.
        try:
            record_event(
                session_id="backend",
                trace_id="backend",
                ts=int(time.time() * 1000),
                event_type="proposal_generated",
                payload={
                    "natural_language": natural_language,
                    "success": False,
                    "message": str(exc),
                    "command": None,
                    "model_name": None,
                    "latency_ms": None,
                    "attempt_count": None,
                    "failure_reason": "llm_error",
                },
            )
        except Exception:
            pass

        return {"message": str(exc), "command": None, "success": False,
                "model_name": None, "latency_ms": None,
                "is_risky": False, "risk_reason": None,
                "undo_hint": None, "rag_safety_level": None}

    # Record telemetry (fire-and-forget).
    try:
        failure_reason: str | None = None
        if not message:
            failure_reason = "llm_error"

        record_event(
            session_id="backend",
            trace_id="backend",
            ts=int(time.time() * 1000),
            event_type="proposal_generated",
            payload={
                "natural_language": natural_language,
                "success": bool(message),
                "message": message,
                "command": command,
                "model_name": model_name,
                "latency_ms": latency_ms,
                "attempt_count": attempt_count,
                "failure_reason": failure_reason,
            },
        )
    except Exception:
        pass  # Telemetry must never affect the response

    # Risky-command check
    is_risky = False
    risk_reason: str | None = None
    if command:
        from reos.shell_propose import is_safe_command

        _safe, _reason = is_safe_command(command)
        if not _safe:
            # Command was already blocked inside extract_conversational_response,
            # so this branch shouldn't normally fire. But guard it anyway.
            is_risky = True
            risk_reason = _reason
        else:
            for _pat, _msg in _SOFT_RISKY_PATTERNS:
                if _pat.search(command):
                    is_risky = True
                    risk_reason = _msg
                    break

    # RAG safety level overrides: a "dangerous" RAG classification forces is_risky.
    rag_safety_level = trace.rag_safety_level
    if rag_safety_level == "dangerous":
        is_risky = True
        if not risk_reason:
            risk_reason = "Flagged dangerous by RAG safety classifier"

    return {
        "message": message,
        "command": command,  # str or None
        "success": True,
        "model_name": model_name,
        "latency_ms": latency_ms,
        "is_risky": is_risky,
        "risk_reason": risk_reason,
        "undo_hint": trace.rag_undo,
        "rag_safety_level": rag_safety_level,
    }
