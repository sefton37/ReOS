"""RPC handler for natural language → shell command proposals.

Wraps ``shell_propose.propose_command_with_meta()`` behind the Cairn RPC
dispatch convention so the Tauri frontend can call ``reos/propose``.

Returns model_name and latency_ms in the response so the frontend can include
them in subsequent user_action telemetry events.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Soft-risky patterns: commands that pass safety validation but warrant a visual
# warning badge in the frontend.  Compiled once at import time.
_SOFT_RISKY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b", re.IGNORECASE), "Requires elevated privileges"),
    (re.compile(r"\brm\b.*-[rRf]", re.IGNORECASE), "Recursive or forced delete"),
    (re.compile(r"\bdd\b", re.IGNORECASE), "Low-level disk operation"),
    (re.compile(r"\bchmod\b.*777", re.IGNORECASE), "Makes files world-writable"),
    (re.compile(r"\bcurl\b.*\|\s*(?:bash|sh)\b", re.IGNORECASE), "Pipes remote content to shell"),
    (re.compile(r"\bwget\b.*\|\s*(?:bash|sh)\b", re.IGNORECASE), "Pipes remote content to shell"),
    (re.compile(r"\bsystemctl\b\s+(?:stop|disable|mask)\b", re.IGNORECASE),
     "Modifies service state"),
    (re.compile(r"\bapt(?:-get)?\b.*(?:remove|purge)", re.IGNORECASE), "Removes packages"),
]


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
    from reos.shell_propose import propose_command_with_meta
    from reos.telemetry import record_event

    try:
        message, command, model_name, latency_ms, attempt_count = propose_command_with_meta(
            natural_language
        )
    except Exception as exc:
        logger.warning("propose_command_with_meta failed: %s", exc)
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
                "is_risky": False, "risk_reason": None}

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

    return {
        "message": message,
        "command": command,  # str or None
        "success": True,
        "model_name": model_name,
        "latency_ms": latency_ms,
        "is_risky": is_risky,
        "risk_reason": risk_reason,
    }
