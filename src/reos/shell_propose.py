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
from typing import NoReturn

from trcore.db import get_db
from trcore.providers import get_provider


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Output Sanitization (assume garbage in)
# ═══════════════════════════════════════════════════════════════════════════════

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
    text = raw_response.strip()
    explanation = ""

    # Strip markdown code blocks (``` or ```bash or ```shell)
    if text.startswith("```"):
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
            explanation = " ".join(l.strip() for l in after_lines if l.strip())

    # Strip single backticks wrapping the entire response
    if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        text = text[1:-1].strip()

    # Handle multiple lines - first line is command, rest is explanation
    if "\n" in text:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            first_line = lines[0]
            # Strip backticks from first line
            first_line = first_line.strip("`").strip()
            if looks_like_command(first_line):
                text = first_line
                if len(lines) > 1:
                    explanation = " ".join(lines[1:])

    # Strip common prefixes
    for prefix in ["Command:", "Run:", "Execute:", "$ ", "> ", "Output:",
                   "LINE 1:", "Line 1:", "line 1:", "bash ", "shell "]:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    # Strip any remaining backticks
    text = text.strip("`").strip()

    # Clean explanation prefixes
    for prefix in ["Explanation:", "LINE 2:", "Line 2:", "This command"]:
        if explanation.lower().startswith(prefix.lower()):
            explanation = explanation[len(prefix):].strip()

    # Reject meta-responses that aren't actual commands
    if text.lower() in ["bash", "shell", "linux", "terminal", "", "none"]:
        return None, "Could not interpret as a command"

    # Validate it's actually a plausible command
    if not looks_like_command(text):
        return None, "Response doesn't look like a shell command"

    return text, explanation


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
        "the", "a", "an", "this", "that", "i", "you",
        "it", "there", "here", "what", "who", "when",
        "where", "why", "how", "is", "are", "was", "were",
        "will", "would", "could", "should", "can", "may",
        "to", "for", "of", "in", "on", "at", "by", "with"
    }

    if first_word in sentence_starters:
        return False

    # If it has too many words and reads like prose, reject
    if len(words) > 15:
        # Allow if it has shell operators (pipes, redirects, etc.)
        if not any(c in text for c in ['|', '>', '<', '&&', '||', ';', '$', '/']):
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


def extract_conversational_response(raw: str) -> tuple[str, str | None]:
    """Split LLM response into message and optional command.

    Looks for a COMMAND: sentinel line. Everything before it is the message.
    Everything after is the command (passed through extract_command for cleanup).

    Returns: (message, command_or_None)
    """
    text = raw.strip()

    # Look for COMMAND: sentinel (case-insensitive)
    sentinel_idx = -1
    lines = text.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith('COMMAND:'):
            sentinel_idx = i
            break

    if sentinel_idx >= 0:
        message_lines = lines[:sentinel_idx]
        command_line = lines[sentinel_idx].strip()
        # Strip the COMMAND: prefix
        command_raw = command_line.split(':', 1)[1].strip() if ':' in command_line else ''

        message = '\n'.join(message_lines).strip()

        if command_raw and command_raw.upper() != 'NONE':
            # Safety check
            is_safe, reason = is_safe_command(command_raw)
            if not is_safe:
                message += f'\n(Command blocked: {reason})'
                return message[:500], None
            return message[:500], command_raw
        return message[:500], None
    else:
        # No COMMAND: sentinel — purely conversational
        return text[:500], None


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
    db = get_db()
    llm = get_provider(db)

    # Resolve model name up front — _model may be None until first call.
    model_name: str = getattr(llm, '_model', None) or getattr(llm, 'model', None) or 'unknown'

    # ═══════════════════════════════════════════════════════════════════════════
    # Context Gathering (RIVA: Can I verify this intent?)
    # ═══════════════════════════════════════════════════════════════════════════
    context_string = ""
    try:
        from .shell_context import get_context_for_proposal
        context = get_context_for_proposal(natural_language)

        if context.can_verify:
            context_string = f"\nSystem Context:\n{context.to_context_string()}\n"
    except Exception:
        pass  # Context gathering is optional - fail open

    # Build enriched prompt
    user_prompt = f"Input: {natural_language}"
    if context_string:
        user_prompt = f"{context_string}\n{user_prompt}"

    start = time.monotonic()

    # First attempt: conversational prompt
    try:
        response = llm.chat_text(
            system=CONVERSATIONAL_PROMPT,
            user=user_prompt,
            temperature=0.3,
        )

        message, command = extract_conversational_response(response)

        if message:
            # After LLM succeeds, try to resolve actual model name if still unknown.
            if model_name == 'unknown':
                model_name = getattr(llm, '_model', None) or 'unknown'

            elapsed_ms = int((time.monotonic() - start) * 1000)
            return message, command, model_name, elapsed_ms, 1

    except Exception:
        pass  # Fall through to constrained retry

    # Second attempt: constrained fallback prompt — use only when first attempt
    # completely failed (exception or empty response). Wraps result in a message.
    try:
        response = llm.chat_text(
            system="You are a shell command generator. Output only commands.",
            user=CONSTRAINED_FALLBACK_PROMPT.format(intent=natural_language),
            temperature=0.1,  # Even lower temperature for more deterministic output
        )

        # For constrained prompt, just take the first line
        text = response.strip().split("\n")[0].strip()
        text = text.strip("`").strip()

        if model_name == 'unknown':
            model_name = getattr(llm, '_model', None) or 'unknown'

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Check for explicit failure
        if text.upper() in ("NONE", "COMMAND: NONE"):
            return "I could not determine a command for that request.", None, model_name, elapsed_ms, 2

        # Strip COMMAND: prefix if present
        if text.upper().startswith("COMMAND:"):
            text = text.split(":", 1)[1].strip()

        # Validate
        if looks_like_command(text):
            is_safe, reason = is_safe_command(text)
            if not is_safe:
                return f"I found a command but it was blocked for safety: {reason}", None, model_name, elapsed_ms, 2
            return "Here is what I suggest:", text, model_name, elapsed_ms, 2

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return f"Error: {e}", None, model_name, elapsed_ms, 2

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return "I could not interpret that as a command.", None, model_name, elapsed_ms, 2


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
    return cmd or '', msg


def main() -> NoReturn:
    """Main entry point for shell propose CLI."""
    if len(sys.argv) < 2:
        print("Usage: python -m reos.shell_propose 'natural language request'", file=sys.stderr)
        sys.exit(1)

    # Join all arguments as the natural language input
    natural_language = ' '.join(sys.argv[1:])

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
