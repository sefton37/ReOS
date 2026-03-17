"""RPC handlers for the ReOS Conversational Shell.

Three endpoints:

    reos/converse       – Primary turn: NL → classification → turn_type + optional command
    reos/execute        – Execute an approved command via subprocess (never PTY)
    reos/converse/abort – Discard a pending operation without executing

Backend is stateless across calls: all conversation history is passed in from
the frontend on each request.  No server-side session store is maintained.

Safety model (two independent checks, defence in depth):
    1. NL input classified + SOFT_RISKY_PATTERNS / is_safe_command() at propose time
    2. is_safe_command() re-checked at execute time before subprocess.run()

TTY-requiring commands are detected and returned as turn_type="inform" with a
redirect message — the conversational shell cannot host interactive processes.
"""

from __future__ import annotations

import logging
import subprocess
import time
import uuid
from typing import Any

from reos.shell_propose import SOFT_RISKY_PATTERNS, is_safe_command, propose_command_with_trace

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# TTY-requiring commands
# Commands that need a real terminal emulator (ncurses, interactive prompts,
# readline, etc.).  When a proposed command starts with one of these the handler
# returns turn_type="inform" telling the user to switch to the Terminal tab.
# ═══════════════════════════════════════════════════════════════════════════════

_TTY_COMMANDS: frozenset[str] = frozenset(
    [
        "vim",
        "vi",
        "nvim",
        "nano",
        "emacs",
        "less",
        "more",
        "htop",
        "top",
        "btop",
        "ssh",
        "man",
        "info",
        "pager",
        "watch",
        "tmux",
        "screen",
        "bash",
        "sh",
        "zsh",
        "fish",
        "sudo",  # sudo alone (without an argument) is interactive
        "su",
        "python",
        "python3",
        "irb",
        "node",
        "psql",
        "mysql",
        "sqlite3",
        "fzf",
        "mc",
        "ranger",
        "nnn",
        "cfdisk",
        "fdisk",
        "gdisk",
    ]
)

# Maximum output size returned for conversational display (50 KB)
_OUTPUT_TRUNCATE_BYTES = 50 * 1024

# Maximum turns kept as conversation context (prevents context-window overflow)
_MAX_HISTORY_TURNS = 8


# ═══════════════════════════════════════════════════════════════════════════════
# Intent classification (pragmatic fallback when AtomicOpsProcessor unavailable)
# ═══════════════════════════════════════════════════════════════════════════════

# Keyword lists for lightweight classification without an LLM call.
_GREETING_KEYWORDS: frozenset[str] = frozenset(
    ["hello", "hi", "hey", "yo", "greetings", "howdy", "sup", "what's up", "whats up"]
)
_DANGEROUS_KEYWORDS: tuple[str, ...] = (
    "delete all",
    "remove all",
    "wipe",
    "destroy",
    "format",
    "nuke",
    "erase everything",
    "rm -rf /",
    "fork bomb",
    "kill all",
    "killall",
    "shutdown now",
    "reboot now",
)
_DIAGNOSTIC_KEYWORDS: tuple[str, ...] = (
    "show",
    "list",
    "check",
    "status",
    "monitor",
    "view",
    "display",
    "what is",
    "what are",
    "how much",
    "how many",
    "disk usage",
    "memory",
    "cpu",
    "processes",
    "services",
    "logs",
    "uptime",
    "who",
    "df",
    "du",
    "ps",
    "top",
    "free",
)
_VAGUE_PATTERNS: tuple[str, ...] = (
    "fix",
    "help",
    "something",
    "anything",
    "everything",
    "my computer",
    "it",
    "this",
    "make it work",
    "make it better",
    "improve",
    "optimize",
)


def _classify_intent(
    natural_language: str,
    turn_history: list[dict[str, Any]],  # noqa: ARG001  (reserved for future use)
) -> dict[str, Any]:
    """Classify user intent for the conversational shell using keyword heuristics.

    Tries to classify without an LLM call.  Returns confident=False when the
    input doesn't match any keyword pattern, deferring full classification to
    the downstream propose_command_with_trace() call.

    Returns:
        dict with keys:
            intent:    "greeting" | "question" | "diagnostic" | "execute"
                       | "dangerous" | "unclear"
            confident: bool — True when keyword match is unambiguous
    """
    text = natural_language.lower().strip()

    # Greetings
    if text in _GREETING_KEYWORDS or any(text.startswith(g + " ") for g in _GREETING_KEYWORDS):
        return {"intent": "greeting", "confident": True}

    # Dangerous requests — check before diagnostics to avoid mis-routing
    if any(kw in text for kw in _DANGEROUS_KEYWORDS):
        return {"intent": "dangerous", "confident": True}

    # Vague / unclear
    words = text.split()
    if len(words) <= 2 and any(vague in text for vague in _VAGUE_PATTERNS):
        return {"intent": "unclear", "confident": True}

    # Diagnostic / read-only
    if any(text.startswith(kw) or f" {kw} " in f" {text} " for kw in _DIAGNOSTIC_KEYWORDS):
        return {"intent": "diagnostic", "confident": False}  # medium confidence

    # Default: assume execute intent, let LLM figure it out
    return {"intent": "execute", "confident": False}


