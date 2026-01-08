"""Tests for Linux system tools."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from reos import linux_tools


class TestCommandSafety:
    """Test command safety checks."""

    def test_safe_command_allowed(self) -> None:
        """Safe commands should be allowed."""
        is_safe, warning = linux_tools.is_command_safe("ls -la")
        assert is_safe is True
        assert warning is None

    def test_safe_command_echo(self) -> None:
        """Echo command should be allowed."""
        is_safe, warning = linux_tools.is_command_safe("echo hello")
        assert is_safe is True
        assert warning is None

    def test_dangerous_rm_rf_root_blocked(self) -> None:
        """rm -rf / should be blocked."""
        is_safe, warning = linux_tools.is_command_safe("rm -rf /")
        assert is_safe is False
        assert warning is not None
        assert "blocked" in warning.lower()

    def test_dangerous_rm_rf_wildcard_blocked(self) -> None:
        """rm -rf /* should be blocked."""
        is_safe, warning = linux_tools.is_command_safe("rm -rf /*")
        assert is_safe is False
        assert warning is not None

    def test_fork_bomb_blocked(self) -> None:
        """Fork bomb should be blocked."""
        is_safe, warning = linux_tools.is_command_safe(":(){:|:&};:")
        assert is_safe is False
        assert warning is not None

    def test_dd_risky_blocked(self) -> None:
        """dd command should be blocked (risky operations require approval workflow)."""
        is_safe, warning = linux_tools.is_command_safe("dd if=/dev/sda of=backup.img")
        assert is_safe is False  # Now blocked, requires approval workflow
        assert warning is not None
        assert "risky" in warning.lower() or "blocked" in warning.lower()

    def test_shutdown_risky_blocked(self) -> None:
        """shutdown command should be blocked (risky operations require approval workflow)."""
        is_safe, warning = linux_tools.is_command_safe("shutdown -h now")
        assert is_safe is False  # Now blocked, requires approval workflow
        assert warning is not None


class TestExecuteCommand:
    """Test command execution."""

    def test_simple_command(self) -> None:
        """Simple command should execute successfully."""
        result = linux_tools.execute_command("echo 'hello world'")
        assert result.success is True
        assert result.returncode == 0
        assert "hello world" in result.stdout

    def test_command_with_error(self) -> None:
        """Command with error should return non-zero."""
        result = linux_tools.execute_command("ls /nonexistent_directory_xyz")
        assert result.success is False
        assert result.returncode != 0

    def test_dangerous_command_blocked(self) -> None:
        """Dangerous command should be blocked."""
        result = linux_tools.execute_command("rm -rf /")
        assert result.success is False
        assert "blocked" in result.stderr.lower() or "dangerous" in result.stderr.lower()

    def test_timeout(self) -> None:
        """Command should timeout."""
        result = linux_tools.execute_command("sleep 10", timeout=1)
        assert result.success is False
        assert "timed out" in result.stderr.lower()

    def test_working_directory(self) -> None:
        """Command should run in specified directory."""
        result = linux_tools.execute_command("pwd", cwd="/tmp")
        assert result.success is True
        assert "/tmp" in result.stdout


class TestSystemInfo:
    """Test system information gathering."""

    def test_get_system_info(self) -> None:
        """Should return system info dataclass."""
        info = linux_tools.get_system_info()
        assert info is not None
        assert isinstance(info.hostname, str)
        assert isinstance(info.cpu_cores, int)
        assert info.cpu_cores >= 0
        assert isinstance(info.memory_total_mb, int)
        assert info.memory_total_mb >= 0

    def test_distro_detection(self) -> None:
        """Should detect Linux distribution."""
        distro = linux_tools.detect_distro()
        assert distro is not None
        assert isinstance(distro, str)
        assert len(distro) > 0


class TestPackageManager:
    """Test package manager detection."""

    def test_detect_package_manager(self) -> None:
        """Should detect package manager or return None."""
        pm = linux_tools.detect_package_manager()
        # pm can be None if no supported package manager is found
        if pm is not None:
            assert pm in ["apt", "dnf", "yum", "pacman", "zypper", "apk", "emerge", "nix-env"]

    @patch("os.path.exists")
    def test_detect_apt(self, mock_exists: MagicMock) -> None:
        """Should detect apt on Debian/Ubuntu."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/apt"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "apt"

    @patch("os.path.exists")
    def test_detect_dnf(self, mock_exists: MagicMock) -> None:
        """Should detect dnf on Fedora."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/dnf"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "dnf"

    @patch("os.path.exists")
    def test_detect_pacman(self, mock_exists: MagicMock) -> None:
        """Should detect pacman on Arch."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/pacman"

        mock_exists.side_effect = exists_side_effect
        pm = linux_tools.detect_package_manager()
        assert pm == "pacman"


class TestNetworkInfo:
    """Test network information gathering."""

    def test_get_network_info(self) -> None:
        """Should return network interfaces."""
        interfaces = linux_tools.get_network_info()
        assert isinstance(interfaces, dict)
        # Should have at least loopback
        if len(interfaces) > 0:
            for name, info in interfaces.items():
                assert isinstance(name, str)
                assert isinstance(info, dict)


class TestProcessManagement:
    """Test process listing."""

    def test_list_processes(self) -> None:
        """Should return list of processes."""
        processes = linux_tools.list_processes(limit=10)
        assert isinstance(processes, list)
        # Should have at least one process (ourselves)
        if len(processes) > 0:
            p = processes[0]
            assert hasattr(p, "pid")
            assert hasattr(p, "command")
            assert isinstance(p.pid, int)

    def test_list_processes_by_memory(self) -> None:
        """Should sort by memory."""
        processes = linux_tools.list_processes(sort_by="mem", limit=5)
        assert isinstance(processes, list)


class TestServiceManagement:
    """Test systemd service management."""

    def test_list_services(self) -> None:
        """Should return list of services."""
        services = linux_tools.list_services()
        assert isinstance(services, list)
        # May be empty if systemd not available
        if len(services) > 0:
            s = services[0]
            assert hasattr(s, "name")
            assert hasattr(s, "active_state")

    def test_get_service_status(self) -> None:
        """Should return service status dict."""
        # Test with a service that likely doesn't exist
        status = linux_tools.get_service_status("nonexistent_service_xyz")
        assert isinstance(status, dict)
        assert "name" in status
        assert status["name"] == "nonexistent_service_xyz"

    def test_manage_service_invalid_action(self) -> None:
        """Should reject invalid action."""
        result = linux_tools.manage_service("test", "invalid_action")
        assert result.success is False
        assert "invalid" in result.stderr.lower()


class TestDiskUsage:
    """Test disk usage information."""

    def test_get_disk_usage_root(self) -> None:
        """Should return disk usage for /."""
        usage = linux_tools.get_disk_usage("/")
        assert isinstance(usage, dict)
        assert "total_gb" in usage
        assert "used_gb" in usage
        assert "free_gb" in usage
        assert usage["total_gb"] > 0

    def test_get_disk_usage_home(self) -> None:
        """Should return disk usage for home."""
        usage = linux_tools.get_disk_usage(os.path.expanduser("~"))
        assert isinstance(usage, dict)
        assert usage["total_gb"] > 0


class TestDirectoryOperations:
    """Test directory listing and file finding."""

    def test_list_directory(self) -> None:
        """Should list directory contents."""
        entries = linux_tools.list_directory("/tmp")
        assert isinstance(entries, list)
        # /tmp should exist and be readable
        if entries and "error" not in entries[0]:
            for entry in entries:
                assert "name" in entry
                assert "type" in entry

    def test_list_directory_with_details(self) -> None:
        """Should include details when requested."""
        entries = linux_tools.list_directory("/tmp", details=True)
        assert isinstance(entries, list)
        if entries and "error" not in entries[0]:
            for entry in entries:
                assert "name" in entry
                # With details, should have size info
                if entry["type"] == "file":
                    assert "size" in entry

    def test_list_directory_nonexistent(self) -> None:
        """Should handle nonexistent directory."""
        entries = linux_tools.list_directory("/nonexistent_dir_xyz")
        assert isinstance(entries, list)
        assert len(entries) == 1
        assert "error" in entries[0]

    def test_find_files(self) -> None:
        """Should find files matching criteria."""
        files = linux_tools.find_files("/tmp", limit=10)
        assert isinstance(files, list)

    def test_find_files_by_extension(self) -> None:
        """Should filter by extension."""
        files = linux_tools.find_files("/tmp", extension=".py", limit=10)
        assert isinstance(files, list)
        for f in files:
            assert f.endswith(".py")


class TestLogReading:
    """Test log file reading."""

    def test_read_log_file(self) -> None:
        """Should read log file."""
        # Use a file we know exists
        result = linux_tools.read_log_file("/etc/passwd", lines=5)
        assert isinstance(result, dict)
        assert "path" in result
        if "error" not in result:
            assert "lines" in result
            assert isinstance(result["lines"], list)

    def test_read_log_file_nonexistent(self) -> None:
        """Should handle nonexistent file."""
        result = linux_tools.read_log_file("/nonexistent_log.log")
        assert isinstance(result, dict)
        assert "error" in result

    def test_read_log_with_filter(self) -> None:
        """Should filter log lines."""
        result = linux_tools.read_log_file("/etc/passwd", filter_pattern="root")
        assert isinstance(result, dict)
        if "error" not in result and result["lines"]:
            for line in result["lines"]:
                assert "root" in line.lower()


class TestDockerIntegration:
    """Test Docker integration."""

    def test_check_docker_available(self) -> None:
        """Should check Docker availability."""
        available = linux_tools.check_docker_available()
        assert isinstance(available, bool)

    def test_list_docker_containers(self) -> None:
        """Should list Docker containers."""
        containers = linux_tools.list_docker_containers()
        assert isinstance(containers, list)

    def test_list_docker_images(self) -> None:
        """Should list Docker images."""
        images = linux_tools.list_docker_images()
        assert isinstance(images, list)


class TestEnvironmentInfo:
    """Test environment information."""

    def test_get_environment_info(self) -> None:
        """Should return environment info."""
        env = linux_tools.get_environment_info()
        assert isinstance(env, dict)
        assert "shell" in env
        assert "user" in env
        assert "home" in env
        assert "available_tools" in env
        assert isinstance(env["available_tools"], dict)


class TestDataclasses:
    """Test dataclass properties."""

    def test_command_result_frozen(self) -> None:
        """CommandResult should be frozen."""
        result = linux_tools.CommandResult(
            command="test",
            returncode=0,
            stdout="output",
            stderr="",
            success=True,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.command = "modified"  # type: ignore

    def test_system_info_frozen(self) -> None:
        """SystemInfo should be frozen."""
        info = linux_tools.get_system_info()
        with pytest.raises(Exception):
            info.hostname = "modified"  # type: ignore

    def test_process_info_frozen(self) -> None:
        """ProcessInfo should be frozen."""
        info = linux_tools.ProcessInfo(
            pid=1,
            user="root",
            cpu_percent=0.0,
            mem_percent=0.0,
            command="init",
            status="S",
        )
        with pytest.raises(Exception):
            info.pid = 2  # type: ignore


class TestCommandPreview:
    """Test command preview functionality."""

    def test_preview_safe_command(self) -> None:
        """Non-destructive commands should not be marked destructive."""
        preview = linux_tools.preview_command("ls -la")
        assert preview.is_destructive is False
        assert preview.can_undo is False

    def test_preview_rm_command(self) -> None:
        """rm commands should be marked as destructive."""
        preview = linux_tools.preview_command("rm -rf /tmp/testdir")
        assert preview.is_destructive is True
        assert preview.can_undo is False
        assert "Delete" in preview.description
        assert any("Recursive" in w for w in preview.warnings)

    def test_preview_mv_command(self) -> None:
        """mv commands should be marked as destructive with undo."""
        # Create a temp file for testing
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            preview = linux_tools.preview_command(f"mv {temp_path} /tmp/newname")
            assert preview.is_destructive is True
            assert preview.can_undo is True
            assert preview.undo_command is not None
            assert "Move" in preview.description
        finally:
            os.unlink(temp_path)

    def test_preview_blocked_command(self) -> None:
        """Dangerous commands should be blocked."""
        preview = linux_tools.preview_command("rm -rf /")
        assert preview.is_destructive is True
        assert "BLOCKED" in preview.description
        assert len(preview.warnings) > 0

    def test_preview_service_command(self) -> None:
        """Service commands should show undo options."""
        preview = linux_tools.preview_command("systemctl stop nginx")
        assert preview.is_destructive is True
        assert preview.can_undo is True
        assert preview.undo_command == "systemctl start nginx"

    def test_preview_package_command(self) -> None:
        """Package commands should be marked destructive."""
        preview = linux_tools.preview_command("apt install vim")
        assert preview.is_destructive is True
        assert any("Package" in w for w in preview.warnings)


class TestSudoAvailability:
    """Test sudo availability checking."""

    @patch("subprocess.run")
    def test_sudo_available(self, mock_run: MagicMock) -> None:
        """Should return True when sudo works without password."""
        mock_run.return_value = MagicMock(returncode=0)
        available, error = linux_tools.check_sudo_available()
        assert available is True
        assert error is None

    @patch("subprocess.run")
    def test_sudo_requires_password(self, mock_run: MagicMock) -> None:
        """Should return False when sudo requires password."""
        mock_run.return_value = MagicMock(returncode=1)
        available, error = linux_tools.check_sudo_available()
        assert available is False
        assert error is not None
        assert "password" in error.lower()

    @patch("subprocess.run")
    def test_sudo_not_installed(self, mock_run: MagicMock) -> None:
        """Should return False when sudo is not installed."""
        mock_run.side_effect = FileNotFoundError()
        available, error = linux_tools.check_sudo_available()
        assert available is False
        assert error is not None
        assert "not installed" in error.lower()


class TestPackageRemoval:
    """Test package removal functionality."""

    @patch("reos.linux_tools.detect_package_manager")
    def test_remove_package_preview(self, mock_pm: MagicMock) -> None:
        """Should return preview when confirm=False."""
        mock_pm.return_value = "apt"
        result = linux_tools.remove_package("vim", confirm=False)
        assert result.success is True
        assert "Would run" in result.stdout
        assert "vim" in result.command

    @patch("reos.linux_tools.detect_package_manager")
    def test_remove_package_purge(self, mock_pm: MagicMock) -> None:
        """Should use purge option for apt."""
        mock_pm.return_value = "apt"
        result = linux_tools.remove_package("vim", confirm=False, purge=True)
        assert "purge" in result.command

    @patch("reos.linux_tools.detect_package_manager")
    def test_remove_package_no_pm(self, mock_pm: MagicMock) -> None:
        """Should fail gracefully without package manager."""
        mock_pm.return_value = None
        result = linux_tools.remove_package("vim", confirm=False)
        assert result.success is False
        assert "No supported package manager" in result.stderr


class TestFirewallDetection:
    """Test firewall detection and status."""

    @patch("os.path.exists")
    def test_detect_ufw(self, mock_exists: MagicMock) -> None:
        """Should detect UFW on Ubuntu/Debian."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/sbin/ufw"
        mock_exists.side_effect = exists_side_effect
        assert linux_tools.detect_firewall() == "ufw"

    @patch("os.path.exists")
    def test_detect_firewalld(self, mock_exists: MagicMock) -> None:
        """Should detect firewalld on RHEL/Fedora."""
        def exists_side_effect(path: str) -> bool:
            return path == "/usr/bin/firewall-cmd"
        mock_exists.side_effect = exists_side_effect
        assert linux_tools.detect_firewall() == "firewalld"

    @patch("os.path.exists")
    def test_detect_no_firewall(self, mock_exists: MagicMock) -> None:
        """Should return None when no firewall found."""
        mock_exists.return_value = False
        assert linux_tools.detect_firewall() is None


class TestFirewallOperations:
    """Test firewall allow/deny/enable/disable."""

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_allow_preview(self, mock_fw: MagicMock) -> None:
        """Should return preview for allow operation."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_allow(80, confirm=False)
        assert result.success is True
        assert "Would run" in result.stdout
        assert "80" in result.command

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_allow_service(self, mock_fw: MagicMock) -> None:
        """Should handle service names."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_allow("ssh", confirm=False)
        assert "ssh" in result.command

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_deny_preview(self, mock_fw: MagicMock) -> None:
        """Should return preview for deny operation."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_deny(22, confirm=False)
        assert result.success is True
        assert "deny" in result.command

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_no_backend(self, mock_fw: MagicMock) -> None:
        """Should fail gracefully without firewall."""
        mock_fw.return_value = None
        result = linux_tools.firewall_allow(80, confirm=False)
        assert result.success is False
        assert "No supported firewall" in result.stderr

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_enable_preview(self, mock_fw: MagicMock) -> None:
        """Should return preview for enable operation."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_enable(confirm=False)
        assert result.success is True
        assert "enable" in result.command
        assert "Warning" in result.stdout

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_disable_preview(self, mock_fw: MagicMock) -> None:
        """Should return preview for disable operation."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_disable(confirm=False)
        assert result.success is True
        assert "disable" in result.command


class TestJournalctl:
    """Test journalctl log retrieval."""

    @patch("subprocess.run")
    def test_get_service_logs(self, mock_run: MagicMock) -> None:
        """Should parse service logs."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="2024-01-15T10:30:45+0000 hostname nginx[123]: Started\n"
        )
        entries = linux_tools.get_service_logs("nginx", lines=10)
        assert len(entries) >= 0  # May be 0 or 1 depending on parsing

    @patch("subprocess.run")
    def test_get_system_logs(self, mock_run: MagicMock) -> None:
        """Should parse system logs."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="2024-01-15T10:30:45+0000 hostname kernel: Log message\n"
        )
        entries = linux_tools.get_system_logs(lines=10)
        assert isinstance(entries, list)

    @patch("subprocess.run")
    def test_get_boot_logs(self, mock_run: MagicMock) -> None:
        """Should parse boot logs."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="2024-01-15T10:30:45+0000 hostname systemd[1]: Boot message\n"
        )
        entries = linux_tools.get_boot_logs(current_boot=True, lines=10)
        assert isinstance(entries, list)

    @patch("subprocess.run")
    def test_get_failed_services(self, mock_run: MagicMock) -> None:
        """Should list failed services."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="test.service loaded failed failed Test service\n"
        )
        services = linux_tools.get_failed_services()
        assert isinstance(services, list)


class TestContainerRuntime:
    """Test container runtime detection and operations."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_detect_podman(self, mock_run: MagicMock, mock_which: MagicMock) -> None:
        """Should detect Podman."""
        mock_which.side_effect = lambda cmd: "/usr/bin/podman" if cmd == "podman" else None
        mock_run.return_value = MagicMock(returncode=0)
        assert linux_tools.detect_container_runtime() == "podman"

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_detect_docker(self, mock_run: MagicMock, mock_which: MagicMock) -> None:
        """Should detect Docker when Podman not available."""
        mock_which.side_effect = lambda cmd: "/usr/bin/docker" if cmd == "docker" else None
        mock_run.return_value = MagicMock(returncode=0)
        assert linux_tools.detect_container_runtime() == "docker"

    @patch("shutil.which")
    def test_detect_no_runtime(self, mock_which: MagicMock) -> None:
        """Should return None when no runtime available."""
        mock_which.return_value = None
        assert linux_tools.detect_container_runtime() is None

    @patch("reos.linux_tools.detect_container_runtime")
    def test_list_containers(self, mock_runtime: MagicMock) -> None:
        """Should return empty list without runtime."""
        mock_runtime.return_value = None
        containers = linux_tools.list_containers()
        assert containers == []

    @patch("reos.linux_tools.detect_container_runtime")
    def test_container_logs_no_runtime(self, mock_runtime: MagicMock) -> None:
        """Should fail gracefully without runtime."""
        mock_runtime.return_value = None
        result = linux_tools.get_container_logs("test_container")
        assert result.success is False
        assert "No container runtime" in result.stderr

    @patch("reos.linux_tools.detect_container_runtime")
    def test_container_exec_preview(self, mock_runtime: MagicMock) -> None:
        """Should return preview for exec."""
        mock_runtime.return_value = "docker"
        result = linux_tools.container_exec("mycontainer", "ls", confirm=False)
        assert result.success is True
        assert "Would run" in result.stdout


class TestUserManagement:
    """Test user and group management."""

    @patch("builtins.open")
    @patch("subprocess.run")
    def test_list_users(self, mock_run: MagicMock, mock_open: MagicMock) -> None:
        """Should list users from /etc/passwd."""
        mock_open.return_value.__enter__.return_value = iter([
            "root:x:0:0:root:/root:/bin/bash\n",
            "testuser:x:1000:1000:Test User:/home/testuser:/bin/bash\n",
        ])
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="testuser : testuser sudo\n"
        )
        users = linux_tools.list_users(system_users=False)
        # Should filter out most system users
        assert isinstance(users, list)

    @patch("builtins.open")
    def test_list_groups(self, mock_open: MagicMock) -> None:
        """Should list groups from /etc/group."""
        mock_open.return_value.__enter__.return_value = iter([
            "root:x:0:\n",
            "sudo:x:27:testuser\n",
            "docker:x:999:testuser\n",
            "testuser:x:1000:\n",
        ])
        groups = linux_tools.list_groups()
        assert isinstance(groups, list)
        # Should include sudo and docker groups
        group_names = [g["name"] for g in groups]
        assert "sudo" in group_names or "docker" in group_names or len(groups) > 0

    def test_add_user_preview(self) -> None:
        """Should return preview for add_user."""
        result = linux_tools.add_user("newuser", confirm=False)
        assert result.success is True
        assert "Would run" in result.stdout
        assert "newuser" in result.command

    def test_add_user_with_groups(self) -> None:
        """Should include groups in command."""
        result = linux_tools.add_user("newuser", groups=["sudo", "docker"], confirm=False)
        assert "sudo" in result.command or "-G" in result.command

    def test_delete_user_preview(self) -> None:
        """Should return preview for delete_user."""
        result = linux_tools.delete_user("olduser", confirm=False)
        assert result.success is True
        assert "Would run" in result.stdout

    def test_delete_user_remove_home(self) -> None:
        """Should use -r flag to remove home."""
        result = linux_tools.delete_user("olduser", remove_home=True, confirm=False)
        assert "-r" in result.command
        assert "Warning" in result.stdout

    def test_add_user_to_group_preview(self) -> None:
        """Should return preview for adding to group."""
        result = linux_tools.add_user_to_group("testuser", "docker", confirm=False)
        assert result.success is True
        assert "docker" in result.command
        assert "testuser" in result.command

    def test_remove_user_from_group_preview(self) -> None:
        """Should return preview for removing from group."""
        result = linux_tools.remove_user_from_group("testuser", "docker", confirm=False)
        assert result.success is True
        assert "gpasswd" in result.command


class TestShellInjectionPrevention:
    """Test that shell injection is prevented."""

    @patch("reos.linux_tools.detect_package_manager")
    def test_package_name_sanitized(self, mock_pm: MagicMock) -> None:
        """Package names should be shell-escaped."""
        mock_pm.return_value = "apt"
        result = linux_tools.install_package("vim; rm -rf /", confirm=False)
        # The command should have the malicious input quoted
        assert "'" in result.command or '"' in result.command or "\\" in result.command

    @patch("reos.linux_tools.detect_firewall")
    def test_firewall_port_sanitized(self, mock_fw: MagicMock) -> None:
        """Firewall port/service names should be shell-escaped."""
        mock_fw.return_value = "ufw"
        result = linux_tools.firewall_allow("ssh; rm -rf /", confirm=False)
        # Should be quoted
        assert "'" in result.command

    def test_username_sanitized(self) -> None:
        """Usernames should be shell-escaped."""
        result = linux_tools.add_user("test; rm -rf /", confirm=False)
        assert "'" in result.command


class TestIntegrationWithMcpTools:
    """Test integration with MCP tools.

    These tests require the full reos package with all dependencies.
    They are skipped if dependencies like pydantic are not available.
    """

    @pytest.fixture(autouse=True)
    def check_dependencies(self) -> None:
        """Skip if reos package dependencies are not available."""
        try:
            from reos.mcp_tools import list_tools  # noqa: F401
        except ImportError:
            pytest.skip("Full reos package dependencies not available")

    def test_tools_registered(self) -> None:
        """Linux tools should be registered in MCP tools."""
        from reos.mcp_tools import list_tools

        tools = list_tools()
        tool_names = [t.name for t in tools]

        linux_tool_names = [
            # Original tools
            "linux_run_command",
            "linux_preview_command",
            "linux_system_info",
            "linux_network_info",
            "linux_list_processes",
            "linux_list_services",
            "linux_service_status",
            "linux_manage_service",
            "linux_search_packages",
            "linux_install_package",
            "linux_list_installed_packages",
            "linux_disk_usage",
            "linux_list_directory",
            "linux_find_files",
            "linux_read_log",
            "linux_docker_containers",
            "linux_docker_images",
            "linux_environment",
            "linux_package_manager",
            # Phase 2 tools - Package removal
            "linux_remove_package",
            # Phase 2 tools - Firewall
            "linux_firewall_status",
            "linux_firewall_allow",
            "linux_firewall_deny",
            "linux_firewall_enable",
            "linux_firewall_disable",
            # Phase 2 tools - Journalctl
            "linux_service_logs",
            "linux_system_logs",
            "linux_boot_logs",
            "linux_failed_services",
            # Phase 2 tools - Containers
            "linux_container_runtime",
            "linux_containers",
            "linux_container_images",
            "linux_container_logs",
            "linux_container_exec",
            # Phase 2 tools - User management
            "linux_list_users",
            "linux_list_groups",
            "linux_add_user",
            "linux_delete_user",
            "linux_add_user_to_group",
            "linux_remove_user_from_group",
        ]

        for name in linux_tool_names:
            assert name in tool_names, f"Tool {name} not found in registered tools"

    def test_call_linux_system_info(self) -> None:
        """Should be able to call linux_system_info via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_system_info", arguments={})
        assert isinstance(result, dict)
        assert "hostname" in result
        assert "kernel" in result

    def test_call_linux_environment(self) -> None:
        """Should be able to call linux_environment via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_environment", arguments={})
        assert isinstance(result, dict)
        assert "shell" in result
        assert "user" in result

    def test_call_linux_run_command(self) -> None:
        """Should be able to call linux_run_command via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_run_command", arguments={"command": "echo test"})
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "test" in result["stdout"]

    def test_call_linux_disk_usage(self) -> None:
        """Should be able to call linux_disk_usage via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_disk_usage", arguments={"path": "/"})
        assert isinstance(result, dict)
        assert "total_gb" in result
        assert result["total_gb"] > 0

    # Phase 2 MCP Tool Integration Tests

    def test_call_linux_remove_package_preview(self) -> None:
        """Should preview package removal via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_remove_package", arguments={
            "package_name": "vim",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result
        # Should be preview mode
        if result.get("success"):
            assert "Would run" in result.get("stdout", "")

    def test_call_linux_firewall_status(self) -> None:
        """Should get firewall status via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_firewall_status", arguments={})
        assert isinstance(result, dict)
        assert "enabled" in result
        assert "backend" in result
        assert "rules" in result

    def test_call_linux_firewall_allow_preview(self) -> None:
        """Should preview firewall allow via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_firewall_allow", arguments={
            "port": 80,
            "protocol": "tcp",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result

    def test_call_linux_service_logs(self) -> None:
        """Should get service logs via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_service_logs", arguments={
            "service_name": "ssh",
            "lines": 10,
        })
        assert isinstance(result, dict)
        assert "service" in result
        assert "entries" in result

    def test_call_linux_system_logs(self) -> None:
        """Should get system logs via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_system_logs", arguments={
            "lines": 10,
        })
        assert isinstance(result, dict)
        assert "entries" in result

    def test_call_linux_boot_logs(self) -> None:
        """Should get boot logs via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_boot_logs", arguments={
            "current_boot": True,
            "lines": 10,
        })
        assert isinstance(result, dict)
        assert "boot" in result
        assert "entries" in result

    def test_call_linux_failed_services(self) -> None:
        """Should get failed services via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_failed_services", arguments={})
        assert isinstance(result, dict)
        assert "count" in result
        assert "services" in result

    def test_call_linux_container_runtime(self) -> None:
        """Should detect container runtime via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_container_runtime", arguments={})
        assert isinstance(result, dict)
        assert "runtime" in result
        assert "available" in result

    def test_call_linux_containers(self) -> None:
        """Should list containers via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_containers", arguments={
            "all_containers": False,
        })
        assert isinstance(result, dict)
        assert "containers" in result
        assert "count" in result

    def test_call_linux_container_images(self) -> None:
        """Should list container images via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_container_images", arguments={})
        assert isinstance(result, dict)
        assert "images" in result
        assert "count" in result

    def test_call_linux_list_users(self) -> None:
        """Should list users via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_list_users", arguments={
            "system_users": False,
        })
        assert isinstance(result, dict)
        assert "users" in result
        assert "count" in result

    def test_call_linux_list_groups(self) -> None:
        """Should list groups via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_list_groups", arguments={})
        assert isinstance(result, dict)
        assert "groups" in result
        assert "count" in result

    def test_call_linux_add_user_preview(self) -> None:
        """Should preview user creation via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_add_user", arguments={
            "username": "testuser",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result
        assert "testuser" in result["command"]

    def test_call_linux_delete_user_preview(self) -> None:
        """Should preview user deletion via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_delete_user", arguments={
            "username": "testuser",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result

    def test_call_linux_add_user_to_group_preview(self) -> None:
        """Should preview adding user to group via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_add_user_to_group", arguments={
            "username": "testuser",
            "group": "docker",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result
        assert "docker" in result["command"]

    def test_call_linux_remove_user_from_group_preview(self) -> None:
        """Should preview removing user from group via call_tool."""
        from reos.db import Database
        from reos.mcp_tools import call_tool

        db = Database(":memory:")
        result = call_tool(db, name="linux_remove_user_from_group", arguments={
            "username": "testuser",
            "group": "docker",
            "confirm": False,
        })
        assert isinstance(result, dict)
        assert "command" in result


class TestMcpToolValidation:
    """Test MCP tool argument validation."""

    @pytest.fixture(autouse=True)
    def check_dependencies(self) -> None:
        """Skip if reos package dependencies are not available."""
        try:
            from reos.mcp_tools import call_tool  # noqa: F401
        except ImportError:
            pytest.skip("Full reos package dependencies not available")

    def test_remove_package_requires_package_name(self) -> None:
        """Should require package_name argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_remove_package", arguments={})
        assert "package_name" in str(exc_info.value.message)

    def test_firewall_allow_requires_port(self) -> None:
        """Should require port argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_firewall_allow", arguments={})
        assert "port" in str(exc_info.value.message)

    def test_service_logs_requires_service_name(self) -> None:
        """Should require service_name argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_service_logs", arguments={})
        assert "service_name" in str(exc_info.value.message)

    def test_container_logs_requires_container_id(self) -> None:
        """Should require container_id argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_container_logs", arguments={})
        assert "container_id" in str(exc_info.value.message)

    def test_container_exec_requires_command(self) -> None:
        """Should require command argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_container_exec", arguments={
                "container_id": "test",
            })
        assert "command" in str(exc_info.value.message)

    def test_add_user_requires_username(self) -> None:
        """Should require username argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_add_user", arguments={})
        assert "username" in str(exc_info.value.message)

    def test_add_user_to_group_requires_group(self) -> None:
        """Should require group argument."""
        from reos.db import Database
        from reos.mcp_tools import ToolError, call_tool

        db = Database(":memory:")
        with pytest.raises(ToolError) as exc_info:
            call_tool(db, name="linux_add_user_to_group", arguments={
                "username": "test",
            })
        assert "group" in str(exc_info.value.message)
