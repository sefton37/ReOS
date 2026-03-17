"""ReOS Shell Propose - Propose commands, never execute.

This module implements the "Foreign until confirmed" principle:
- Takes natural language input
- Proposes a shell command
- Prints command and explanation to stdout
- NEVER EXECUTES ANYTHING

The shell script handles confirmation and native execution.

Output format:
  Line 1: The proposed command
  Line 2+: Explanation (optional)

Usage:
  python -m reos.shell_propose "install gimp"
  # Output:
  # sudo apt install gimp
  # Installs GIMP image editor using apt package manager
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from typing import NamedTuple, NoReturn

from trcore.db import get_db
from trcore.providers import get_provider

# ═══════════════════════════════════════════════════════════════════════════════
# Instrumentation types
# ═══════════════════════════════════════════════════════════════════════════════


class SanitizationFlags(NamedTuple):
    """Records which sanitization transforms fired during extract_command."""

    markdown_block: bool = False  # stripped ``` wrapper
    backtick: bool = False  # stripped single backtick
    prefix: bool = False  # stripped "Command:" / "Run:" etc.
    multiline: bool = False  # extracted first-line from multiline
    meta_rejection: bool = False  # rejected "bash"/"shell"/empty


@dataclass
class ProposalTrace:
    """Full internal trace of one propose_command_with_trace execution."""

    message: str
    command: str | None
    model_name: str
    latency_ms: int
    attempt_count: int

    # Attempt 1
    raw_response_1: str | None = None
    latency_ms_attempt1: int = 0
    tokens_prompt_1: int | None = None
    tokens_completion_1: int | None = None
    sentinel_found_1: bool = False
    command_before_safety_1: str | None = None
    safety_passed_1: bool = True
    safety_block_reason_1: str | None = None
    looks_like_cmd_1: bool = False

    # Attempt 2
    raw_response_2: str | None = None
    latency_ms_attempt2: int | None = None
    tokens_prompt_2: int | None = None
    tokens_completion_2: int | None = None
    sentinel_found_2: bool = False
    command_before_safety_2: str | None = None
    safety_passed_2: bool = True
    safety_block_reason_2: str | None = None
    looks_like_cmd_2: bool = False

    # Context
    context_can_verify: bool = False
    context_string: str = ""

    # Sanitization flags
    sanitize_markdown_block: bool = False
    sanitize_backtick: bool = False
    sanitize_prefix: bool = False
    sanitize_multiline: bool = False
    sanitize_meta_rejection: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Output Sanitization (assume garbage in)
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_command_with_flags(
    raw_response: str,
) -> tuple[str | None, str, SanitizationFlags]:
    """Internal implementation of extract_command that also returns sanitization flags.

    Returns:
        Tuple of (command or None, explanation, SanitizationFlags)
    """
    text = raw_response.strip()
    explanation = ""

    flag_markdown_block = False
    flag_backtick = False
    flag_prefix = False
    flag_multiline = False
    flag_meta_rejection = False

    # Strip markdown code blocks (``` or ```bash or ```shell)
    if text.startswith("```"):
        flag_markdown_block = True
        lines = text.split("\n")
        # Remove first line (```bash) and find closing ```
        code_lines = []
        after_lines = []
        in_code = True
        for line in lines[1:]:
            if line.strip() == "```":
                in_code = False
                continue
            if in_code:
                code_lines.append(line)
            else:
                after_lines.append(line)
        text = "\n".join(code_lines).strip()
        # Anything after the code block might be explanation
        if after_lines:
            explanation = " ".join(ln.strip() for ln in after_lines if ln.strip())

    # Strip single backticks wrapping the entire response
    if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        flag_backtick = True
        text = text[1:-1].strip()

    # Handle multiple lines - first line is command, rest is explanation
    if "\n" in text:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if lines:
            first_line = lines[0]
            # Strip backticks from first line
            first_line = first_line.strip("`").strip()
            if looks_like_command(first_line):
                flag_multiline = True
                text = first_line
                if len(lines) > 1:
                    explanation = " ".join(lines[1:])

    # Strip common prefixes
    for prefix in [
        "Command:",
        "Run:",
        "Execute:",
        "$ ",
        "> ",
        "Output:",
        "LINE 1:",
        "Line 1:",
        "line 1:",
        "bash ",
        "shell ",
    ]:
        if text.lower().startswith(prefix.lower()):
            flag_prefix = True
            text = text[len(prefix):].strip()

    # Strip any remaining backticks
    text = text.strip("`").strip()

    # Clean explanation prefixes
    for prefix in ["Explanation:", "LINE 2:", "Line 2:", "This command"]:
        if explanation.lower().startswith(prefix.lower()):
            explanation = explanation[len(prefix):].strip()

    # Reject meta-responses that aren't actual commands
    if text.lower() in ["bash", "shell", "linux", "terminal", "", "none"]:
        flag_meta_rejection = True
        flags = SanitizationFlags(
            markdown_block=flag_markdown_block,
            backtick=flag_backtick,
            prefix=flag_prefix,
            multiline=flag_multiline,
            meta_rejection=flag_meta_rejection,
        )
        return None, "Could not interpret as a command", flags

    # Validate it's actually a plausible command
    if not looks_like_command(text):
        flags = SanitizationFlags(
            markdown_block=flag_markdown_block,
            backtick=flag_backtick,
            prefix=flag_prefix,
            multiline=flag_multiline,
            meta_rejection=flag_meta_rejection,
        )
        return None, "Response doesn't look like a shell command", flags

    flags = SanitizationFlags(
        markdown_block=flag_markdown_block,
        backtick=flag_backtick,
        prefix=flag_prefix,
        multiline=flag_multiline,
        meta_rejection=flag_meta_rejection,
    )
    return text, explanation, flags


def extract_command(raw_response: str) -> tuple[str | None, str]:
    """
    LLMs will do all of these despite instructions:
    - Wrap in ```bash ... ```
    - Wrap in single backticks
    - Add explanations before/after
    - Return "bash" or "shell" as literals
    - Answer the question instead of commanding
    - Prefix with "Command:" or "Run:"
    - Add "LINE 1:" prefix

    Returns:
        Tuple of (command or None, explanation)
    """
    command, explanation, _flags = _extract_command_with_flags(raw_response)
    return command, explanation


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Command Validation (verify before proposing)
# ═══════════════════════════════════════════════════════════════════════════════


def looks_like_command(text: str) -> bool:
    """
    A command should:
    - Start with a word that could be a binary/builtin
    - Not be a complete English sentence
    - Not be a question
    - Not contain only articles/pronouns/prepositions
    """
    if not text or len(text) > 500:  # Commands don't need to be essays
        return False

    # Questions aren't commands
    if text.rstrip().endswith("?"):
        return False

    words = text.split()
    if not words:
        return False

    first_word = words[0].lower()

    # Common sentence starters that aren't commands
    sentence_starters = {
        "the",
        "a",
        "an",
        "this",
        "that",
        "i",
        "you",
        "it",
        "there",
        "here",
        "what",
        "who",
        "when",
        "where",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "can",
        "may",
        "to",
        "for",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
    }

    if first_word in sentence_starters:
        return False

    # If it has too many words and reads like prose, reject
    if len(words) > 15:
        # Allow if it has shell operators (pipes, redirects, etc.)
        if not any(c in text for c in ["|", ">", "<", "&&", "||", ";", "$", "/"]):
            return False

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: Safety Validation (reject dangerous commands)
# ═══════════════════════════════════════════════════════════════════════════════


def is_safe_command(command: str) -> tuple[bool, str]:
    """
    Check if command matches known dangerous patterns.

    Returns:
        Tuple of (is_safe, reason if unsafe)
    """
    dangerous_patterns = [
        (r"rm\s+-rf\s+/\s*$", "Cannot remove root filesystem"),
        (r"rm\s+-rf\s+/\*", "Cannot remove root filesystem"),
        (r"rm\s+-rf\s+~", "Cannot remove home directory"),
        (r"dd\s+if=.*of=/dev/sd", "Cannot write directly to disk"),
        (r"dd\s+if=/dev/zero", "Cannot wipe disk with zeros"),
        (r"dd\s+if=/dev/random", "Cannot overwrite with random data"),
        (r"dd\s+if=/dev/urandom", "Cannot overwrite with random data"),
        (r"mkfs\s+/dev/sd", "Cannot format disk"),
        (r"mkfs\.\w+\s+/dev/sd", "Cannot format disk"),
        (r":\(\)\s*\{.*\}", "Fork bombs are not allowed"),
        (r">\s*/dev/sd", "Cannot write directly to disk"),
        (r"chmod\s+-R\s+777\s+/", "Cannot make all files world-writable"),
    ]

    for pattern, reason in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, reason

    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 4: Main Proposal Logic (with retry)
# ═══════════════════════════════════════════════════════════════════════════════

CONVERSATIONAL_PROMPT = """You are ReOS, a natural language assistant embedded in a Linux terminal.
The user typed something the shell did not recognize. Help them.