def _build_conversation_context(turn_history: list[dict[str, Any]]) -> str:
    """Format the last N turns as a dialogue prefix for the LLM prompt.

    Args:
        turn_history: List of {role: "user"|"assistant", content: str} dicts.

    Returns:
        Multi-line string "User: ...\\nAssistant: ..." or empty string.
    """
    if not turn_history:
        return ""

    # Cap at _MAX_HISTORY_TURNS entries (most recent)
    recent = turn_history[-_MAX_HISTORY_TURNS:]

    lines: list[str] = ["Conversation history (most recent last):"]
    for turn in recent:
        role = turn.get("role", "user")
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")

    if len(lines) == 1:
        return ""  # nothing useful was added
    return "\n".join(lines)


def _needs_tty(command: str) -> bool:
    """Return True if the command requires an interactive terminal emulator.

    Checks the first token of the command against _TTY_COMMANDS.  Commands
    that follow a sudo prefix are also checked (e.g. "sudo vim /etc/hosts").
    """
    if not command:
        return False
    parts = command.strip().split()
    if not parts:
        return False
    first = parts[0].lower()
    if first in _TTY_COMMANDS:
        # sudo alone is TTY-requiring; sudo with args depends on the argument
        if first == "sudo" and len(parts) > 1:
            return parts[1].lower() in _TTY_COMMANDS
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# RPC Handlers
# ═══════════════════════════════════════════════════════════════════════════════


