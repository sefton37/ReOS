"""ReOS Shell CLI - Natural language terminal integration.

This module provides a CLI interface for handling natural language prompts
directly from the terminal, enabling shell integration via command_not_found_handle.

Usage:
    python -m reos.shell_cli "what files are in my home directory"
    python -m reos.shell_cli --execute "list all python files"

Architecture:
    When running from the terminal, commands should execute with full terminal
    access (stdin/stdout/stderr connected to the terminal). This allows users
    to interact with commands normally (e.g., respond to y/n prompts).

    We set REOS_TERMINAL_MODE=1 to signal this to downstream code.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from .agent import ChatAgent, ChatResponse
from .db import get_db
from .logging_setup import configure_logging

# Signal that we're running in terminal mode - commands should have terminal access
os.environ["REOS_TERMINAL_MODE"] = "1"

# File to persist conversation ID between shell invocations
CONVERSATION_FILE = Path.home() / ".reos_conversation"


def get_conversation_id() -> str | None:
    """Get the current conversation ID from file."""
    try:
        if CONVERSATION_FILE.exists():
            content = CONVERSATION_FILE.read_text().strip()
            if content:
                return content
    except Exception:
        pass
    return None


def save_conversation_id(conversation_id: str) -> None:
    """Save conversation ID to file for context continuity."""
    try:
        CONVERSATION_FILE.write_text(conversation_id)
    except Exception:
        pass  # Best effort


def clear_conversation() -> None:
    """Clear the current conversation to start fresh."""
    try:
        if CONVERSATION_FILE.exists():
            CONVERSATION_FILE.unlink()
    except Exception:
        pass


def read_user_input(prompt_text: str = "") -> str:
    """Read input from user, trying /dev/tty if stdin is unavailable.

    Args:
        prompt_text: Optional prompt to display (not used if reading from /dev/tty).

    Returns:
        User input string, stripped.
    """
    if sys.stdin.isatty():
        # stdin is connected to terminal, use normal input
        if prompt_text:
            return input(prompt_text).strip()
        return input().strip()

    # stdin is not a tty (piped/redirected), try /dev/tty
    try:
        with open("/dev/tty", "r") as tty:
            return tty.readline().strip()
    except OSError:
        # Can't open /dev/tty, fall back to stdin
        if prompt_text:
            return input(prompt_text).strip()
        return input().strip()


def colorize(text: str, color: str) -> str:
    """Apply ANSI color codes if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text

    colors = {
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "reset": "\033[0m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "white": "\033[97m",
        "bg_dim": "\033[48;5;236m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def print_header() -> None:
    """Print a minimal ReOS header."""
    header = colorize("🐧 ReOS", "cyan") + colorize(" (natural language mode)", "dim")
    print(header, file=sys.stderr)


def print_thinking() -> None:
    """Show thinking indicator."""
    print(colorize("  🤔 Thinking...", "dim"), end="\r", file=sys.stderr)


def clear_thinking() -> None:
    """Clear the thinking indicator."""
    print(" " * 30, end="\r", file=sys.stderr)


def print_processing_summary(response: ChatResponse, *, quiet: bool = False, show_approval_hint: bool = True) -> None:
    """Print a summary of what ReOS did during processing.

    This shows tool calls, pending approvals, and other metadata
    in a visually distinct format from the response.
    """
    if quiet:
        return

    has_output = False

    # Show tool calls
    if response.tool_calls:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize("🔧 Actions taken:", "cyan"), file=sys.stderr)

        for tc in response.tool_calls:
            name = tc.get("name", "unknown")
            ok = tc.get("ok", False)

            # Format tool name nicely with category emoji
            display_name = name.replace("linux_", "").replace("reos_", "").replace("_", " ")

            # Pick emoji based on tool category
            if "docker" in name or "container" in name:
                tool_emoji = "🐳"
            elif "service" in name:
                tool_emoji = "🔄"
            elif "package" in name:
                tool_emoji = "📦"
            elif "system_info" in name:
                tool_emoji = "📊"
            elif "run_command" in name:
                tool_emoji = "⚡"
            elif "git" in name:
                tool_emoji = "📂"
            elif "file" in name or "log" in name:
                tool_emoji = "📄"
            elif "network" in name:
                tool_emoji = "🌐"
            elif "process" in name:
                tool_emoji = "⚙️"
            else:
                tool_emoji = "🔹"

            if ok:
                status = colorize("✅", "green")
                # Show brief result preview for some tools
                result = tc.get("result", {})
                preview = ""
                if isinstance(result, dict):
                    if "stdout" in result and result["stdout"]:
                        lines = result["stdout"].strip().split("\n")
                        preview = f" → {len(lines)} lines"
                    elif "hostname" in result:
                        preview = f" → {result.get('hostname', '')}"
                    elif "status" in result:
                        preview = f" → {result.get('status', '')}"
            else:
                status = colorize("❌", "red")
                error = tc.get("error", {})
                preview = f" → {error.get('message', 'failed')}" if error else ""

            print(f"    {status} {tool_emoji} {colorize(display_name, 'cyan')}{colorize(preview, 'dim')}", file=sys.stderr)

        has_output = True

    # Show pending approval (hint only - actual prompt is handled by interactive loop)
    if response.pending_approval_id and show_approval_hint:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize("⚠️  Plan requires approval", "yellow"), file=sys.stderr)
        has_output = True

    # Show conversation tracking
    if response.conversation_id and not quiet:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize(f"📝 Conversation: {response.conversation_id}", "dim"), file=sys.stderr)
        has_output = True

    # Separator before response
    if has_output:
        print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(file=sys.stderr)