FORMAT YOUR RESPONSE IN TWO PARTS:

First, write 1-3 sentences explaining what the user likely wants and what
tool or approach to use. Be direct. No markdown. Under 60 words.

Second, if a specific runnable shell command applies, write exactly:
COMMAND: <the full shell command here>

If no specific command applies (greeting, question with no shell equivalent,
etc.), omit the COMMAND line entirely.

RULES:
- No markdown formatting (no backticks, no asterisks, no hash symbols)
- COMMAND line contains ONLY the bare command, nothing else
- Use sudo when root privileges are required
- Never suggest dangerous commands (rm -rf /, dd to block devices, etc.)

EXAMPLES:

Input: show running processes
It looks like you want to see what is running. Use ps for a snapshot or htop for a live interactive view.
COMMAND: ps aux --sort=-%cpu | head -20

Input: install vim
You want to install the Vim text editor from the Ubuntu package repositories.
COMMAND: sudo apt install vim

Input: hello
Hello. I am ReOS. Type Linux commands here, or describe what you want to do in plain English and I will suggest the right command.

Input: what is my ip address
To see your machine's network addresses, ip addr lists all interfaces with their IPs. Use curl ifconfig.me for your public internet IP.
COMMAND: ip addr show

Input: list running services
This shows all systemd services that are currently active on your system.
COMMAND: systemctl list-units --type=service --state=running"""


CONSTRAINED_FALLBACK_PROMPT = """Output exactly one line: COMMAND: <shell command>
If no command applies, output: COMMAND: NONE

