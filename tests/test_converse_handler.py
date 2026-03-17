"""Unit tests for reos/converse, reos/execute, and reos/converse/abort handlers.

All LLM calls are mocked so these tests run without Ollama.

Coverage map
────────────
handle_reos_converse:
    - Greeting             → inform
    - Safe diagnostic      → propose (mocked)
    - Vague input          → clarify
    - Dangerous intent     → refuse  (keyword classification)
    - Hard-blocked command → refuse  (is_safe_command gate)
    - Soft-risky command   → danger  (SOFT_RISKY_PATTERNS)
    - TTY-requiring cmd    → inform  (redirect to Terminal tab)
    - LLM exception        → inform  (graceful degradation)
    - No command proposed  → inform  (pure conversational)
    - With turn_history    → conversation_context injected (smoke)

handle_reos_execute:
    - Happy path           → success=True, stdout captured
    - Command timeout      → success=False, "timed out" in stderr
    - Safety re-check fail → success=False, blocked
    - Output truncation    → truncated=True

handle_reos_converse_abort:
    - Always returns {"aborted": True}
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from reos.rpc_handlers.converse import (
    _build_conversation_context,
    _classify_intent,
    _needs_tty,
    handle_reos_converse,
    handle_reos_converse_abort,
    handle_reos_execute,
)
from reos.shell_propose import ProposalTrace


# ── helpers ──────────────────────────────────────────────────────────────────


def _trace(message: str, command: str | None = None) -> ProposalTrace:
    """Minimal ProposalTrace for mocking propose_command_with_trace."""
    return ProposalTrace(
        message=message,
        command=command,
        model_name="test-model",
        latency_ms=50,
        attempt_count=1,
    )


def _converse(natural_language: str, *, turn_history: list | None = None) -> dict:
    return handle_reos_converse(
        None,
        natural_language=natural_language,
        conversation_id="test-conv-id",
        turn_history=turn_history or [],
        system_context={},
    )


# ── _classify_intent unit tests ───────────────────────────────────────────────


class TestClassifyIntent:
    def test_greeting(self):
        r = _classify_intent("hello", [])
        assert r["intent"] == "greeting"
        assert r["confident"] is True

    def test_greeting_prefix(self):
        r = _classify_intent("hi there", [])
        assert r["intent"] == "greeting"

    def test_dangerous(self):
        r = _classify_intent("wipe everything", [])
        assert r["intent"] == "dangerous"
        assert r["confident"] is True

    def test_dangerous_kill_all(self):
        r = _classify_intent("kill all processes", [])
        assert r["intent"] == "dangerous"

    def test_vague(self):
        r = _classify_intent("fix it", [])
        assert r["intent"] == "unclear"
        assert r["confident"] is True

    def test_diagnostic(self):
        r = _classify_intent("show disk usage", [])
        assert r["intent"] == "diagnostic"

    def test_default_execute(self):
        r = _classify_intent("install nginx", [])
        assert r["intent"] == "execute"


# ── _needs_tty unit tests ──────────────────────────────────────────────────────


class TestNeedsTTY:
    def test_vim(self):
        assert _needs_tty("vim /etc/hosts") is True

    def test_htop(self):
        assert _needs_tty("htop") is True

    def test_sudo_vim(self):
        assert _needs_tty("sudo vim /etc/hosts") is True

    def test_sudo_safe(self):
        # sudo with a non-tty argument is fine
        assert _needs_tty("sudo systemctl status nginx") is False

    def test_ls_not_tty(self):
        assert _needs_tty("ls -la /home") is False

    def test_empty(self):
        assert _needs_tty("") is False


# ── _build_conversation_context unit tests ─────────────────────────────────────


class TestBuildConversationContext:
    def test_empty_history(self):
        assert _build_conversation_context([]) == ""

    def test_single_user_turn(self):
        history = [{"role": "user", "content": "show memory usage"}]
        ctx = _build_conversation_context(history)
        assert "User: show memory usage" in ctx

    def test_assistant_turn_label(self):
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        ctx = _build_conversation_context(history)
        assert "Assistant: Hi!" in ctx

    def test_history_cap(self):
        # 12 turns (0-11) — last 8 are turns 4-11; turns 0-3 are pruned
        history = [{"role": "user", "content": f"turn {i}"} for i in range(12)]
        ctx = _build_conversation_context(history)
        assert "turn 0" not in ctx   # earliest turns pruned
        assert "turn 11" in ctx

    def test_empty_content_skipped(self):
        history = [{"role": "user", "content": ""}]
        assert _build_conversation_context(history) == ""


# ── handle_reos_converse tests ─────────────────────────────────────────────────


class TestHandleReosConverse:
    def test_greeting_returns_inform(self):
        r = _converse("hello")
        assert r["turn_type"] == "inform"
        assert r["command"] is None
        assert "ReOS" in r["message"]

    def test_dangerous_returns_refuse(self):
        r = _converse("wipe everything")
        assert r["turn_type"] == "refuse"
        assert r["is_risky"] is True

    def test_vague_returns_clarify(self):
        r = _converse("fix it")
        assert r["turn_type"] == "clarify"
        assert r["command"] is None

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_safe_command_returns_propose(self, mock_propose):
        mock_propose.return_value = _trace("Here is disk usage.", "df -h")
        r = _converse("show disk usage")
        assert r["turn_type"] == "propose"
        assert r["command"] == "df -h"
        assert r["is_risky"] is False

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_soft_risky_command_returns_danger(self, mock_propose):
        mock_propose.return_value = _trace(
            "This will stop the service.", "sudo systemctl stop nginx"
        )
        r = _converse("stop nginx")
        assert r["turn_type"] == "danger"
        assert r["is_risky"] is True
        assert r["command"] == "sudo systemctl stop nginx"

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_hard_blocked_command_returns_refuse(self, mock_propose):
        # LLM proposes a hard-blocked command — is_safe_command() gates it.
        # Use a non-dangerous NL phrase so classification reaches the LLM path.
        mock_propose.return_value = _trace("Cleaning disk", "rm -rf /")
        r = _converse("clean up disk space")
        assert r["turn_type"] == "refuse"
        assert r["command"] is None
        assert r["is_risky"] is True

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_tty_command_returns_inform(self, mock_propose):
        mock_propose.return_value = _trace("Use htop for interactive view.", "htop")
        r = _converse("show processes interactively")
        assert r["turn_type"] == "inform"
        assert r["command"] is None
        assert "Terminal tab" in r["message"]

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_no_command_returns_inform(self, mock_propose):
        mock_propose.return_value = _trace(
            "The kernel is the core of the operating system.", None
        )
        r = _converse("what is the linux kernel")
        assert r["turn_type"] == "inform"
        assert r["command"] is None

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_llm_exception_returns_inform(self, mock_propose):
        mock_propose.side_effect = RuntimeError("Ollama unavailable")
        r = _converse("check disk space")
        assert r["turn_type"] == "inform"
        assert "error" in r["message"].lower()

    @patch("reos.rpc_handlers.converse.propose_command_with_trace")
    def test_turn_history_passed_as_context(self, mock_propose):
        """Conversation context built from turn_history is forwarded to the LLM."""
        mock_propose.return_value = _trace("Here you go.", "free -h")
        history = [
            {"role": "user", "content": "check memory"},
            {"role": "assistant", "content": "Use free -h for a summary."},
        ]
        _converse("show it again", turn_history=history)
        call_kwargs = mock_propose.call_args
        # The second positional/keyword argument should be conversation_context
        ctx = call_kwargs[1].get("conversation_context", "")
        assert "check memory" in ctx

    def test_result_always_has_operation_id(self):
        r = _converse("hello")
        assert isinstance(r["operation_id"], str)
        assert len(r["operation_id"]) > 0

    def test_result_always_has_latency_ms(self):
        r = _converse("hello")
        assert isinstance(r["latency_ms"], int)
        assert r["latency_ms"] >= 0


# ── handle_reos_execute tests ──────────────────────────────────────────────────


class TestHandleReosExecute:
    def test_happy_path_echo(self):
        r = handle_reos_execute(
            None,
            operation_id="op-1",
            command="echo hello",
            conversation_id="conv-1",
        )
        assert r["success"] is True
        assert r["exit_code"] == 0
        assert "hello" in r["stdout"]
        assert r["truncated"] is False

    def test_nonzero_exit_code(self):
        r = handle_reos_execute(
            None,
            operation_id="op-2",
            command="false",  # always exits 1
            conversation_id="conv-1",
        )
        assert r["success"] is False
        assert r["exit_code"] == 1

    def test_stderr_captured(self):
        r = handle_reos_execute(
            None,
            operation_id="op-3",
            command="echo error-text >&2",
            conversation_id="conv-1",
        )
        assert "error-text" in r["stderr"]

    def test_safety_recheck_blocks_dangerous_command(self):
        """Even if frontend sends a dangerous command, the re-check blocks it."""
        r = handle_reos_execute(
            None,
            operation_id="op-4",
            command="rm -rf /",
            conversation_id="conv-1",
        )
        assert r["success"] is False
        assert r["exit_code"] is None
        assert "Blocked" in r["stderr"]

    @patch("reos.rpc_handlers.converse.subprocess.run")
    def test_timeout_returns_failure(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=30)
        r = handle_reos_execute(
            None,
            operation_id="op-5",
            command="sleep 999",
            conversation_id="conv-1",
        )
        assert r["success"] is False
        assert "timed out" in r["stderr"].lower()

    @patch("reos.rpc_handlers.converse.subprocess.run")
    def test_stdout_truncated_at_50kb(self, mock_run):
        big_output = "x" * (60 * 1024)  # 60 KB > 50 KB cap
        mock_run.return_value = MagicMock(
            returncode=0, stdout=big_output, stderr=""
        )
        r = handle_reos_execute(
            None,
            operation_id="op-6",
            command="cat big_file",
            conversation_id="conv-1",
        )
        assert r["truncated"] is True
        assert len(r["stdout"].encode()) <= 50 * 1024 + 100  # small tolerance


# ── handle_reos_converse_abort tests ──────────────────────────────────────────


class TestHandleReosConverseAbort:
    def test_returns_aborted_true(self):
        r = handle_reos_converse_abort(None, operation_id="op-abort-1")
        assert r == {"aborted": True}

    def test_empty_operation_id_still_works(self):
        r = handle_reos_converse_abort(None, operation_id="")
        assert r["aborted"] is True