def handle_prompt(
    prompt: str,
    *,
    verbose: bool = False,
    conversation_id: str | None = None,
    agent: ChatAgent | None = None,
) -> ChatResponse:
    """Process a natural language prompt through ReOS.

    Args:
        prompt: The natural language query from the user.
        verbose: If True, show detailed progress.
        conversation_id: Optional conversation ID to continue.
        agent: Optional ChatAgent instance to reuse.

    Returns:
        ChatResponse with answer and metadata.
    """
    if agent is None:
        db = get_db()
        agent = ChatAgent(db=db)

    if verbose:
        print_thinking()

    try:
        response = agent.respond(prompt, conversation_id=conversation_id)
    finally:
        if verbose:
            clear_thinking()

    return response


def prompt_for_approval() -> str | None:
    """Prompt user for approval inline.

    Returns:
        'yes', 'no', or None if interrupted/EOF
    """
    print(file=sys.stderr)
    print(colorize("─" * 50, "dim"), file=sys.stderr)
    print(
        colorize("🔐 ", "yellow") +
        colorize("Proceed with this plan? ", "bold") +
        colorize("[y/n/q]: ", "dim"),
        end="",
        file=sys.stderr,
    )
    sys.stderr.flush()

    try:
        response = read_user_input().lower()

        if response in ("y", "yes", "ok", "proceed", "go", "do it"):
            return "yes"
        elif response in ("n", "no", "cancel", "abort", "stop"):
            return "no"
        elif response in ("q", "quit", "exit"):
            return None
        else:
            # Treat unknown as rejection for safety
            print(colorize("  ℹ️  Unknown response, treating as 'no'", "dim"), file=sys.stderr)
            return "no"
    except (EOFError, KeyboardInterrupt):
        return None