def handle_reos_converse(
    db: Any = None,
    *,
    natural_language: str,
    conversation_id: str,
    turn_history: list[dict[str, Any]],
    system_context: dict[str, Any],  # noqa: ARG001  (reserved for future use)
) -> dict[str, Any]:
    """Primary conversational turn endpoint.

    Classifies the user's intent, optionally proposes a shell command, and
    returns a structured turn result that the frontend renders as one of:
        clarify  – system needs more information before proposing
        inform   – pure conversational response, no command
        propose  – safe command proposal with approve/skip UI
        danger   – risky command, explicit acknowledge required
        refuse   – hard-blocked command, no execution path

    Parameters
    ----------
    db :               Cairn database handle (passed through, may be None).
    natural_language : The user's free-text input.
    conversation_id :  UUID for this session (used to tag AtomicOperation records).
    turn_history :     List of prior {role, content} turns (frontend-supplied).
    system_context :   Distro / package manager info from the vitals dashboard.

    Returns
    -------
    dict with keys:
        turn_type    : str  — one of clarify | inform | propose | danger | refuse
        message      : str  — conversational explanation
        command      : str | None
        explanation  : str | None
        is_risky     : bool
        risk_reason  : str | None
        operation_id : str  — UUID for approval tracking
        classification: dict — {intent, confident} for debug display
        latency_ms   : int
    """
    start = time.monotonic()
    operation_id = str(uuid.uuid4())

    # --- Classify intent using lightweight keyword heuristics ---
    classification = _classify_intent(natural_language, turn_history)
    intent = classification["intent"]

    # --- Hard refusal: dangerous intent detected at classification stage ---
    if intent == "dangerous":
        return {
            "turn_type": "refuse",
            "message": (
                "That request involves destructive operations that ReOS will not perform. "
                "If you need to remove files or reconfigure system state, please be specific "
                "about which files and why."
            ),
            "command": None,
            "explanation": None,
            "is_risky": True,
            "risk_reason": "Dangerous intent detected",
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- Greetings and pure conversational turns (no command needed) ---
    if intent == "greeting":
        return {
            "turn_type": "inform",
            "message": (
                "Hello. I am ReOS. Describe what you want to do with your Linux system "
                "and I will suggest the right command, or explain what is happening."
            ),
            "command": None,
            "explanation": None,
            "is_risky": False,
            "risk_reason": None,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- Vague / unclear: ask a clarifying question without hitting the LLM ---
    if intent == "unclear" and classification["confident"]:
        return {
            "turn_type": "clarify",
            "message": (
                "Could you be more specific about what you would like to do? "
                "For example: 'show disk usage', 'check nginx status', "
                "or 'list running processes'."
            ),
            "command": None,
            "explanation": None,
            "is_risky": False,
            "risk_reason": None,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- Call propose_command_with_trace() for all other intents ---
    conversation_context = _build_conversation_context(turn_history)
    try:
        trace = propose_command_with_trace(
            natural_language,
            conversation_context=conversation_context,
        )
    except Exception as exc:
        logger.warning("propose_command_with_trace failed in converse handler: %s", exc)
        return {
            "turn_type": "inform",
            "message": f"I encountered an error processing your request: {exc}",
            "command": None,
            "explanation": None,
            "is_risky": False,
            "risk_reason": None,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    message = trace.message
    command = trace.command

    # --- TTY detection: redirect to Terminal tab ---
    if command and _needs_tty(command):
        return {
            "turn_type": "inform",
            "message": (
                f"The command `{command}` requires an interactive terminal. "
                "Switch to the Terminal tab and run it there."
            ),
            "command": None,
            "explanation": None,
            "is_risky": False,
            "risk_reason": None,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- No command produced: pure informational response ---
    if not command:
        return {
            "turn_type": "inform",
            "message": message,
            "command": None,
            "explanation": None,
            "is_risky": False,
            "risk_reason": None,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- Hard safety check (is_safe_command) ---
    safe, block_reason = is_safe_command(command)
    if not safe:
        return {
            "turn_type": "refuse",
            "message": (
                f"The proposed command was blocked for safety: {block_reason}. "
                "ReOS will not propose or execute this command."
            ),
            "command": None,
            "explanation": None,
            "is_risky": True,
            "risk_reason": block_reason,
            "operation_id": operation_id,
            "classification": classification,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }

    # --- Soft-risky pattern check ---
    is_risky = False
    risk_reason: str | None = None
    for pattern, reason in SOFT_RISKY_PATTERNS:
        if pattern.search(command):
            is_risky = True
            risk_reason = reason
            break

    # Determine turn_type from risk level
    turn_type = "danger" if is_risky else "propose"

    return {
        "turn_type": turn_type,
        "message": message,
        "command": command,
        "explanation": None,  # Phase 2: extract explanation from trace
        "is_risky": is_risky,
        "risk_reason": risk_reason,
        "undo_hint": trace.rag_undo,
        "operation_id": operation_id,
        "classification": classification,
        "latency_ms": int((time.monotonic() - start) * 1000),
    }


def handle_reos_execute(
    db: Any = None,  # noqa: ARG001
    *,
    operation_id: str,  # noqa: ARG001  (reserved for Phase 2 operation store)
    command: str,
    conversation_id: str,  # noqa: ARG001  (reserved for Phase 2 audit tagging)
) -> dict[str, Any]:
    """Execute an approved command via subprocess (never via PTY).

    Defense-in-depth: is_safe_command() is re-checked here even though the
    frontend only calls this endpoint after receiving turn_type="propose" or
    "danger".  The extra check guards against replayed or tampered requests.

    Parameters
    ----------
    db :             Cairn database handle (unused in Phase 1).
    operation_id :   UUID from the preceding reos/converse response.
    command :        The shell command to run (may have been edited by the user).
    conversation_id: Session UUID for audit tagging (Phase 2).

    Returns
    -------
    dict with keys:
        success    : bool
        exit_code  : int | None
        stdout     : str
        stderr     : str
        duration_ms: int
        truncated  : bool — True if stdout or stderr were capped at 50 KB
    """
    start = time.monotonic()

    # Defence-in-depth safety re-check
    safe, reason = is_safe_command(command)
    if not safe:
        logger.warning("execute blocked by safety re-check: %s — %s", command, reason)
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": f"Blocked: {reason}",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "truncated": False,
        }

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            shell=True,  # commands are full shell strings (pipes, redirects, etc.)
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "Command timed out after 30 seconds.",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "truncated": False,
        }
    except Exception as exc:
        logger.warning("subprocess.run failed for command %r: %s", command, exc)
        return {
            "success": False,
            "exit_code": None,
            "stdout": "",
            "stderr": f"Execution error: {exc}",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "truncated": False,
        }

    # Truncate output at 50 KB for conversational display
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    truncated = False

    if len(stdout.encode()) > _OUTPUT_TRUNCATE_BYTES:
        stdout = stdout.encode()[:_OUTPUT_TRUNCATE_BYTES].decode(errors="replace")
        truncated = True

    if len(stderr.encode()) > _OUTPUT_TRUNCATE_BYTES:
        stderr = stderr.encode()[:_OUTPUT_TRUNCATE_BYTES].decode(errors="replace")
        truncated = True

    return {
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": truncated,
    }


def handle_reos_converse_abort(
    db: Any = None,  # noqa: ARG001
    *,
    operation_id: str,  # noqa: ARG001  (reserved for Phase 2 operation store)
) -> dict[str, Any]:
    """Discard a pending operation without executing it.

    In Phase 1 this is a no-op that signals the frontend the abort was
    acknowledged.  Phase 2 will update the AtomicOperation status to FAILED.

    Returns
    -------
    dict with keys:
        aborted: bool — always True
    """
    return {"aborted": True}
