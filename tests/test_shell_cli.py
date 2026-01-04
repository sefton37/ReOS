"""Tests for ReOS shell CLI integration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reos.agent import ChatResponse


def _make_chat_response(answer: str, conversation_id: str = "test-conv-123") -> ChatResponse:
    """Create a ChatResponse for testing."""
    return ChatResponse(
        answer=answer,
        conversation_id=conversation_id,
        message_id="test-msg-123",
        message_type="text",
        tool_calls=[],
        pending_approval_id=None,
    )


class TestShellCliModule:
    """Tests for the shell_cli module."""

    def test_module_imports(self) -> None:
        """Shell CLI module should import successfully."""
        from reos import shell_cli

        assert hasattr(shell_cli, "main")
        assert hasattr(shell_cli, "handle_prompt")
        assert hasattr(shell_cli, "colorize")

    def test_colorize_with_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """colorize should add ANSI codes when stdout is a TTY."""
        from reos.shell_cli import colorize

        # Mock isatty to return True
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        result = colorize("test", "cyan")
        assert "\033[36m" in result  # Cyan code
        assert "\033[0m" in result  # Reset code
        assert "test" in result

    def test_colorize_without_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """colorize should return plain text when stdout is not a TTY."""
        from reos.shell_cli import colorize

        # Mock isatty to return False
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

        result = colorize("test", "cyan")
        assert result == "test"
        assert "\033[" not in result

    def test_colorize_unknown_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """colorize should handle unknown colors gracefully."""
        from reos.shell_cli import colorize

        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        result = colorize("test", "unknown_color")
        assert "test" in result
        assert "\033[0m" in result  # Should still have reset


class TestHandlePrompt:
    """Tests for the handle_prompt function."""

    def test_handle_prompt_returns_response(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """handle_prompt should return agent response."""
        from reos.shell_cli import handle_prompt

        # Mock the ChatAgent
        mock_agent = MagicMock()
        mock_agent.respond.return_value = _make_chat_response("Test response from agent")

        with patch("reos.shell_cli.ChatAgent", return_value=mock_agent):
            result = handle_prompt("test query")

        assert result.answer == "Test response from agent"
        mock_agent.respond.assert_called_once_with("test query", conversation_id=None)

    def test_handle_prompt_passes_db(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """handle_prompt should pass database to ChatAgent."""
        from reos.db import get_db
        from reos.shell_cli import handle_prompt

        captured_db = None

        def capture_agent(*, db, **kwargs):  # noqa: ANN003, ANN001
            nonlocal captured_db
            captured_db = db
            mock = MagicMock()
            mock.respond.return_value = _make_chat_response("ok")
            return mock

        with patch("reos.shell_cli.ChatAgent", side_effect=capture_agent):
            handle_prompt("test")

        assert captured_db is not None
        assert captured_db == get_db()


class TestMainEntryPoint:
    """Tests for the main() entry point."""

    def test_main_with_no_args_prints_usage(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """main() with no args should print usage."""
        from reos.shell_cli import main

        monkeypatch.setattr(sys, "argv", ["reos-shell"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.err

    def test_main_with_prompt_calls_handler(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """main() with prompt should call handle_prompt."""
        from reos.shell_cli import main

        monkeypatch.setattr(sys, "argv", ["reos-shell", "test", "query"])

        mock_agent = MagicMock()
        mock_agent.respond.return_value = _make_chat_response("Agent response")

        with patch("reos.shell_cli.ChatAgent", return_value=mock_agent):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Agent response" in captured.out

    def test_main_with_quiet_flag(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """main() with --quiet should suppress header."""
        from reos.shell_cli import main

        monkeypatch.setattr(sys, "argv", ["reos-shell", "--quiet", "test"])

        mock_agent = MagicMock()
        mock_agent.respond.return_value = _make_chat_response("Response")

        with patch("reos.shell_cli.ChatAgent", return_value=mock_agent):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "ReOS" not in captured.err  # Header should not appear


class TestCommandNotFoundMode:
    """Tests for command-not-found integration mode."""

    def test_command_not_found_mode_prompts_user(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--command-not-found should prompt for confirmation."""
        from reos.shell_cli import main

        monkeypatch.setattr(sys, "argv", ["reos-shell", "--command-not-found", "test"])

        # Simulate user typing "n" to decline
        monkeypatch.setattr("builtins.input", lambda: "n")

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Exit code 127 = command not found
        assert exc_info.value.code == 127
        captured = capsys.readouterr()
        assert "is not a command" in captured.err

    def test_command_not_found_mode_accepts_yes(
        self,
        isolated_db_singleton,  # noqa: ANN001
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--command-not-found with 'y' should process prompt."""
        from reos.shell_cli import main

        monkeypatch.setattr(sys, "argv", ["reos-shell", "--command-not-found", "test", "query"])

        # Simulate user typing "y"
        monkeypatch.setattr("builtins.input", lambda: "y")

        mock_agent = MagicMock()
        mock_agent.respond.return_value = _make_chat_response("Processed")

        with patch("reos.shell_cli.ChatAgent", return_value=mock_agent):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Processed" in captured.out


class TestShellIntegrationScript:
    """Tests for the shell integration bash script."""

    def test_integration_script_exists(self) -> None:
        """Shell integration script should exist."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "reos-shell-integration.sh"
        assert script_path.exists(), f"Missing: {script_path}"

    def test_installer_script_exists(self) -> None:
        """Shell integration installer should exist."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "install-shell-integration.sh"
        assert script_path.exists(), f"Missing: {script_path}"

    def test_integration_script_is_valid_bash(self) -> None:
        """Shell integration script should be valid bash syntax."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "reos-shell-integration.sh"

        # Check syntax with bash -n
        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Bash syntax error: {result.stderr}"

    def test_installer_script_is_valid_bash(self) -> None:
        """Installer script should be valid bash syntax."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "install-shell-integration.sh"

        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Bash syntax error: {result.stderr}"

    def test_integration_script_defines_handler(self) -> None:
        """Shell integration should define command_not_found_handle."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "reos-shell-integration.sh"

        content = script_path.read_text()
        assert "command_not_found_handle()" in content
        assert "reos()" in content  # Direct invocation function


class TestReosLauncherPromptMode:
    """Tests for the reos launcher --prompt mode."""

    def test_reos_launcher_has_prompt_mode(self) -> None:
        """reos launcher should support --prompt mode."""
        repo_root = Path(__file__).parent.parent
        launcher_path = repo_root / "reos"

        content = launcher_path.read_text()
        assert "--prompt" in content
        assert "-p" in content
        assert "reos.shell_cli" in content

    def test_reos_launcher_has_shell_mode(self) -> None:
        """reos launcher should support --shell mode."""
        repo_root = Path(__file__).parent.parent
        launcher_path = repo_root / "reos"

        content = launcher_path.read_text()
        assert "--shell" in content
        assert "install-shell-integration.sh" in content

    def test_reos_help_mentions_shell_integration(self) -> None:
        """reos --help should mention shell integration."""
        repo_root = Path(__file__).parent.parent
        launcher_path = repo_root / "reos"

        content = launcher_path.read_text()
        assert "Shell Integration" in content
        assert "natural language" in content.lower()