def run_interactive_session(
    initial_prompt: str,
    *,
    verbose: bool = False,
    quiet: bool = False,
    conversation_id: str | None = None,
) -> int:
    """Run an interactive session with approval loop.

    Handles the full flow:
    1. Send initial prompt
    2. If plan needs approval, prompt user inline
    3. On approval, execute and show results
    4. Loop until no more pending approvals

    Args:
        initial_prompt: The user's initial request
        verbose: Show detailed progress
        quiet: Suppress headers
        conversation_id: Optional conversation to continue

    Returns:
        Exit code (0 for success)
    """
    db = get_db()
    agent = ChatAgent(db=db)

    prompt = initial_prompt
    current_conversation_id = conversation_id

    while True:
        # Process the prompt
        result = handle_prompt(
            prompt,
            verbose=verbose,
            conversation_id=current_conversation_id,
            agent=agent,
        )

        # Update conversation ID
        current_conversation_id = result.conversation_id
        save_conversation_id(current_conversation_id)

        # Show processing summary (without approval hint since we handle it below)
        print_processing_summary(result, quiet=quiet, show_approval_hint=False)

        # Print the response
        if not quiet:
            print(colorize("💬 ReOS:", "cyan"), file=sys.stderr)
            print(file=sys.stderr)
        print(result.answer)

        # Check if we need approval
        if result.pending_approval_id:
            approval = prompt_for_approval()

            if approval is None:
                # User quit
                print(colorize("\n  ℹ️  Session ended. Plan not executed.", "dim"), file=sys.stderr)
                return 0
            elif approval == "yes":
                # Continue the conversation with approval
                prompt = "yes"
                if not quiet:
                    print(file=sys.stderr)
                    print(colorize("  ⏳ Executing plan...", "cyan"), file=sys.stderr)
                continue
            else:
                # Rejected
                prompt = "no"
                if not quiet:
                    print(file=sys.stderr)
                    print(colorize("  ℹ️  Plan cancelled.", "dim"), file=sys.stderr)
                # Send rejection to agent so it clears state
                result = handle_prompt(
                    prompt,
                    verbose=False,
                    conversation_id=current_conversation_id,
                    agent=agent,
                )
                return 0
        else:
            # No pending approval, we're done
            return 0


def main() -> NoReturn:
    """Main entry point for shell CLI."""
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="reos-shell",
        description="ReOS natural language terminal integration - talk to your Linux system",
        epilog="""
Examples:
  reos-shell "what files are in this directory"
  reos-shell "show me running processes using lots of memory"
  reos-shell "install htop"
  reos-shell -q "disk usage"      # Quiet mode, just output
  reos-shell -n "fresh question"  # Start new conversation

Shell Integration:
  Add to ~/.bashrc for command_not_found handling:
    command_not_found_handle() {
        reos-shell --command-not-found "$*"
    }

  This lets you type natural language directly:
    $ what files are here
    ReOS: 'what files are here' is not a command.
          Treat as natural language? [Y/n]
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Natural language prompt (e.g., 'list all python files')",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress header and progress indicators (output only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed processing information",
    )
    parser.add_argument(
        "--new", "-n",
        action="store_true",
        help="Start a new conversation (clear previous context)",
    )
    parser.add_argument(
        "--command-not-found",
        action="store_true",
        help="Mode for command_not_found_handle (confirms before processing)",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version="%(prog)s 0.0.0a0 (Talking Rock)",
    )

    args = parser.parse_args()

    # Handle --new flag to start fresh conversation
    if args.new:
        clear_conversation()

    # Join prompt words
    prompt = " ".join(args.prompt).strip()

    if not prompt:
        # Read from stdin if no prompt provided
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()

        if not prompt:
            print("Usage: reos-shell 'your natural language prompt'", file=sys.stderr)
            sys.exit(1)

    # In command-not-found mode, confirm before processing
    if args.command_not_found:
        print(colorize("ReOS:", "cyan"), f"'{prompt}' is not a command.", file=sys.stderr)
        print(colorize("      ", "cyan"), "Treat as natural language? [Y/n] ", end="", file=sys.stderr)
        sys.stderr.flush()

        try:
            response = read_user_input().lower()
            if response and response not in ("y", "yes"):
                sys.exit(127)  # Standard exit code for command not found
        except (EOFError, KeyboardInterrupt):
            sys.exit(127)

    if not args.quiet:
        print_header()

    try:
        # Get conversation ID for context continuity
        conversation_id = get_conversation_id()

        # Run interactive session with approval loop
        exit_code = run_interactive_session(
            prompt,
            verbose=not args.quiet,
            quiet=args.quiet,
            conversation_id=conversation_id,
        )
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(colorize(f"Error: {e}", "red"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
