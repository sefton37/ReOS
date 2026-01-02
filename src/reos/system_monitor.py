"""Linux system monitoring for ReOS.

This module provides read-only system surveillance capabilities for Ubuntu/Linux:
- Process monitoring (ps, top-like info)
- Docker container/image status
- Systemd service status
- System resources (disk, memory, CPU)
- Network connections and ports
- System logs via journalctl
- User sessions and logins

All operations are read-only and safe for server management.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SystemMonitorError(RuntimeError):
    """Error accessing system information."""

    pass


def _run_command(
    cmd: list[str],
    *,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemMonitorError(f"Command timed out: {' '.join(cmd)}") from exc
    except FileNotFoundError as exc:
        raise SystemMonitorError(f"Command not found: {cmd[0]}") from exc


def _command_exists(cmd: str) -> bool:
    """Check if a command exists on the system."""
    return shutil.which(cmd) is not None


# =============================================================================
# Process Monitoring
# =============================================================================


@dataclass(frozen=True)
class ProcessInfo:
    """Information about a running process."""

    pid: int
    ppid: int
    user: str
    cpu_percent: float
    mem_percent: float
    vsz_kb: int
    rss_kb: int
    stat: str
    started: str
    command: str


def list_processes(
    *,
    sort_by: str = "cpu",
    limit: int = 50,
    user: str | None = None,
    filter_command: str | None = None,
) -> list[ProcessInfo]:
    """List running processes.

    Args:
        sort_by: Sort by 'cpu', 'mem', 'pid', or 'time'.
        limit: Maximum number of processes to return.
        user: Filter by username.
        filter_command: Filter by command substring.

    Returns:
        List of ProcessInfo objects.
    """
    # Build ps command with custom format
    cmd = [
        "ps",
        "axo",
        "pid,ppid,user,%cpu,%mem,vsz,rss,stat,lstart,args",
        "--no-headers",
    ]

    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"ps failed: {result.stderr}")

    processes: list[ProcessInfo] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue

        # Parse the fixed-width ps output
        # lstart is like "Mon Jan 20 10:30:00 2025" (24 chars after stat)
        parts = line.split()
        if len(parts) < 10:
            continue

        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            proc_user = parts[2]
            cpu = float(parts[3])
            mem = float(parts[4])
            vsz = int(parts[5])
            rss = int(parts[6])
            stat = parts[7]
            # lstart is 5 fields: Day Mon DD HH:MM:SS YYYY
            started = " ".join(parts[8:13])
            command = " ".join(parts[13:])
        except (ValueError, IndexError):
            continue

        # Apply filters
        if user and proc_user != user:
            continue
        if filter_command and filter_command.lower() not in command.lower():
            continue

        processes.append(
            ProcessInfo(
                pid=pid,
                ppid=ppid,
                user=proc_user,
                cpu_percent=cpu,
                mem_percent=mem,
                vsz_kb=vsz,
                rss_kb=rss,
                stat=stat,
                started=started,
                command=command[:200],  # Truncate long commands
            )
        )

    # Sort
    if sort_by == "cpu":
        processes.sort(key=lambda p: p.cpu_percent, reverse=True)
    elif sort_by == "mem":
        processes.sort(key=lambda p: p.mem_percent, reverse=True)
    elif sort_by == "pid":
        processes.sort(key=lambda p: p.pid)
    elif sort_by == "time":
        processes.sort(key=lambda p: p.started, reverse=True)

    return processes[:limit]


def get_process_details(pid: int) -> dict[str, Any]:
    """Get detailed information about a specific process.

    Args:
        pid: Process ID.

    Returns:
        Dict with process details.
    """
    proc_path = Path(f"/proc/{pid}")
    if not proc_path.exists():
        raise SystemMonitorError(f"Process {pid} not found")

    details: dict[str, Any] = {"pid": pid}

    # Read cmdline
    try:
        cmdline = (proc_path / "cmdline").read_text()
        details["cmdline"] = cmdline.replace("\x00", " ").strip()
    except OSError:
        details["cmdline"] = None

    # Read status
    try:
        status_text = (proc_path / "status").read_text()
        for line in status_text.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip()
                if key in ("name", "state", "ppid", "uid", "gid", "threads", "vmrss", "vmsize"):
                    details[key] = value
    except OSError:
        pass

    # Read cwd
    try:
        details["cwd"] = os.readlink(proc_path / "cwd")
    except OSError:
        details["cwd"] = None

    # Read exe
    try:
        details["exe"] = os.readlink(proc_path / "exe")
    except OSError:
        details["exe"] = None

    # Read fd count
    try:
        fd_path = proc_path / "fd"
        details["open_files"] = len(list(fd_path.iterdir()))
    except OSError:
        details["open_files"] = None

    # Read environ (first 10 vars)
    try:
        environ = (proc_path / "environ").read_text()
        env_vars = environ.split("\x00")[:10]
        details["environment_sample"] = [e for e in env_vars if e]
    except OSError:
        details["environment_sample"] = None

    return details


# =============================================================================
# Docker Monitoring
# =============================================================================


def docker_available() -> bool:
    """Check if Docker is available."""
    return _command_exists("docker")


def list_containers(*, all_containers: bool = False) -> list[dict[str, Any]]:
    """List Docker containers.

    Args:
        all_containers: If True, include stopped containers.

    Returns:
        List of container info dicts.
    """
    if not docker_available():
        raise SystemMonitorError("Docker is not installed")

    cmd = ["docker", "ps", "--format", "json"]
    if all_containers:
        cmd.append("-a")

    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"docker ps failed: {result.stderr}")

    containers = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            container = json.loads(line)
            containers.append({
                "id": container.get("ID", ""),
                "name": container.get("Names", ""),
                "image": container.get("Image", ""),
                "status": container.get("Status", ""),
                "state": container.get("State", ""),
                "ports": container.get("Ports", ""),
                "created": container.get("CreatedAt", ""),
            })
        except json.JSONDecodeError:
            continue

    return containers


def list_docker_images() -> list[dict[str, Any]]:
    """List Docker images."""
    if not docker_available():
        raise SystemMonitorError("Docker is not installed")

    cmd = ["docker", "images", "--format", "json"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"docker images failed: {result.stderr}")

    images = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            image = json.loads(line)
            images.append({
                "id": image.get("ID", ""),
                "repository": image.get("Repository", ""),
                "tag": image.get("Tag", ""),
                "size": image.get("Size", ""),
                "created": image.get("CreatedAt", ""),
            })
        except json.JSONDecodeError:
            continue

    return images


def get_container_stats() -> list[dict[str, Any]]:
    """Get resource usage stats for running containers."""
    if not docker_available():
        raise SystemMonitorError("Docker is not installed")

    cmd = ["docker", "stats", "--no-stream", "--format", "json"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"docker stats failed: {result.stderr}")

    stats = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            stat = json.loads(line)
            stats.append({
                "container": stat.get("Name", ""),
                "cpu_percent": stat.get("CPUPerc", ""),
                "mem_usage": stat.get("MemUsage", ""),
                "mem_percent": stat.get("MemPerc", ""),
                "net_io": stat.get("NetIO", ""),
                "block_io": stat.get("BlockIO", ""),
                "pids": stat.get("PIDs", ""),
            })
        except json.JSONDecodeError:
            continue

    return stats


def get_container_logs(container: str, *, lines: int = 100) -> str:
    """Get recent logs from a container.

    Args:
        container: Container name or ID.
        lines: Number of log lines to retrieve.

    Returns:
        Log output as string.
    """
    if not docker_available():
        raise SystemMonitorError("Docker is not installed")

    cmd = ["docker", "logs", "--tail", str(min(lines, 1000)), container]
    result = _run_command(cmd)
    # docker logs outputs to stderr for some logs
    return result.stdout + result.stderr


# =============================================================================
# Systemd Monitoring
# =============================================================================


def systemd_available() -> bool:
    """Check if systemd is available."""
    return _command_exists("systemctl")


def list_services(
    *,
    state: str | None = None,
    type_filter: str = "service",
) -> list[dict[str, Any]]:
    """List systemd services.

    Args:
        state: Filter by state ('running', 'failed', 'inactive', etc.).
        type_filter: Unit type to list (default 'service').

    Returns:
        List of service info dicts.
    """
    if not systemd_available():
        raise SystemMonitorError("systemd is not available")

    cmd = ["systemctl", "list-units", f"--type={type_filter}", "--all", "--no-pager", "--output=json"]
    if state:
        cmd.append(f"--state={state}")

    result = _run_command(cmd)
    if result.returncode != 0:
        # Fallback to non-JSON output
        return _parse_systemctl_text_output(type_filter, state)

    try:
        units = json.loads(result.stdout)
        return [
            {
                "unit": u.get("unit", ""),
                "load": u.get("load", ""),
                "active": u.get("active", ""),
                "sub": u.get("sub", ""),
                "description": u.get("description", ""),
            }
            for u in units
        ]
    except json.JSONDecodeError:
        return _parse_systemctl_text_output(type_filter, state)


def _parse_systemctl_text_output(type_filter: str, state: str | None) -> list[dict[str, Any]]:
    """Fallback parser for systemctl text output."""
    cmd = ["systemctl", "list-units", f"--type={type_filter}", "--all", "--no-pager", "--no-legend"]
    if state:
        cmd.append(f"--state={state}")

    result = _run_command(cmd)
    services = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(None, 4)
        if len(parts) >= 4:
            services.append({
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            })
    return services


def get_service_status(service: str) -> dict[str, Any]:
    """Get detailed status of a systemd service.

    Args:
        service: Service name (with or without .service suffix).

    Returns:
        Dict with service status details.
    """
    if not systemd_available():
        raise SystemMonitorError("systemd is not available")

    if not service.endswith(".service"):
        service = f"{service}.service"

    cmd = ["systemctl", "show", service, "--no-pager"]
    result = _run_command(cmd)

    status: dict[str, Any] = {"unit": service}
    for line in result.stdout.strip().split("\n"):
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Only include useful fields
            if key in (
                "ActiveState",
                "SubState",
                "LoadState",
                "Description",
                "MainPID",
                "ExecMainStartTimestamp",
                "MemoryCurrent",
                "CPUUsageNSec",
                "TasksCurrent",
                "Restart",
                "RestartUSec",
                "FragmentPath",
                "Result",
            ):
                status[key.lower()] = value

    return status


def get_failed_services() -> list[dict[str, Any]]:
    """Get list of failed systemd services."""
    return list_services(state="failed")


# =============================================================================
# System Resources
# =============================================================================


def get_disk_usage() -> list[dict[str, Any]]:
    """Get disk usage for mounted filesystems."""
    cmd = ["df", "-h", "--output=source,fstype,size,used,avail,pcent,target"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"df failed: {result.stderr}")

    disks = []
    lines = result.stdout.strip().split("\n")
    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 7:
            # Skip pseudo filesystems
            if parts[1] in ("tmpfs", "devtmpfs", "squashfs", "overlay"):
                continue
            disks.append({
                "filesystem": parts[0],
                "type": parts[1],
                "size": parts[2],
                "used": parts[3],
                "available": parts[4],
                "use_percent": parts[5],
                "mounted_on": parts[6],
            })

    return disks


def get_memory_info() -> dict[str, Any]:
    """Get memory usage information."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
    except OSError as exc:
        raise SystemMonitorError(f"Failed to read /proc/meminfo: {exc}") from exc

    info: dict[str, Any] = {}
    for line in meminfo.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace("(", "_").replace(")", "")
            value = value.strip()
            if key in (
                "memtotal",
                "memfree",
                "memavailable",
                "buffers",
                "cached",
                "swaptotal",
                "swapfree",
                "shmem",
                "slab",
            ):
                info[key] = value

    # Calculate usage percentage
    try:
        total = int(info.get("memtotal", "0 kB").split()[0])
        available = int(info.get("memavailable", "0 kB").split()[0])
        if total > 0:
            info["used_percent"] = round((total - available) / total * 100, 1)
    except (ValueError, IndexError):
        pass

    return info


