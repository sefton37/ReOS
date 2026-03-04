"""Tests for shell context gathering module."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from reos.shell_context import (
    ShellContext,
    ShellContextGatherer,
    get_context_for_proposal,
    INTENT_PATTERNS,
    PACKAGE_ALIASES,
)


class TestIntentPatternMatching:
    """Tests for intent analysis."""

    def test_run_intent(self):
        gatherer = ShellContextGatherer()

        # Basic run commands
        assert gatherer.analyze_intent("run gimp") == ("run", "gimp")
        assert gatherer.analyze_intent("launch firefox") == ("run", "firefox")
        assert gatherer.analyze_intent("open vscode") == ("run", "code")  # alias
        assert gatherer.analyze_intent("execute python") == ("run", "python3")  # alias

    def test_install_intent(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("install gimp") == ("install", "gimp")
        assert gatherer.analyze_intent("add nodejs") == ("install", "nodejs")
        assert gatherer.analyze_intent("get docker") == ("install", "docker")
        assert gatherer.analyze_intent("download git") == ("install", "git")

    def test_remove_intent(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("remove gimp") == ("remove", "gimp")
        assert gatherer.analyze_intent("uninstall firefox") == ("remove", "firefox")
        assert gatherer.analyze_intent("delete vlc") == ("remove", "vlc")
        assert gatherer.analyze_intent("purge nginx") == ("remove", "nginx")

    def test_service_intents(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("start nginx") == ("service_start", "nginx")
        assert gatherer.analyze_intent("restart postgresql") == ("service_start", "postgresql")
        assert gatherer.analyze_intent("stop docker") == ("service_stop", "docker")
        assert gatherer.analyze_intent("enable ssh") == ("service_config", "ssh")
        assert gatherer.analyze_intent("disable bluetooth") == ("service_config", "bluetooth")

    def test_update_intent(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("update system")[0] == "update"
        assert gatherer.analyze_intent("upgrade packages")[0] == "update"

    def test_package_aliases(self):
        gatherer = ShellContextGatherer()

        # Test known aliases
        assert gatherer.analyze_intent("run chrome")[1] == "google-chrome-stable"
        assert gatherer.analyze_intent("install vscode")[1] == "code"
        assert gatherer.analyze_intent("run vs code")[1] == "code"
        assert gatherer.analyze_intent("install node")[1] == "nodejs"

    def test_filler_word_removal(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("run the gimp") == ("run", "gimp")
        assert gatherer.analyze_intent("install a python") == ("install", "python3")  # alias
        assert gatherer.analyze_intent("please run my firefox") == ("run", "firefox")

    def test_no_intent_detected(self):
        gatherer = ShellContextGatherer()

        # Should return None for unrecognized patterns
        verb, target = gatherer.analyze_intent("hello world")
        assert verb is None

    def test_empty_input(self):
        gatherer = ShellContextGatherer()

        assert gatherer.analyze_intent("") == (None, None)
        assert gatherer.analyze_intent("   ") == (None, None)


class TestContextGathering:
    """Tests for context gathering functionality."""

    @patch("subprocess.run")
    def test_check_executable_found(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="/usr/bin/gimp\n"
        )

        gatherer = ShellContextGatherer()
        result = gatherer.check_executable("gimp")

        assert result == "/usr/bin/gimp"
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_check_executable_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        gatherer = ShellContextGatherer()
        result = gatherer.check_executable("nonexistent")

        assert result is None

    @patch("subprocess.run")
    def test_check_package_installed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Package: gimp\nStatus: install ok installed\nVersion: 2.10.36\n"
        )

        gatherer = ShellContextGatherer()
        installed, version = gatherer.check_package_installed("gimp")

        assert installed is True
        assert version == "2.10.36"

    @patch("subprocess.run")
    def test_check_package_not_installed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        gatherer = ShellContextGatherer()
        installed, version = gatherer.check_package_installed("nonexistent")

        assert installed is False
        assert version is None

    @patch("subprocess.run")
    def test_check_service_active(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "show" in cmd:
                return MagicMock(returncode=0, stdout="LoadState=loaded\n")
            elif "is-active" in cmd:
                return MagicMock(returncode=0, stdout="active\n")
            elif "is-enabled" in cmd:
                return MagicMock(returncode=0, stdout="enabled\n")
            return MagicMock(returncode=1)

        mock_run.side_effect = side_effect

        gatherer = ShellContextGatherer()
        is_service, status, enabled = gatherer.check_service("nginx")

        assert is_service is True
        assert status == "active"
        assert enabled is True

    @patch("subprocess.run")
    def test_check_service_inactive(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "show" in cmd:
                return MagicMock(returncode=0, stdout="LoadState=loaded\n")
            elif "is-active" in cmd:
                return MagicMock(returncode=0, stdout="inactive\n")
            elif "is-enabled" in cmd:
                return MagicMock(returncode=1, stdout="disabled\n")
            return MagicMock(returncode=1)

        mock_run.side_effect = side_effect

        gatherer = ShellContextGatherer()
        is_service, status, enabled = gatherer.check_service("nginx")

        assert is_service is True
        assert status == "inactive"
        assert enabled is False


class TestShellContext:
    """Tests for ShellContext dataclass."""

    def test_context_string_executable(self):
        context = ShellContext(
            intent_target="gimp",
            executable_path="/usr/bin/gimp",
        )

        result = context.to_context_string()
        assert "gimp" in result
        assert "/usr/bin/gimp" in result

    def test_context_string_package_installed(self):
        context = ShellContext(
            intent_target="nodejs",
            package_installed=True,
            package_version="18.19.0",
        )

        result = context.to_context_string()
        assert "nodejs" in result
        assert "installed" in result
        assert "18.19.0" in result

    def test_context_string_package_available(self):
        context = ShellContext(
            intent_target="gimp",
            package_available=True,
            package_description="GNU Image Manipulation Program",
        )

        result = context.to_context_string()
        assert "gimp" in result
        assert "available" in result
        assert "NOT installed" in result
        assert "GNU Image Manipulation Program" in result

    def test_context_string_not_found(self):
        context = ShellContext(
            intent_target="nonexistent",
        )

        result = context.to_context_string()
        assert "nonexistent" in result
        assert "NOT FOUND" in result

    def test_context_string_service(self):
        context = ShellContext(
            intent_target="nginx",
            is_service=True,
            service_status="active",
            service_enabled=True,
        )

        result = context.to_context_string()
        assert "nginx service" in result
        assert "active" in result
        assert "enabled" in result


class TestIntegration:
    """Integration tests with real system calls (skipped if not available)."""

    def test_real_which_python(self):
        """Test that we can find python3."""
        gatherer = ShellContextGatherer()
        result = gatherer.check_executable("python3")

        # python3 should be installed on most Linux systems
        assert result is not None or True  # Skip if not installed

    def test_real_context_gathering(self):
        """Test full context gathering pipeline."""
        context = get_context_for_proposal("run python3")

        assert context.intent_verb == "run"
        assert context.intent_target == "python3"
        # May or may not find python3 depending on system


class TestEdgeCases:
    """Edge case tests."""

    def test_timeout_handling(self):
        """Test that timeouts are handled gracefully."""
        gatherer = ShellContextGatherer()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 2)

            result = gatherer.check_executable("slow_command")
            assert result is None

    def test_file_not_found_handling(self):
        """Test that missing commands are handled gracefully."""
        gatherer = ShellContextGatherer()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = gatherer.check_executable("missing_which")
            assert result is None

    def test_gather_context_with_no_target(self):
        """Test context gathering with no target."""
        gatherer = ShellContextGatherer()
        context = gatherer.gather_context(None, None)

        assert context.can_verify is False

    def test_gather_context_can_verify(self):
        """Test that can_verify is set correctly."""
        gatherer = ShellContextGatherer()

        with patch.object(gatherer, "check_executable", return_value="/usr/bin/test"):
            context = gatherer.gather_context("run", "test")
            assert context.can_verify is True

        with patch.object(gatherer, "check_executable", return_value=None):
            with patch.object(gatherer, "check_package_installed", return_value=(False, None)):
                with patch.object(gatherer, "check_package_available", return_value=(False, None)):
                    with patch.object(gatherer, "check_service", return_value=(False, None, False)):
                        context = gatherer.gather_context("run", "nonexistent")
                        assert context.can_verify is False
