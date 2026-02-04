"""System state collection for ReOS.

Provides comprehensive knowledge about the Linux machine:
- Steady State: Static/slow-changing data (RAG context)
- Volatile State: Dynamic data (via tools)

This ensures the LLM has accurate, grounded knowledge about the system.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiskInfo:
    """Information about a disk/partition."""

    device: str
    mount_point: str
    filesystem: str
    size_gb: float
    used_gb: float
    available_gb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "mount_point": self.mount_point,
            "filesystem": self.filesystem,
            "size_gb": self.size_gb,
            "used_gb": self.used_gb,
            "available_gb": self.available_gb,
        }


@dataclass
class NetworkInterface:
    """Information about a network interface."""

    name: str
    mac_address: str | None
    ipv4_addresses: list[str]
    ipv6_addresses: list[str]
    is_up: bool
    is_loopback: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mac_address": self.mac_address,
            "ipv4_addresses": self.ipv4_addresses,
            "ipv6_addresses": self.ipv6_addresses,
            "is_up": self.is_up,
            "is_loopback": self.is_loopback,
        }


@dataclass
class UserInfo:
    """Information about a system user."""

    username: str
    uid: int
    gid: int
    home: str
    shell: str
    is_system: bool  # UID < 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "uid": self.uid,
            "gid": self.gid,
            "home": self.home,
            "shell": self.shell,
            "is_system": self.is_system,
        }


@dataclass
class SteadyState:
    """Static/slow-changing system state.

    This data is collected periodically and included in LLM context
    to ground responses in actual system knowledge.
    """

    # Collection metadata
    collected_at: datetime
    collection_duration_ms: int

    # Identity
    hostname: str
    domain: str | None
    machine_id: str | None

    # OS Information
    os_name: str  # "Ubuntu", "Debian", "Fedora"
    os_version: str  # "24.04"
    os_codename: str | None  # "noble"
    os_pretty_name: str  # "Ubuntu 24.04 LTS"
    kernel_version: str  # "6.8.0-45-generic"
    arch: str  # "x86_64"

    # Hardware
    cpu_model: str
    cpu_cores: int
    cpu_threads: int
    memory_total_gb: float

    # Package Management (moved before fields with defaults)
    package_manager: str  # "apt", "dnf", "pacman"
    installed_packages_count: int

    # Storage (has default)
    disks: list[DiskInfo] = field(default_factory=list)

    # Network (has default)
    network_interfaces: list[NetworkInterface] = field(default_factory=list)

    # Package details (has default)
    key_packages: dict[str, str] = field(default_factory=dict)  # name -> version

    # Services (has default)
    available_services: list[str] = field(default_factory=list)
    enabled_services: list[str] = field(default_factory=list)

    # Users (has default)
    users: list[UserInfo] = field(default_factory=list)
    current_user: str = ""

    # Docker (has default)
    docker_installed: bool = False
    docker_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "collected_at": self.collected_at.isoformat(),
            "collection_duration_ms": self.collection_duration_ms,
            "hostname": self.hostname,
            "domain": self.domain,
            "machine_id": self.machine_id,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "os_codename": self.os_codename,
            "os_pretty_name": self.os_pretty_name,
            "kernel_version": self.kernel_version,
            "arch": self.arch,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "memory_total_gb": self.memory_total_gb,
            "disks": [d.to_dict() for d in self.disks],
            "network_interfaces": [n.to_dict() for n in self.network_interfaces],
            "package_manager": self.package_manager,
            "installed_packages_count": self.installed_packages_count,
            "key_packages": self.key_packages,
            "available_services": self.available_services,
            "enabled_services": self.enabled_services,
            "users": [u.to_dict() for u in self.users],
            "current_user": self.current_user,
            "docker_installed": self.docker_installed,
            "docker_version": self.docker_version,
        }

    def to_context_string(self) -> str:
        """Format for LLM context (concise but comprehensive)."""
        lines = [
            f"SYSTEM STATE (collected {self.collected_at.strftime('%Y-%m-%d %H:%M:%S')}):",
            "",
            f"Hostname: {self.hostname}" + (f".{self.domain}" if self.domain else ""),
            f"OS: {self.os_pretty_name}, kernel {self.kernel_version}",
            f"Architecture: {self.arch}",
            "",
            f"CPU: {self.cpu_model} ({self.cpu_cores} cores, {self.cpu_threads} threads)",
            f"Memory: {self.memory_total_gb:.1f} GB total",
            "",
        ]

        # Disks
        if self.disks:
            lines.append("Storage:")
            for disk in self.disks:
                lines.append(
                    f"  {disk.mount_point}: {disk.available_gb:.1f}GB free "
                    f"of {disk.size_gb:.1f}GB ({disk.device})"
                )
            lines.append("")

        # Network
        if self.network_interfaces:
            non_loopback = [n for n in self.network_interfaces if not n.is_loopback]
            if non_loopback:
                lines.append("Network:")
                for iface in non_loopback:
                    ips = ", ".join(iface.ipv4_addresses) if iface.ipv4_addresses else "no IP"
                    status = "up" if iface.is_up else "down"
                    lines.append(f"  {iface.name}: {ips} ({status})")
                lines.append("")

        # Package management
        lines.append(f"Package Manager: {self.package_manager}")
        lines.append(f"Installed Packages: {self.installed_packages_count}")

        # Key packages
        if self.key_packages:
            key_pkgs = [f"{k} {v}" for k, v in list(self.key_packages.items())[:10]]
            lines.append(f"Key Packages: {', '.join(key_pkgs)}")
        lines.append("")

        # Docker
        if self.docker_installed:
            lines.append(f"Docker: installed (v{self.docker_version})")
        else:
            lines.append("Docker: not installed")
        lines.append("")

        # Services
        lines.append(f"Systemd Services: {len(self.available_services)} available, "
                     f"{len(self.enabled_services)} enabled")
        if self.enabled_services:
            sample = self.enabled_services[:15]
            lines.append(f"  Enabled: {', '.join(sample)}" +
                         (f" (+{len(self.enabled_services) - 15} more)" if len(self.enabled_services) > 15 else ""))
        lines.append("")

        # Users
        regular_users = [u for u in self.users if not u.is_system]
        if regular_users:
            usernames = [u.username for u in regular_users]
            lines.append(f"Users: {', '.join(usernames)}")
            lines.append(f"Current User: {self.current_user}")

        return "\n".join(lines)


class SteadyStateCollector:
    """Collects steady-state system information.

    This class gathers static/slow-changing system data that provides
    grounded context for LLM responses. The data is cached and refreshed
    periodically.
    """

    def __init__(self, cache_path: Path | None = None):
        """Initialize the collector.

        Args:
            cache_path: Optional path to cache collected state
        """
        self.cache_path = cache_path or Path.home() / ".cache" / "reos" / "steady_state.json"
        self._current: SteadyState | None = None
        self._last_collection: datetime | None = None

    @property
    def current(self) -> SteadyState:
        """Get current steady state, collecting if needed."""
        if self._current is None:
            self._current = self.collect()
        return self._current

    def collect(self) -> SteadyState:
        """Collect all steady state information."""
        start_time = datetime.now()
        logger.info("Collecting steady state system information...")

        state = SteadyState(
            collected_at=start_time,
            collection_duration_ms=0,
            hostname=self._get_hostname(),
            domain=self._get_domain(),
            machine_id=self._get_machine_id(),
            os_name=self._get_os_name(),
            os_version=self._get_os_version(),
            os_codename=self._get_os_codename(),
            os_pretty_name=self._get_os_pretty_name(),
            kernel_version=platform.release(),
            arch=platform.machine(),
            cpu_model=self._get_cpu_model(),
            cpu_cores=self._get_cpu_cores(),
            cpu_threads=self._get_cpu_threads(),
            memory_total_gb=self._get_memory_total_gb(),
            disks=self._get_disks(),
            network_interfaces=self._get_network_interfaces(),
            package_manager=self._detect_package_manager(),
            installed_packages_count=self._count_installed_packages(),
            key_packages=self._get_key_packages(),
            available_services=self._get_available_services(),
            enabled_services=self._get_enabled_services(),
            users=self._get_users(),
            current_user=os.environ.get("USER", "unknown"),
            docker_installed=self._check_docker_installed(),
            docker_version=self._get_docker_version(),
        )

        end_time = datetime.now()
        state.collection_duration_ms = int((end_time - start_time).total_seconds() * 1000)

        self._current = state
        self._last_collection = start_time
        self._save_cache(state)

        logger.info("Steady state collected in %dms", state.collection_duration_ms)
        return state

    def get_context(self) -> str:
        """Get formatted context string for LLM prompts."""
        return self.current.to_context_string()

    def refresh_if_stale(self, max_age_seconds: int = 3600) -> SteadyState:
        """Refresh if data is older than max_age_seconds."""
        if self._last_collection is None:
            return self.collect()

        age = (datetime.now() - self._last_collection).total_seconds()
        if age > max_age_seconds:
            logger.info("Steady state is stale (%.0fs old), refreshing...", age)
            return self.collect()

        return self.current

    def _run_cmd(self, cmd: list[str], default: str = "") -> str:
        """Run a command and return stdout, or default on error."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else default
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return default

    def _get_hostname(self) -> str:
        return platform.node() or self._run_cmd(["hostname"], "unknown")

    def _get_domain(self) -> str | None:
        fqdn = self._run_cmd(["hostname", "-f"])
        if fqdn and "." in fqdn:
            return fqdn.split(".", 1)[1]
        return None

    def _get_machine_id(self) -> str | None:
        try:
            return Path("/etc/machine-id").read_text().strip()
        except (FileNotFoundError, PermissionError):
            return None

    def _get_os_release(self) -> dict[str, str]:
        """Parse /etc/os-release."""
        data = {}
        try:
            content = Path("/etc/os-release").read_text()
            for line in content.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key] = value.strip('"')
        except (FileNotFoundError, PermissionError) as e:
            logger.debug("Cannot read /etc/os-release: %s", e)
        return data

    def _get_os_name(self) -> str:
        return self._get_os_release().get("ID", platform.system()).capitalize()

    def _get_os_version(self) -> str:
        return self._get_os_release().get("VERSION_ID", "")

    def _get_os_codename(self) -> str | None:
        return self._get_os_release().get("VERSION_CODENAME")

    def _get_os_pretty_name(self) -> str:
        return self._get_os_release().get("PRETTY_NAME", platform.platform())

    def _get_cpu_model(self) -> str:
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except (FileNotFoundError, PermissionError) as e:
            logger.debug("Cannot read /proc/cpuinfo for CPU model: %s", e)
        return platform.processor() or "Unknown CPU"

    def _get_cpu_cores(self) -> int:
        try:
            return os.cpu_count() or 1
        except (NotImplementedError, OSError) as e:
            logger.debug("Cannot determine CPU core count: %s", e)
            return 1

    def _get_cpu_threads(self) -> int:
        try:
            with open("/proc/cpuinfo") as f:
                return sum(1 for line in f if line.startswith("processor"))
        except (FileNotFoundError, PermissionError):
            return self._get_cpu_cores()

    def _get_memory_total_gb(self) -> float:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 * 1024)
        except (FileNotFoundError, PermissionError) as e:
            logger.debug("Cannot read /proc/meminfo: %s", e)
        return 0.0

    def _get_disks(self) -> list[DiskInfo]:
        disks = []
        output = self._run_cmd(["df", "-BG", "--output=source,target,fstype,size,used,avail"])
        for line in output.splitlines()[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 6 and parts[1].startswith("/"):
                # Skip pseudo filesystems
                if parts[0].startswith("/dev/"):
                    try:
                        disks.append(DiskInfo(
                            device=parts[0],
                            mount_point=parts[1],
                            filesystem=parts[2],
                            size_gb=float(parts[3].rstrip("G")),
                            used_gb=float(parts[4].rstrip("G")),
                            available_gb=float(parts[5].rstrip("G")),
                        ))
                    except ValueError:
                        continue
        return disks

    def _get_network_interfaces(self) -> list[NetworkInterface]:
        interfaces = []
        output = self._run_cmd(["ip", "-j", "addr"])
        if output:
            try:
                data = json.loads(output)
                for iface in data:
                    ipv4 = []
                    ipv6 = []
                    mac = None

                    for addr_info in iface.get("addr_info", []):
                        if addr_info.get("family") == "inet":
                            ipv4.append(addr_info.get("local", ""))
                        elif addr_info.get("family") == "inet6":
                            ipv6.append(addr_info.get("local", ""))

                    if "link" in iface.get("link_type", ""):
                        mac = iface.get("address")

                    interfaces.append(NetworkInterface(
                        name=iface.get("ifname", ""),
                        mac_address=mac,
                        ipv4_addresses=ipv4,
                        ipv6_addresses=ipv6,
                        is_up="UP" in iface.get("flags", []),
                        is_loopback="LOOPBACK" in iface.get("flags", []),
                    ))
            except json.JSONDecodeError:
                logger.debug("Failed to parse 'ip -j addr' output")
        return interfaces

    def _detect_package_manager(self) -> str:
        if os.path.exists("/usr/bin/apt"):
            return "apt"
        elif os.path.exists("/usr/bin/dnf"):
            return "dnf"
        elif os.path.exists("/usr/bin/pacman"):
            return "pacman"
        elif os.path.exists("/usr/bin/zypper"):
            return "zypper"
        return "unknown"

    def _count_installed_packages(self) -> int:
        pm = self._detect_package_manager()
        if pm == "apt":
            output = self._run_cmd(["dpkg-query", "-f", ".\n", "-W"])
            return len(output.splitlines())
        elif pm == "dnf":
            output = self._run_cmd(["rpm", "-qa"])
            return len(output.splitlines())
        elif pm == "pacman":
            output = self._run_cmd(["pacman", "-Q"])
            return len(output.splitlines())
        return 0

    def _get_key_packages(self) -> dict[str, str]:
        """Get versions of commonly important packages."""
        key_packages = {}
        packages_to_check = [
            "python3", "python", "node", "nodejs", "npm",
            "docker", "docker-ce", "podman",
            "nginx", "apache2", "httpd",
            "postgresql", "mysql-server", "mariadb-server", "redis-server",
            "git", "curl", "wget", "vim", "nano",
            "openssh-server", "ufw", "firewalld",
        ]

        pm = self._detect_package_manager()
        if pm == "apt":
            for pkg in packages_to_check:
                output = self._run_cmd(["dpkg-query", "-W", "-f", "${Version}", pkg])
                if output:
                    key_packages[pkg] = output
        elif pm == "dnf":
            for pkg in packages_to_check:
                output = self._run_cmd(["rpm", "-q", "--qf", "%{VERSION}", pkg])
                if output and "not installed" not in output.lower():
                    key_packages[pkg] = output

        return key_packages

    def _get_available_services(self) -> list[str]:
        """Get list of available systemd services."""
        output = self._run_cmd(["systemctl", "list-unit-files", "--type=service", "--no-legend"])
        services = []
        for line in output.splitlines():
            parts = line.split()
            if parts:
                services.append(parts[0].replace(".service", ""))
        return sorted(services)

    def _get_enabled_services(self) -> list[str]:
        """Get list of enabled systemd services."""
        output = self._run_cmd([
            "systemctl", "list-unit-files", "--type=service",
            "--state=enabled", "--no-legend"
        ])
        services = []
        for line in output.splitlines():
            parts = line.split()
            if parts:
                services.append(parts[0].replace(".service", ""))
        return sorted(services)

    def _get_users(self) -> list[UserInfo]:
        """Get list of system users."""
        users = []
        try:
            with open("/etc/passwd") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if len(parts) >= 7:
                        uid = int(parts[2])
                        users.append(UserInfo(
                            username=parts[0],
                            uid=uid,
                            gid=int(parts[3]),
                            home=parts[5],
                            shell=parts[6],
                            is_system=uid < 1000,
                        ))
        except (FileNotFoundError, PermissionError) as e:
            logger.debug("Cannot read /etc/passwd: %s", e)
        return users

    def _check_docker_installed(self) -> bool:
        return os.path.exists("/usr/bin/docker") or os.path.exists("/usr/local/bin/docker")

    def _get_docker_version(self) -> str | None:
        if not self._check_docker_installed():
            return None
        output = self._run_cmd(["docker", "--version"])
        # "Docker version 24.0.7, build afdd53b"
        match = re.search(r"version (\S+)", output)
        return match.group(1).rstrip(",") if match else None

    def _save_cache(self, state: SteadyState) -> None:
        """Save state to cache file."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
        except (OSError, PermissionError) as e:
            logger.warning("Failed to save steady state cache: %s", e)

    def load_cached(self) -> SteadyState | None:
        """Load state from cache if available.

        Returns None - caching disabled, always collect fresh.
        """
        return None