def get_cpu_info() -> dict[str, Any]:
    """Get CPU information."""
    info: dict[str, Any] = {}

    # Get CPU model from /proc/cpuinfo
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for line in cpuinfo.split("\n"):
            if line.startswith("model name"):
                info["model"] = line.split(":")[1].strip()
                break
        info["cores"] = cpuinfo.count("processor\t:")
    except OSError:
        pass

    # Get load average
    try:
        loadavg = Path("/proc/loadavg").read_text().split()
        info["load_1min"] = float(loadavg[0])
        info["load_5min"] = float(loadavg[1])
        info["load_15min"] = float(loadavg[2])
    except (OSError, IndexError, ValueError):
        pass

    # Get uptime
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
        days, remainder = divmod(int(uptime_seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        info["uptime"] = f"{days}d {hours}h {minutes}m"
        info["uptime_seconds"] = uptime_seconds
    except (OSError, ValueError, IndexError):
        pass

    return info


def get_system_overview() -> dict[str, Any]:
    """Get a comprehensive system overview."""
    overview: dict[str, Any] = {}

    # Hostname
    try:
        overview["hostname"] = Path("/etc/hostname").read_text().strip()
    except OSError:
        overview["hostname"] = "unknown"

    # OS info
    try:
        os_release = Path("/etc/os-release").read_text()
        for line in os_release.split("\n"):
            if line.startswith("PRETTY_NAME="):
                overview["os"] = line.split("=")[1].strip().strip('"')
                break
    except OSError:
        overview["os"] = "Linux"

    # Kernel
    result = _run_command(["uname", "-r"])
    overview["kernel"] = result.stdout.strip()

    # Add CPU, memory, disk summaries
    overview["cpu"] = get_cpu_info()
    overview["memory"] = get_memory_info()
    overview["disks"] = get_disk_usage()

    return overview


# =============================================================================
# Network Monitoring
# =============================================================================


def get_network_connections(
    *,
    state: str | None = None,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Get network connections.

    Args:
        state: Filter by state ('LISTEN', 'ESTABLISHED', etc.).
        protocol: Filter by protocol ('tcp', 'udp').

    Returns:
        List of connection info dicts.
    """
    cmd = ["ss", "-tunapH"]  # TCP, UDP, numeric, all, processes, no header
    result = _run_command(cmd)
    if result.returncode != 0:
        # Fallback to netstat
        return _get_connections_netstat(state, protocol)

    connections = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue

        proto = parts[0]
        conn_state = parts[1]
        local = parts[4] if len(parts) > 4 else ""
        remote = parts[5] if len(parts) > 5 else ""
        process = parts[6] if len(parts) > 6 else ""

        # Apply filters
        if protocol and proto.lower() != protocol.lower():
            continue
        if state and conn_state.upper() != state.upper():
            continue

        connections.append({
            "protocol": proto,
            "state": conn_state,
            "local_address": local,
            "remote_address": remote,
            "process": process,
        })

    return connections


def _get_connections_netstat(state: str | None, protocol: str | None) -> list[dict[str, Any]]:
    """Fallback to netstat for connection listing."""
    cmd = ["netstat", "-tuanp"]
    result = _run_command(cmd)

    connections = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) < 6:
            continue
        if parts[0] not in ("tcp", "tcp6", "udp", "udp6"):
            continue

        proto = parts[0]
        local = parts[3]
        remote = parts[4]
        conn_state = parts[5] if proto.startswith("tcp") else "STATELESS"
        process = parts[6] if len(parts) > 6 else ""

        if protocol and not proto.startswith(protocol):
            continue
        if state and conn_state != state:
            continue

        connections.append({
            "protocol": proto,
            "state": conn_state,
            "local_address": local,
            "remote_address": remote,
            "process": process,
        })

    return connections


def get_listening_ports() -> list[dict[str, Any]]:
    """Get all listening ports."""
    return get_network_connections(state="LISTEN")


def get_network_interfaces() -> list[dict[str, Any]]:
    """Get network interface information."""
    cmd = ["ip", "-j", "addr", "show"]
    result = _run_command(cmd)

    try:
        interfaces = json.loads(result.stdout)
        return [
            {
                "name": iface.get("ifname", ""),
                "state": iface.get("operstate", ""),
                "mac": iface.get("address", ""),
                "addresses": [
                    {
                        "family": addr.get("family", ""),
                        "address": addr.get("local", ""),
                        "prefix": addr.get("prefixlen", ""),
                    }
                    for addr in iface.get("addr_info", [])
                ],
            }
            for iface in interfaces
        ]
    except json.JSONDecodeError:
        # Fallback to text parsing
        return _parse_ip_addr_text()


def _parse_ip_addr_text() -> list[dict[str, Any]]:
    """Parse ip addr output as text."""
    cmd = ["ip", "addr", "show"]
    result = _run_command(cmd)

    interfaces = []
    current: dict[str, Any] = {}

    for line in result.stdout.split("\n"):
        if re.match(r"^\d+:", line):
            if current:
                interfaces.append(current)
            parts = line.split(":")
            current = {
                "name": parts[1].strip().split("@")[0],
                "state": "UP" if "UP" in line else "DOWN",
                "addresses": [],
            }
        elif "link/ether" in line:
            current["mac"] = line.split()[1]
        elif "inet " in line:
            parts = line.split()
            current["addresses"].append({
                "family": "inet",
                "address": parts[1].split("/")[0],
                "prefix": parts[1].split("/")[1] if "/" in parts[1] else "",
            })
        elif "inet6 " in line:
            parts = line.split()
            current["addresses"].append({
                "family": "inet6",
                "address": parts[1].split("/")[0],
                "prefix": parts[1].split("/")[1] if "/" in parts[1] else "",
            })

    if current:
        interfaces.append(current)

    return interfaces


# =============================================================================
# Logs and Users
# =============================================================================


def get_journal_logs(
    *,
    unit: str | None = None,
    priority: str | None = None,
    since: str | None = None,
    lines: int = 100,
    grep: str | None = None,
) -> list[dict[str, Any]]:
    """Get system logs from journalctl.

    Args:
        unit: Filter by systemd unit.
        priority: Filter by priority ('emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug').
        since: Time filter (e.g., '1 hour ago', 'today', '2025-01-20').
        lines: Maximum number of log lines.
        grep: Filter logs by pattern.

    Returns:
        List of log entry dicts.
    """
    if not _command_exists("journalctl"):
        raise SystemMonitorError("journalctl not available")

    cmd = ["journalctl", "--no-pager", "-o", "json", "-n", str(min(lines, 1000))]

    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    if since:
        cmd.extend(["--since", since])
    if grep:
        cmd.extend(["-g", grep])

    result = _run_command(cmd, timeout=60)

    logs = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            logs.append({
                "timestamp": entry.get("__REALTIME_TIMESTAMP", ""),
                "unit": entry.get("_SYSTEMD_UNIT", ""),
                "priority": entry.get("PRIORITY", ""),
                "message": entry.get("MESSAGE", ""),
                "pid": entry.get("_PID", ""),
            })
        except json.JSONDecodeError:
            continue

    return logs


def get_logged_in_users() -> list[dict[str, Any]]:
    """Get currently logged in users."""
    cmd = ["who", "-u"]
    result = _run_command(cmd)

    users = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 5:
            users.append({
                "user": parts[0],
                "tty": parts[1],
                "login_time": " ".join(parts[2:4]),
                "idle": parts[4] if len(parts) > 4 else "",
                "pid": parts[5] if len(parts) > 5 else "",
            })

    return users


def get_last_logins(*, limit: int = 20) -> list[dict[str, Any]]:
    """Get recent login history."""
    cmd = ["last", "-n", str(min(limit, 100)), "-F"]
    result = _run_command(cmd)

    logins = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip() or line.startswith("wtmp") or line.startswith("reboot"):
            continue
        parts = line.split()
        if len(parts) >= 4:
            logins.append({
                "user": parts[0],
                "tty": parts[1],
                "host": parts[2] if not parts[2].startswith("Mon") else "",
                "login_time": " ".join(parts[3:8]) if len(parts) > 7 else "",
            })

    return logins


def get_system_status() -> dict[str, Any]:
    """Get a comprehensive system status summary."""
    status: dict[str, Any] = {}

    # Basic info
    status["overview"] = get_system_overview()

    # Counts
    try:
        status["process_count"] = len(list_processes(limit=10000))
    except SystemMonitorError:
        status["process_count"] = None

    try:
        status["listening_ports"] = len(get_listening_ports())
    except SystemMonitorError:
        status["listening_ports"] = None

    try:
        status["logged_in_users"] = len(get_logged_in_users())
    except SystemMonitorError:
        status["logged_in_users"] = None

    # Docker
    status["docker_available"] = docker_available()
    if status["docker_available"]:
        try:
            status["container_count"] = len(list_containers())
        except SystemMonitorError:
            status["container_count"] = None

    # Failed services
    try:
        failed = get_failed_services()
        status["failed_services"] = len(failed)
        status["failed_service_names"] = [s["unit"] for s in failed[:5]]
    except SystemMonitorError:
        status["failed_services"] = None

    # GPU
    status["nvidia_gpu_available"] = nvidia_smi_available()
    if status["nvidia_gpu_available"]:
        try:
            status["gpu"] = get_gpu_usage()
        except SystemMonitorError:
            status["gpu"] = None

    return status


# =============================================================================
# GPU Monitoring (NVIDIA)
# =============================================================================


def nvidia_smi_available() -> bool:
    """Check if nvidia-smi is available (NVIDIA GPU with drivers)."""
    return _command_exists("nvidia-smi")


def get_gpu_info() -> list[dict[str, Any]]:
    """Get NVIDIA GPU information.

    Returns:
        List of GPU info dicts with model, driver, memory, etc.
    """
    if not nvidia_smi_available():
        raise SystemMonitorError("nvidia-smi not available (no NVIDIA GPU or drivers)")

    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,driver_version,memory.total,memory.free,memory.used,pcie.link.gen.current,pcie.link.width.current,compute_mode",
        "--format=csv,noheader,nounits",
    ]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"nvidia-smi failed: {result.stderr}")

    gpus = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            gpus.append({
                "index": int(parts[0]) if parts[0].isdigit() else 0,
                "name": parts[1],
                "driver_version": parts[2],
                "memory_total_mb": int(parts[3]) if parts[3].isdigit() else parts[3],
                "memory_free_mb": int(parts[4]) if parts[4].isdigit() else parts[4],
                "memory_used_mb": int(parts[5]) if parts[5].isdigit() else parts[5],
                "pcie_gen": parts[6] if len(parts) > 6 else None,
                "pcie_width": parts[7] if len(parts) > 7 else None,
                "compute_mode": parts[8] if len(parts) > 8 else None,
            })

    return gpus


def get_gpu_usage() -> list[dict[str, Any]]:
    """Get current NVIDIA GPU utilization and status.

    Returns:
        List of GPU status dicts with utilization, memory, temperature, power.
    """
    if not nvidia_smi_available():
        raise SystemMonitorError("nvidia-smi not available (no NVIDIA GPU or drivers)")

    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,fan.speed,pstate",
        "--format=csv,noheader,nounits",
    ]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"nvidia-smi failed: {result.stderr}")

    gpus = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7:
            gpu: dict[str, Any] = {
                "index": int(parts[0]) if parts[0].isdigit() else 0,
                "name": parts[1],
                "gpu_utilization_percent": _parse_int_or_na(parts[2]),
                "memory_utilization_percent": _parse_int_or_na(parts[3]),
                "memory_total_mb": _parse_int_or_na(parts[4]),
                "memory_used_mb": _parse_int_or_na(parts[5]),
                "memory_free_mb": _parse_int_or_na(parts[6]),
            }
            if len(parts) > 7:
                gpu["temperature_c"] = _parse_int_or_na(parts[7])
            if len(parts) > 8:
                gpu["power_draw_w"] = _parse_float_or_na(parts[8])
            if len(parts) > 9:
                gpu["power_limit_w"] = _parse_float_or_na(parts[9])
            if len(parts) > 10:
                gpu["fan_speed_percent"] = _parse_int_or_na(parts[10])
            if len(parts) > 11:
                gpu["performance_state"] = parts[11]

            gpus.append(gpu)

    return gpus


def _parse_int_or_na(value: str) -> int | None:
    """Parse an integer value, returning None for N/A or errors."""
    value = value.strip()
    if value.lower() in ("[not supported]", "n/a", "[n/a]", ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float_or_na(value: str) -> float | None:
    """Parse a float value, returning None for N/A or errors."""
    value = value.strip()
    if value.lower() in ("[not supported]", "n/a", "[n/a]", ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def get_gpu_processes() -> list[dict[str, Any]]:
    """Get processes currently using NVIDIA GPU.

    Returns:
        List of process info dicts with PID, name, GPU memory usage.
    """
    if not nvidia_smi_available():
        raise SystemMonitorError("nvidia-smi not available (no NVIDIA GPU or drivers)")

    cmd = [
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory,gpu_uuid",
        "--format=csv,noheader,nounits",
    ]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"nvidia-smi failed: {result.stderr}")

    processes = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            processes.append({
                "pid": int(parts[0]) if parts[0].isdigit() else parts[0],
                "process_name": parts[1],
                "gpu_memory_mb": _parse_int_or_na(parts[2]),
                "gpu_uuid": parts[3] if len(parts) > 3 else None,
            })

    return processes


def get_gpu_summary() -> dict[str, Any]:
    """Get a summary of GPU status for quick overview.

    Returns:
        Dict with GPU availability, count, and basic usage stats.
    """
    if not nvidia_smi_available():
        return {
            "available": False,
            "driver": None,
            "gpus": [],
        }

    try:
        info = get_gpu_info()
        usage = get_gpu_usage()
        processes = get_gpu_processes()

        return {
            "available": True,
            "driver": info[0]["driver_version"] if info else None,
            "gpu_count": len(info),
            "gpus": [
                {
                    "name": u["name"],
                    "gpu_util": u.get("gpu_utilization_percent"),
                    "memory_used_mb": u.get("memory_used_mb"),
                    "memory_total_mb": u.get("memory_total_mb"),
                    "temperature_c": u.get("temperature_c"),
                    "power_draw_w": u.get("power_draw_w"),
                }
                for u in usage
            ],
            "process_count": len(processes),
        }
    except SystemMonitorError:
        return {
            "available": True,
            "error": "Failed to query GPU",
            "gpus": [],
        }


# =============================================================================
# GPU Monitoring (AMD/ROCm)
# =============================================================================


def rocm_smi_available() -> bool:
    """Check if rocm-smi is available (AMD GPU with ROCm drivers)."""
    return _command_exists("rocm-smi")


def get_amd_gpu_info() -> list[dict[str, Any]]:
    """Get AMD GPU information using rocm-smi.

    Returns:
        List of GPU info dicts with model, driver, memory, etc.
    """
    if not rocm_smi_available():
        raise SystemMonitorError("rocm-smi not available (no AMD GPU or ROCm drivers)")

    # Get basic GPU info
    cmd = ["rocm-smi", "--showid", "--showproductname", "--showdriver", "--showmeminfo", "vram"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"rocm-smi failed: {result.stderr}")

    gpus: list[dict[str, Any]] = []
    current_gpu: dict[str, Any] = {}

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("GPU["):
            # Start of a new GPU entry
            if current_gpu:
                gpus.append(current_gpu)
            idx = line.split("]")[0].replace("GPU[", "")
            current_gpu = {"index": int(idx) if idx.isdigit() else 0}
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if "card_series" in key or "product_name" in key:
                current_gpu["name"] = value
            elif "driver" in key:
                current_gpu["driver_version"] = value
            elif "vram_total" in key:
                # Parse memory like "16368 MB"
                parts = value.split()
                if parts and parts[0].isdigit():
                    current_gpu["memory_total_mb"] = int(parts[0])
            elif "vram_used" in key:
                parts = value.split()
                if parts and parts[0].isdigit():
                    current_gpu["memory_used_mb"] = int(parts[0])

    if current_gpu:
        gpus.append(current_gpu)

    return gpus


def get_amd_gpu_usage() -> list[dict[str, Any]]:
    """Get current AMD GPU utilization and status.

    Returns:
        List of GPU status dicts with utilization, memory, temperature, power.
    """
    if not rocm_smi_available():
        raise SystemMonitorError("rocm-smi not available (no AMD GPU or ROCm drivers)")

    cmd = ["rocm-smi", "--showuse", "--showtemp", "--showpower", "--showmeminfo", "vram", "--showfan"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"rocm-smi failed: {result.stderr}")

    gpus: list[dict[str, Any]] = []
    current_gpu: dict[str, Any] = {}

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("GPU["):
            if current_gpu:
                gpus.append(current_gpu)
            idx = line.split("]")[0].replace("GPU[", "")
            current_gpu = {"index": int(idx) if idx.isdigit() else 0}
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()

            if "gpu_use" in key:
                # Parse "45%"
                current_gpu["gpu_utilization_percent"] = _parse_int_or_na(value.replace("%", ""))
            elif "temperature" in key and "edge" in key:
                # Parse "55.0c"
                current_gpu["temperature_c"] = _parse_float_or_na(value.lower().replace("c", ""))
            elif "power" in key and "average" in key:
                # Parse "120.5 W"
                current_gpu["power_draw_w"] = _parse_float_or_na(value.split()[0] if value else "")
            elif "vram_total" in key:
                parts = value.split()
                if parts and parts[0].isdigit():
                    current_gpu["memory_total_mb"] = int(parts[0])
            elif "vram_used" in key:
                parts = value.split()
                if parts and parts[0].isdigit():
                    current_gpu["memory_used_mb"] = int(parts[0])
            elif "fan" in key:
                current_gpu["fan_speed_percent"] = _parse_int_or_na(value.replace("%", ""))

    if current_gpu:
        gpus.append(current_gpu)

    return gpus


def get_amd_gpu_processes() -> list[dict[str, Any]]:
    """Get processes currently using AMD GPU.

    Returns:
        List of process info dicts with PID, name, GPU memory usage.
    """
    if not rocm_smi_available():
        raise SystemMonitorError("rocm-smi not available (no AMD GPU or ROCm drivers)")

    cmd = ["rocm-smi", "--showpidgpus"]
    result = _run_command(cmd)
    if result.returncode != 0:
        # This command may not be supported on all ROCm versions
        return []

    processes = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line and not line.startswith("=") and "PID" not in line:
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                processes.append({
                    "pid": int(parts[0]),
                    "gpu_index": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                })

    return processes


# =============================================================================
# GPU Monitoring (Unified/Vendor-Agnostic)
# =============================================================================


def detect_gpus() -> dict[str, Any]:
    """Detect all available GPUs regardless of vendor.

    Returns:
        Dict with detected GPU vendors and their availability.
    """
    return {
        "nvidia": nvidia_smi_available(),
        "amd": rocm_smi_available(),
        "any_gpu": nvidia_smi_available() or rocm_smi_available(),
    }


def get_all_gpu_info() -> list[dict[str, Any]]:
    """Get information for all detected GPUs (any vendor).

    Returns:
        List of GPU info dicts with vendor, model, driver, memory.
    """
    gpus = []

    # Try NVIDIA
    if nvidia_smi_available():
        try:
            for gpu in get_gpu_info():
                gpu["vendor"] = "nvidia"
                gpus.append(gpu)
        except SystemMonitorError:
            pass

    # Try AMD
    if rocm_smi_available():
        try:
            for gpu in get_amd_gpu_info():
                gpu["vendor"] = "amd"
                gpus.append(gpu)
        except SystemMonitorError:
            pass

    return gpus


def get_all_gpu_usage() -> list[dict[str, Any]]:
    """Get usage information for all detected GPUs (any vendor).

    Returns:
        List of GPU usage dicts with vendor, utilization, memory, temperature.
    """
    gpus = []

    # Try NVIDIA
    if nvidia_smi_available():
        try:
            for gpu in get_gpu_usage():
                gpu["vendor"] = "nvidia"
                gpus.append(gpu)
        except SystemMonitorError:
            pass

    # Try AMD
    if rocm_smi_available():
        try:
            for gpu in get_amd_gpu_usage():
                gpu["vendor"] = "amd"
                gpus.append(gpu)
        except SystemMonitorError:
            pass

    return gpus


def get_all_gpu_summary() -> dict[str, Any]:
    """Get a vendor-agnostic summary of all GPU status.

    Returns:
        Dict with GPU availability, vendors, count, and basic usage stats.
    """
    detection = detect_gpus()

    if not detection["any_gpu"]:
        return {
            "available": False,
            "vendors": [],
            "gpus": [],
            "message": "No NVIDIA or AMD GPU detected (or drivers not installed)",
        }

    vendors = []
    if detection["nvidia"]:
        vendors.append("nvidia")
    if detection["amd"]:
        vendors.append("amd")

    try:
        all_info = get_all_gpu_info()
        all_usage = get_all_gpu_usage()

        # Match usage to info by index and vendor
        gpus = []
        for info in all_info:
            vendor = info.get("vendor", "unknown")
            idx = info.get("index", 0)

            # Find matching usage
            usage = next(
                (u for u in all_usage if u.get("vendor") == vendor and u.get("index") == idx),
                {},
            )

            gpus.append({
                "vendor": vendor,
                "name": info.get("name", usage.get("name", "Unknown")),
                "driver": info.get("driver_version"),
                "gpu_util": usage.get("gpu_utilization_percent"),
                "memory_used_mb": usage.get("memory_used_mb") or info.get("memory_used_mb"),
                "memory_total_mb": usage.get("memory_total_mb") or info.get("memory_total_mb"),
                "temperature_c": usage.get("temperature_c"),
                "power_draw_w": usage.get("power_draw_w"),
            })

        return {
            "available": True,
            "vendors": vendors,
            "gpu_count": len(gpus),
            "gpus": gpus,
        }
    except SystemMonitorError as e:
        return {
            "available": True,
            "vendors": vendors,
            "error": str(e),
            "gpus": [],
        }


# =============================================================================
# File Structure and Drive Visibility
# =============================================================================


def list_directory(
    path: str = "/",
    *,
    show_hidden: bool = False,
    include_stats: bool = True,
) -> list[dict[str, Any]]:
    """List directory contents with optional file statistics.

    Args:
        path: Directory path to list.
        show_hidden: Include hidden files (starting with .).
        include_stats: Include file size, permissions, modification time.

    Returns:
        List of file/directory info dicts.
    """
    from datetime import datetime

    target = Path(path)
    if not target.exists():
        raise SystemMonitorError(f"Path does not exist: {path}")
    if not target.is_dir():
        raise SystemMonitorError(f"Path is not a directory: {path}")

    entries = []
    try:
        for entry in target.iterdir():
            if not show_hidden and entry.name.startswith("."):
                continue

            info: dict[str, Any] = {
                "name": entry.name,
                "path": str(entry),
                "type": "directory" if entry.is_dir() else "file",
            }

            if entry.is_symlink():
                info["type"] = "symlink"
                try:
                    info["target"] = str(entry.resolve())
                except OSError:
                    info["target"] = None

            if include_stats:
                try:
                    stat = entry.stat(follow_symlinks=False)
                    info["size_bytes"] = stat.st_size
                    info["permissions"] = oct(stat.st_mode)[-3:]
                    info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    info["owner_uid"] = stat.st_uid
                    info["group_gid"] = stat.st_gid
                except OSError:
                    pass

            entries.append(info)

        # Sort: directories first, then by name
        entries.sort(key=lambda e: (e["type"] != "directory", e["name"].lower()))

    except PermissionError as e:
        raise SystemMonitorError(f"Permission denied: {path}") from e

    return entries


def get_directory_tree(
    path: str = "/",
    *,
    max_depth: int = 2,
    show_hidden: bool = False,
) -> dict[str, Any]:
    """Get a tree structure of a directory.

    Args:
        path: Root directory path.
        max_depth: Maximum depth to traverse (default 2).
        show_hidden: Include hidden files/directories.

    Returns:
        Nested dict representing directory tree.
    """
    target = Path(path)
    if not target.exists():
        raise SystemMonitorError(f"Path does not exist: {path}")
    if not target.is_dir():
        raise SystemMonitorError(f"Path is not a directory: {path}")

    def build_tree(current: Path, depth: int) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": current.name or str(current),
            "type": "directory",
            "path": str(current),
        }

        if depth >= max_depth:
            node["truncated"] = True
            return node

        children = []
        try:
            for entry in sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                if not show_hidden and entry.name.startswith("."):
                    continue

                if entry.is_dir() and not entry.is_symlink():
                    children.append(build_tree(entry, depth + 1))
                else:
                    child: dict[str, Any] = {
                        "name": entry.name,
                        "type": "symlink" if entry.is_symlink() else "file",
                        "path": str(entry),
                    }
                    try:
                        child["size_bytes"] = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
                    children.append(child)

            node["children"] = children
            node["child_count"] = len(children)
        except PermissionError:
            node["error"] = "permission denied"

        return node

    return build_tree(target, 0)


def get_block_devices() -> list[dict[str, Any]]:
    """Get information about block devices (drives, partitions).

    Returns:
        List of block device info dicts.
    """
    cmd = ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL,SERIAL,ROTA,RM"]
    result = _run_command(cmd)
    if result.returncode != 0:
        raise SystemMonitorError(f"lsblk failed: {result.stderr}")

    import json

    try:
        data = json.loads(result.stdout)
        return data.get("blockdevices", [])
    except json.JSONDecodeError as e:
        raise SystemMonitorError(f"Failed to parse lsblk output: {e}") from e


def get_drive_info() -> list[dict[str, Any]]:
    """Get detailed information about physical drives.

    Returns:
        List of drive info dicts with model, size, partitions.
    """
    devices = get_block_devices()

    drives = []
    for dev in devices:
        if dev.get("type") == "disk":
            drive: dict[str, Any] = {
                "name": f"/dev/{dev.get('name', '')}",
                "size": dev.get("size"),
                "model": dev.get("model"),
                "serial": dev.get("serial"),
                "rotational": dev.get("rota") == "1" or dev.get("rota") is True,
                "removable": dev.get("rm") == "1" or dev.get("rm") is True,
                "partitions": [],
            }

            # Get partitions
            for child in dev.get("children", []):
                if child.get("type") == "part":
                    drive["partitions"].append({
                        "name": f"/dev/{child.get('name', '')}",
                        "size": child.get("size"),
                        "fstype": child.get("fstype"),
                        "mountpoint": child.get("mountpoint"),
                    })

            drives.append(drive)

    return drives


def get_mount_points() -> list[dict[str, Any]]:
    """Get all mount points with usage information.

    Returns:
        List of mount point dicts with device, type, usage.
    """
    cmd = ["findmnt", "-J", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS,SIZE,USED,AVAIL,USE%"]
    result = _run_command(cmd)
    if result.returncode != 0:
        # Fallback to df if findmnt fails
        return get_disk_usage()

    import json

    try:
        data = json.loads(result.stdout)

        mounts = []
        for fs in data.get("filesystems", []):
            mount: dict[str, Any] = {
                "mountpoint": fs.get("target"),
                "device": fs.get("source"),
                "fstype": fs.get("fstype"),
                "options": fs.get("options"),
                "size": fs.get("size"),
                "used": fs.get("used"),
                "available": fs.get("avail"),
                "use_percent": fs.get("use%"),
            }
            mounts.append(mount)

        return mounts
    except json.JSONDecodeError:
        return get_disk_usage()


def get_filesystem_overview() -> dict[str, Any]:
    """Get a comprehensive overview of filesystem and storage.

    Returns:
        Dict with drives, partitions, and usage summary.
    """
    overview: dict[str, Any] = {}

    # Get drives
    try:
        overview["drives"] = get_drive_info()
        overview["drive_count"] = len(overview["drives"])
    except SystemMonitorError:
        overview["drives"] = []
        overview["drive_count"] = 0

    # Get mount points with usage
    try:
        mounts = get_mount_points()
        # Filter out pseudo filesystems for summary
        real_mounts = [
            m for m in mounts
            if m.get("fstype") not in ("tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devpts", "cgroup", "cgroup2")
        ]
        overview["mount_points"] = real_mounts
        overview["mount_count"] = len(real_mounts)
    except SystemMonitorError:
        overview["mount_points"] = []
        overview["mount_count"] = 0

    # Calculate total storage
    total_size = 0
    total_used = 0
    for drive in overview.get("drives", []):
        size_str = drive.get("size", "")
        if size_str:
            # Parse size like "500G", "1T", "256M"
            try:
                if size_str.endswith("T"):
                    total_size += float(size_str[:-1]) * 1024 * 1024 * 1024 * 1024
                elif size_str.endswith("G"):
                    total_size += float(size_str[:-1]) * 1024 * 1024 * 1024
                elif size_str.endswith("M"):
                    total_size += float(size_str[:-1]) * 1024 * 1024
            except ValueError:
                pass

    overview["total_storage_bytes"] = int(total_size) if total_size > 0 else None

    return overview