Task: {intent}"""


def _extract_conversational_response_with_meta(
    raw: str,
) -> tuple[str, str | None, bool, str | None]:
    """Internal implementation of extract_conversational_response that also returns
    sentinel and pre-safety-check command.

    Returns:
        Tuple of (message, command_or_None, sentinel_found, command_before_safety)
        - message:               Conversational response text (truncated to 500 chars)
        - command_or_None:       Command after safety check, or None
        - sentinel_found:        True if COMMAND: sentinel was present in raw response
        - command_before_safety: The raw command text before safety check (or None)
    """
    text = raw.strip()

    # Look for COMMAND: sentinel (case-insensitive)
    sentinel_idx = -1
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("COMMAND:"):
            sentinel_idx = i
            break

    sentinel_found = sentinel_idx >= 0

    if sentinel_found:
        message_lines = lines[:sentinel_idx]
        command_line = lines[sentinel_idx].strip()
        # Strip the COMMAND: prefix
        command_raw = command_line.split(":", 1)[1].strip() if ":" in command_line else ""

        message = "\n".join(message_lines).strip()

        if command_raw and command_raw.upper() != "NONE":
            command_before_safety = command_raw
            # Safety check
            is_safe, reason = is_safe_command(command_raw)
            if not is_safe:
                message += f"\n(Command blocked: {reason})"
                return message[:500], None, sentinel_found, command_before_safety
            return message[:500], command_raw, sentinel_found, command_before_safety
        return message[:500], None, sentinel_found, None
    else:
        # No COMMAND: sentinel — purely conversational
        return text[:500], None, False, None


def extract_conversational_response(raw: str) -> tuple[str, str | None]:
    """Split LLM response into message and optional command.

    Looks for a COMMAND: sentinel line. Everything before it is the message.
    Everything after is the command (passed through extract_command for cleanup).

    Returns: (message, command_or_None)
    """
    message, command, _sentinel_found, _command_before_safety = (
        _extract_conversational_response_with_meta(raw)
    )
    return message, command


def propose_command_with_trace(natural_language: str) -> ProposalTrace:
    """Propose a conversational response and optional shell command, returning a full trace.

    Runs the complete pipeline (context gathering, LLM call(s), parsing, safety checks)
    and populates every field of ProposalTrace with intermediate state. Intended for
    use by the benchmark runner and any other caller that needs full pipeline visibility.

    NEVER EXECUTES ANYTHING.
    """
    db = get_db()
    llm = get_provider(db)

    # Resolve model name up front — _model may be None until first call.
    model_name: str = getattr(llm, "_model", None) or getattr(llm, "model", None) or "unknown"

    # ═══════════════════════════════════════════════════════════════════════════
    # Context Gathering (RIVA: Can I verify this intent?)
    # ═══════════════════════════════════════════════════════════════════════════
    context_can_verify = False
    context_string = ""
    try:
        from .shell_context import get_context_for_proposal

        context = get_context_for_proposal(natural_language)

        if context.can_verify:
            context_can_verify = True
            context_string = f"\nSystem Context:\n{context.to_context_string()}\n"
    except Exception:
        pass  # Context gathering is optional - fail open

    # Build enriched prompt
    user_prompt = f"Input: {natural_language}"
    if context_string:
        user_prompt = f"{context_string}\n{user_prompt}"

    start = time.monotonic()

    # ── Attempt 1: conversational prompt ────────────────────────────────────
    raw_response_1: str | None = None
    latency_ms_attempt1 = 0
    sentinel_found_1 = False
    command_before_safety_1: str | None = None
    safety_passed_1 = True
    safety_block_reason_1: str | None = None
    looks_like_cmd_1 = False
    attempt1_message: str | None = None
    attempt1_command: str | None = None
    attempt1_ok = False

    try:
        response = llm.chat_text(
            system=CONVERSATIONAL_PROMPT,
            user=user_prompt,
            temperature=0.3,
        )

        t_after_attempt1 = time.monotonic()
        latency_ms_attempt1 = int((t_after_attempt1 - start) * 1000)
        raw_response_1 = response

        message, command, sentinel_found_1, command_before_safety_1 = (
            _extract_conversational_response_with_meta(response)
        )

        # Determine safety outcome for trace (re-derive from command_before_safety_1)
        if command_before_safety_1 is not None and command_before_safety_1.upper() != "NONE":
            is_safe, reason = is_safe_command(command_before_safety_1)
            safety_passed_1 = is_safe
            safety_block_reason_1 = reason if not is_safe else None
            looks_like_cmd_1 = looks_like_command(command_before_safety_1)

        if message:
            # After LLM succeeds, try to resolve actual model name if still unknown.
            if model_name == "unknown":
                model_name = getattr(llm, "_model", None) or "unknown"

            attempt1_message = message
            attempt1_command = command
            attempt1_ok = True

    except Exception:
        latency_ms_attempt1 = int((time.monotonic() - start) * 1000)
        # Fall through to constrained retry

    # If attempt 1 succeeded, build and return trace immediately.
    if attempt1_ok and attempt1_message is not None:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProposalTrace(
            message=attempt1_message,
            command=attempt1_command,
            model_name=model_name,
            latency_ms=elapsed_ms,
            attempt_count=1,
            raw_response_1=raw_response_1,
            latency_ms_attempt1=latency_ms_attempt1,
            sentinel_found_1=sentinel_found_1,
            command_before_safety_1=command_before_safety_1,
            safety_passed_1=safety_passed_1,
            safety_block_reason_1=safety_block_reason_1,
            looks_like_cmd_1=looks_like_cmd_1,
            context_can_verify=context_can_verify,
            context_string=context_string,
        )

    # ── Attempt 2: constrained fallback prompt ───────────────────────────────
    # Only reaches here when attempt 1 completely failed (exception or empty response).
    raw_response_2: str | None = None
    latency_ms_attempt2: int | None = None
    sentinel_found_2 = False
    command_before_safety_2: str | None = None
    safety_passed_2 = True
    safety_block_reason_2: str | None = None
    looks_like_cmd_2 = False

    try:
        response2 = llm.chat_text(
            system="You are a shell command generator. Output only commands.",
            user=CONSTRAINED_FALLBACK_PROMPT.format(intent=natural_language),
            temperature=0.1,  # Even lower temperature for more deterministic output
        )

        t_after_attempt2 = time.monotonic()
        latency_ms_attempt2 = int((t_after_attempt2 - start) * 1000) - latency_ms_attempt1
        raw_response_2 = response2

        # For constrained prompt, just take the first line
        text = response2.strip().split("\n")[0].strip()
        text = text.strip("`").strip()

        if model_name == "unknown":
            model_name = getattr(llm, "_model", None) or "unknown"

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Check for explicit failure
        if text.upper() in ("NONE", "COMMAND: NONE"):
            return ProposalTrace(
                message="I could not determine a command for that request.",
                command=None,
                model_name=model_name,
                latency_ms=elapsed_ms,
                attempt_count=2,
                raw_response_1=raw_response_1,
                latency_ms_attempt1=latency_ms_attempt1,
                sentinel_found_1=sentinel_found_1,
                command_before_safety_1=command_before_safety_1,
                safety_passed_1=safety_passed_1,
                safety_block_reason_1=safety_block_reason_1,
                looks_like_cmd_1=looks_like_cmd_1,
                raw_response_2=raw_response_2,
                latency_ms_attempt2=latency_ms_attempt2,
                sentinel_found_2=False,
                context_can_verify=context_can_verify,
                context_string=context_string,
            )

        # Strip COMMAND: prefix if present
        sentinel_found_2 = text.upper().startswith("COMMAND:")
        if sentinel_found_2:
            text = text.split(":", 1)[1].strip()

        # Validate
        looks_like_cmd_2 = looks_like_command(text)
        command_before_safety_2 = text if looks_like_cmd_2 else None

        if looks_like_cmd_2:
            is_safe, reason = is_safe_command(text)
            safety_passed_2 = is_safe
            safety_block_reason_2 = reason if not is_safe else None

            if not is_safe:
                return ProposalTrace(
                    message=f"I found a command but it was blocked for safety: {reason}",
                    command=None,
                    model_name=model_name,
                    latency_ms=elapsed_ms,
                    attempt_count=2,
                    raw_response_1=raw_response_1,
                    latency_ms_attempt1=latency_ms_attempt1,
                    sentinel_found_1=sentinel_found_1,
                    command_before_safety_1=command_before_safety_1,
                    safety_passed_1=safety_passed_1,
                    safety_block_reason_1=safety_block_reason_1,
                    looks_like_cmd_1=looks_like_cmd_1,
                    raw_response_2=raw_response_2,
                    latency_ms_attempt2=latency_ms_attempt2,
                    sentinel_found_2=sentinel_found_2,
                    command_before_safety_2=command_before_safety_2,
                    safety_passed_2=False,
                    safety_block_reason_2=reason,
                    looks_like_cmd_2=looks_like_cmd_2,
                    context_can_verify=context_can_verify,
                    context_string=context_string,
                )

            return ProposalTrace(
                message="Here is what I suggest:",
                command=text,
                model_name=model_name,
                latency_ms=elapsed_ms,
                attempt_count=2,
                raw_response_1=raw_response_1,
                latency_ms_attempt1=latency_ms_attempt1,
                sentinel_found_1=sentinel_found_1,
                command_before_safety_1=command_before_safety_1,
                safety_passed_1=safety_passed_1,
                safety_block_reason_1=safety_block_reason_1,
                looks_like_cmd_1=looks_like_cmd_1,
                raw_response_2=raw_response_2,
                latency_ms_attempt2=latency_ms_attempt2,
                sentinel_found_2=sentinel_found_2,
                command_before_safety_2=command_before_safety_2,
                safety_passed_2=True,
                looks_like_cmd_2=looks_like_cmd_2,
                context_can_verify=context_can_verify,
                context_string=context_string,
            )

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProposalTrace(
            message=f"Error: {e}",
            command=None,
            model_name=model_name,
            latency_ms=elapsed_ms,
            attempt_count=2,
            raw_response_1=raw_response_1,
            latency_ms_attempt1=latency_ms_attempt1,
            sentinel_found_1=sentinel_found_1,
            command_before_safety_1=command_before_safety_1,
            safety_passed_1=safety_passed_1,
            safety_block_reason_1=safety_block_reason_1,
            looks_like_cmd_1=looks_like_cmd_1,
            raw_response_2=raw_response_2,
            latency_ms_attempt2=latency_ms_attempt2,
            context_can_verify=context_can_verify,
            context_string=context_string,
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return ProposalTrace(
        message="I could not interpret that as a command.",
        command=None,
        model_name=model_name,
        latency_ms=elapsed_ms,
        attempt_count=2,
        raw_response_1=raw_response_1,
        latency_ms_attempt1=latency_ms_attempt1,
        sentinel_found_1=sentinel_found_1,
        command_before_safety_1=command_before_safety_1,
        safety_passed_1=safety_passed_1,
        safety_block_reason_1=safety_block_reason_1,
        looks_like_cmd_1=looks_like_cmd_1,
        raw_response_2=raw_response_2,
        latency_ms_attempt2=latency_ms_attempt2,
        sentinel_found_2=sentinel_found_2,
        command_before_safety_2=command_before_safety_2,
        safety_passed_2=safety_passed_2,
        safety_block_reason_2=safety_block_reason_2,
        looks_like_cmd_2=looks_like_cmd_2,
        context_can_verify=context_can_verify,
        context_string=context_string,
    )


def propose_command_with_meta(
    natural_language: str,
) -> tuple[str, str | None, str, int, int]:
    """Propose a conversational response and optional shell command with model metadata.

    Returns:
        Tuple of (message, command, model_name, latency_ms, attempt_count)
        - message:       Conversational response text (always present on success)
        - command:       The shell command to run, or None if not applicable
        - model_name:    Ollama model name used, or 'unknown' if not determinable
        - latency_ms:    Wall-clock time from first LLM call to last, in ms
        - attempt_count: 1 (first attempt succeeded) or 2 (retry was needed)

    Kernel: "Explain what to do, then suggest a command if one applies."
    NEVER EXECUTES ANYTHING.
    """
    trace = propose_command_with_trace(natural_language)
    return trace.message, trace.command, trace.model_name, trace.latency_ms, trace.attempt_count


def propose_command(natural_language: str) -> tuple[str, str]:
    """Propose a shell command for natural language input.

    Args:
        natural_language: The user's natural language request

    Returns:
        Tuple of (command, message)
        - command: The shell command to run (empty string if not applicable)
        - message: Conversational response text

    Delegates to ``propose_command_with_meta()`` and drops the extra metadata.
    NEVER EXECUTES ANYTHING.
    """
    msg, cmd, _model, _latency, _attempts = propose_command_with_meta(natural_language)
    return cmd or "", msg


def main() -> NoReturn:
    """Main entry point for shell propose CLI."""
    if len(sys.argv) < 2:
        print("Usage: python -m reos.shell_propose 'natural language request'", file=sys.stderr)
        sys.exit(1)

    # Join all arguments as the natural language input
    natural_language = " ".join(sys.argv[1:])

    msg, command, _model, _latency, _attempts = propose_command_with_meta(natural_language)

    # Always print the message
    if msg:
        print(msg)

    if command:
        print(f"\nSuggested command: {command}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
