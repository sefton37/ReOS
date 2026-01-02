"""Shared tool implementations for ReOS MCP + internal agent.

These tools are repo-scoped.

Repo selection is repo-first:
- If `REOS_REPO_PATH` is set, tools run against that repo.
- Otherwise, tools fall back to the workspace root if it is a git repo.

The MCP server wraps these results into MCP's `content` envelope.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alignment import get_git_summary, is_git_repo
from .db import Database
from .repo_discovery import discover_git_repos
from .repo_sandbox import RepoSandboxError, safe_repo_path
from .settings import settings

_JSON = dict[str, Any]


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]


def list_tools() -> list[Tool]:
    return [
        Tool(
            name="reos_repo_discover",
            description="Discover git repos on disk (bounded scan) and store them in SQLite.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_git_summary",
            description=(
                "Return git summary for the current repo. Metadata-only by default; "
                "include_diff must be explicitly set true."
            ),
            input_schema={"type": "object", "properties": {"include_diff": {"type": "boolean"}}},
        ),
        Tool(
            name="reos_repo_grep",
            description="Search text within the current repo (bounded).",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "include_glob": {"type": "string", "description": "Glob like src/**/*.py"},
                    "max_results": {"type": "number"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="reos_repo_read_file",
            description="Read a file within the current repo (bounded) by line range.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "number"},
                    "end_line": {"type": "number"},
                },
                "required": ["path", "start_line", "end_line"],
            },
        ),
        Tool(
            name="reos_repo_list_files",
            description="List files within the current repo using a glob.",
            input_schema={
                "type": "object",
                "properties": {"glob": {"type": "string"}},
                "required": ["glob"],
            },
        ),
        # Thunderbird tools
        Tool(
            name="reos_thunderbird_status",
            description="Check Thunderbird integration status. Returns whether Thunderbird data is available.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_thunderbird_search_messages",
            description=(
                "Search Thunderbird email messages by subject, sender, or recipients. "
                "Returns matching emails with subject, sender, date, and preview."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"},
                    "folder": {"type": "string", "description": "Optional folder name to filter"},
                    "limit": {"type": "number", "description": "Max results (default 50)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="reos_thunderbird_list_folders",
            description="List email folders in Thunderbird with message counts.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_thunderbird_search_contacts",
            description=(
                "Search Thunderbird address book contacts by name, email, or organization."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"},
                    "limit": {"type": "number", "description": "Max results (default 50)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="reos_thunderbird_search_calendar",
            description=(
                "Search Thunderbird calendar events by title, description, or location."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (optional)"},
                    "start_date": {"type": "string", "description": "Start date filter (ISO format)"},
                    "end_date": {"type": "string", "description": "End date filter (ISO format)"},
                    "limit": {"type": "number", "description": "Max results (default 50)"},
                },
            },
        ),
        Tool(
            name="reos_thunderbird_list_calendars",
            description="List available calendars in Thunderbird.",
            input_schema={"type": "object", "properties": {}},
        ),
        # System monitoring tools
        Tool(
            name="reos_system_status",
            description="Get comprehensive system status overview including CPU, memory, disk, and service health.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_list_processes",
            description="List running processes with CPU/memory usage. Can sort by cpu, mem, pid, or time.",
            input_schema={
                "type": "object",
                "properties": {
                    "sort_by": {"type": "string", "enum": ["cpu", "mem", "pid", "time"], "description": "Sort field"},
                    "limit": {"type": "number", "description": "Max results (default 50)"},
                    "user": {"type": "string", "description": "Filter by username"},
                    "filter_command": {"type": "string", "description": "Filter by command substring"},
                },
            },
        ),
        Tool(
            name="reos_process_details",
            description="Get detailed information about a specific process by PID.",
            input_schema={
                "type": "object",
                "properties": {
                    "pid": {"type": "number", "description": "Process ID"},
                },
                "required": ["pid"],
            },
        ),
        Tool(
            name="reos_list_containers",
            description="List Docker containers. Shows running containers by default.",
            input_schema={
                "type": "object",
                "properties": {
                    "all": {"type": "boolean", "description": "Include stopped containers"},
                },
            },
        ),
        Tool(
            name="reos_container_stats",
            description="Get resource usage stats (CPU, memory, I/O) for running Docker containers.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_container_logs",
            description="Get recent logs from a Docker container.",
            input_schema={
                "type": "object",
                "properties": {
                    "container": {"type": "string", "description": "Container name or ID"},
                    "lines": {"type": "number", "description": "Number of lines (default 100)"},
                },
                "required": ["container"],
            },
        ),
        Tool(
            name="reos_list_docker_images",
            description="List Docker images on the system.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_list_services",
            description="List systemd services. Can filter by state (running, failed, inactive).",
            input_schema={
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Filter by state (running, failed, inactive)"},
                },
            },
        ),
        Tool(
            name="reos_service_status",
            description="Get detailed status of a specific systemd service.",
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service name (e.g., nginx, docker)"},
                },
                "required": ["service"],
            },
        ),
        Tool(
            name="reos_failed_services",
            description="List all failed systemd services.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_disk_usage",
            description="Get disk usage for mounted filesystems.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_memory_info",
            description="Get memory usage information.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_cpu_info",
            description="Get CPU information including load averages and uptime.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_network_connections",
            description="Get network connections. Can filter by state (LISTEN, ESTABLISHED) and protocol (tcp, udp).",
            input_schema={
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Filter by state (LISTEN, ESTABLISHED, etc.)"},
                    "protocol": {"type": "string", "description": "Filter by protocol (tcp, udp)"},
                },
            },
        ),
        Tool(
            name="reos_listening_ports",
            description="Get all listening ports on the system.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_network_interfaces",
            description="Get network interface information including IP addresses.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_journal_logs",
            description="Get system logs from journalctl. Can filter by unit, priority, time, and pattern.",
            input_schema={
                "type": "object",
                "properties": {
                    "unit": {"type": "string", "description": "Filter by systemd unit (e.g., nginx.service)"},
                    "priority": {"type": "string", "description": "Filter by priority (err, warning, info, debug)"},
                    "since": {"type": "string", "description": "Time filter (e.g., '1 hour ago', 'today')"},
                    "lines": {"type": "number", "description": "Max lines (default 100)"},
                    "grep": {"type": "string", "description": "Filter by pattern"},
                },
            },
        ),
        Tool(
            name="reos_logged_in_users",
            description="Get currently logged in users.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_last_logins",
            description="Get recent login history.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "Max results (default 20)"},
                },
            },
        ),
        # GPU monitoring tools (NVIDIA)
        Tool(
            name="reos_gpu_info",
            description="Get NVIDIA GPU information (model, driver version, VRAM, PCIe info).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_gpu_usage",
            description="Get current NVIDIA GPU utilization, memory usage, temperature, power draw, and fan speed.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_gpu_processes",
            description="Get processes currently using the NVIDIA GPU with their memory consumption.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_gpu_summary",
            description="Get a quick summary of GPU status (availability, utilization, temperature). NVIDIA-specific.",
            input_schema={"type": "object", "properties": {}},
        ),
        # Unified GPU tools (vendor-agnostic)
        Tool(
            name="reos_detect_gpus",
            description="Detect all available GPUs regardless of vendor (NVIDIA, AMD). Returns which GPU types are available.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_all_gpu_info",
            description="Get hardware information for all detected GPUs (any vendor: NVIDIA, AMD).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_all_gpu_usage",
            description="Get current utilization for all detected GPUs (any vendor: NVIDIA, AMD).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_all_gpu_summary",
            description="Get a vendor-agnostic summary of all GPU status. Works with NVIDIA and AMD GPUs.",
            input_schema={"type": "object", "properties": {}},
        ),
        # File structure and drive tools
        Tool(
            name="reos_list_directory",
            description="List directory contents with file statistics (size, permissions, modified time).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list (default: /)"},
                    "show_hidden": {"type": "boolean", "description": "Include hidden files (default: false)"},
                    "include_stats": {"type": "boolean", "description": "Include file stats (default: true)"},
                },
            },
        ),
        Tool(
            name="reos_directory_tree",
            description="Get a tree structure of a directory with configurable depth.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root directory path (default: /)"},
                    "max_depth": {"type": "integer", "description": "Maximum depth to traverse (default: 2)"},
                    "show_hidden": {"type": "boolean", "description": "Include hidden files (default: false)"},
                },
            },
        ),
        Tool(
            name="reos_block_devices",
            description="Get information about all block devices (drives, partitions, their types and mount points).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_drive_info",
            description="Get detailed information about physical drives including model, size, and partitions.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_mount_points",
            description="Get all mount points with usage information (device, filesystem type, size, used, available).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_filesystem_overview",
            description="Get a comprehensive overview of filesystem and storage (drives, partitions, mount points, total storage).",
            input_schema={"type": "object", "properties": {}},
        ),
    ]


def _repo_root(db: Database) -> Path:
    state_repo_path = db.get_state(key="repo_path")
    if isinstance(state_repo_path, str) and state_repo_path.strip():
        candidate = Path(state_repo_path).resolve()
        if is_git_repo(candidate):
            return candidate

    if settings.repo_path is not None and is_git_repo(settings.repo_path):
        return settings.repo_path.resolve()

    if is_git_repo(settings.root_dir):
        return settings.root_dir.resolve()

    raise ToolError(
        code="no_repo_detected",
        message="No git repo detected.",
        data={"hint": "Set REOS_REPO_PATH or run ReOS inside a git repo."},
    )


def call_tool(db: Database, *, name: str, arguments: dict[str, Any] | None) -> Any:
    args = arguments or {}

    if name == "reos_repo_discover":
        repos = discover_git_repos()
        import uuid

        for repo_path in repos:
            db.upsert_repo(repo_id=str(uuid.uuid4()), path=str(repo_path))
        return {"discovered": len(repos)}

    if name == "reos_git_summary":
        include_diff = bool(args.get("include_diff", False))
        repo_root = _repo_root(db)
        summary = get_git_summary(repo_root, include_diff=include_diff)
        return {
            "repo": str(summary.repo_path),
            "branch": summary.branch,
            "changed_files": summary.changed_files,
            "diff_stat": summary.diff_stat,
            "status_porcelain": summary.status_porcelain,
            "diff": summary.diff_text if include_diff else None,
        }

    if name == "reos_repo_list_files":
        glob = args.get("glob")
        if not isinstance(glob, str) or not glob:
            raise ToolError(code="invalid_args", message="glob is required")
        repo_root = _repo_root(db)
        return sorted(
            [
                str(p.relative_to(repo_root))
                for p in repo_root.glob(glob)
                if p.is_file()
            ]
        )

    if name == "reos_repo_read_file":
        repo_root = _repo_root(db)
        path = args.get("path")
        start = args.get("start_line")
        end = args.get("end_line")

        if not isinstance(path, str) or not path:
            raise ToolError(code="invalid_args", message="path is required")
        if not isinstance(start, int | float) or not isinstance(end, int | float):
            raise ToolError(code="invalid_args", message="start_line/end_line must be numbers")

        start_i = int(start)
        end_i = int(end)
        if start_i < 1 or end_i < start_i:
            raise ToolError(code="invalid_args", message="Invalid line range")

        try:
            full_path = safe_repo_path(repo_root, path)
        except RepoSandboxError as exc:
            raise ToolError(code="path_escape", message=str(exc), data={"path": path}) from exc

        if not full_path.exists() or not full_path.is_file():
            raise ToolError(code="file_not_found", message="File not found", data={"path": path})

        max_lines = 400
        if end_i - start_i + 1 > max_lines:
            raise ToolError(code="range_too_large", message="Requested range too large", data={"max_lines": max_lines})

        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[start_i - 1 : end_i])

    if name == "reos_repo_grep":
        repo_root = _repo_root(db)
        query = args.get("query")
        include_glob = args.get("include_glob", "**/*.py")
        max_results = int(args.get("max_results", 50))

        if not isinstance(query, str) or not query:
            raise ToolError(code="invalid_args", message="query is required")
        if not isinstance(include_glob, str) or not include_glob:
            raise ToolError(code="invalid_args", message="include_glob must be a string")
        if max_results < 1 or max_results > 500:
            raise ToolError(code="invalid_args", message="max_results must be between 1 and 500")

        pattern = re.compile(re.escape(query), flags=re.IGNORECASE)
        results: list[_JSON] = []

        for file_path in repo_root.glob(include_glob):
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for idx, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    results.append(
                        {
                            "path": str(file_path.relative_to(repo_root)),
                            "line": idx,
                            "text": line[:400],
                        }
                    )
                    if len(results) >= max_results:
                        return results

        return results

    # Thunderbird tool handlers
    if name == "reos_thunderbird_status":
        from .thunderbird import get_thunderbird_status

        return get_thunderbird_status()

    if name == "reos_thunderbird_search_messages":
        from .thunderbird import ThunderbirdClient, ThunderbirdError

        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError(code="invalid_args", message="query is required")

        folder = args.get("folder")
        limit = int(args.get("limit", 50))
        if limit < 1 or limit > 200:
            limit = 50

        try:
            client = ThunderbirdClient()
            messages = client.search_messages(query, folder_name=folder, limit=limit)
            return [
                {
                    "id": m.id,
                    "subject": m.subject,
                    "sender": m.sender,
                    "recipients": m.recipients,
                    "date": m.date.isoformat() if m.date else None,
                    "snippet": m.snippet,
                }
                for m in messages
            ]
        except ThunderbirdError as exc:
            raise ToolError(code="thunderbird_error", message=str(exc)) from exc

    if name == "reos_thunderbird_list_folders":
        from .thunderbird import ThunderbirdClient, ThunderbirdError

        try:
            client = ThunderbirdClient()
            return client.list_folders()
        except ThunderbirdError as exc:
            raise ToolError(code="thunderbird_error", message=str(exc)) from exc

    if name == "reos_thunderbird_search_contacts":
        from .thunderbird import ThunderbirdClient, ThunderbirdError

        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError(code="invalid_args", message="query is required")

        limit = int(args.get("limit", 50))
        if limit < 1 or limit > 200:
            limit = 50

        try:
            client = ThunderbirdClient()
            contacts = client.search_contacts(query, limit=limit)
            return [
                {
                    "id": c.id,
                    "display_name": c.display_name,
                    "primary_email": c.primary_email,
                    "secondary_email": c.secondary_email,
                    "phone_work": c.phone_work,
                    "phone_home": c.phone_home,
                    "phone_mobile": c.phone_mobile,
                    "organization": c.organization,
                    "notes": c.notes,
                }
                for c in contacts
            ]
        except ThunderbirdError as exc:
            raise ToolError(code="thunderbird_error", message=str(exc)) from exc

    if name == "reos_thunderbird_search_calendar":
        from datetime import datetime, timezone

        from .thunderbird import ThunderbirdClient, ThunderbirdError

        query = args.get("query")  # Optional for calendar
        limit = int(args.get("limit", 50))
        if limit < 1 or limit > 200:
            limit = 50

        start_date = None
        end_date = None
        if args.get("start_date"):
            try:
                start_date = datetime.fromisoformat(args["start_date"].replace("Z", "+00:00"))
            except ValueError:
                raise ToolError(code="invalid_args", message="Invalid start_date format")
        if args.get("end_date"):
            try:
                end_date = datetime.fromisoformat(args["end_date"].replace("Z", "+00:00"))
            except ValueError:
                raise ToolError(code="invalid_args", message="Invalid end_date format")

        try:
            client = ThunderbirdClient()
            events = client.search_calendar(query, start_date=start_date, end_date=end_date, limit=limit)
            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "start_time": e.start_time.isoformat() if e.start_time else None,
                    "end_time": e.end_time.isoformat() if e.end_time else None,
                    "location": e.location,
                    "description": e.description,
                    "is_all_day": e.is_all_day,
                }
                for e in events
            ]
        except ThunderbirdError as exc:
            raise ToolError(code="thunderbird_error", message=str(exc)) from exc

    if name == "reos_thunderbird_list_calendars":
        from .thunderbird import ThunderbirdClient, ThunderbirdError

        try:
            client = ThunderbirdClient()
            return client.list_calendars()
        except ThunderbirdError as exc:
            raise ToolError(code="thunderbird_error", message=str(exc)) from exc

    # System monitoring tool handlers
    if name == "reos_system_status":
        from .system_monitor import SystemMonitorError, get_system_status

        try:
            return get_system_status()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_list_processes":
        from .system_monitor import SystemMonitorError, list_processes

        sort_by = args.get("sort_by", "cpu")
        limit = int(args.get("limit", 50))
        user = args.get("user")
        filter_command = args.get("filter_command")

        if limit < 1 or limit > 500:
            limit = 50

        try:
            processes = list_processes(
                sort_by=sort_by, limit=limit, user=user, filter_command=filter_command
            )
            return [
                {
                    "pid": p.pid,
                    "ppid": p.ppid,
                    "user": p.user,
                    "cpu_percent": p.cpu_percent,
                    "mem_percent": p.mem_percent,
                    "rss_mb": round(p.rss_kb / 1024, 1),
                    "stat": p.stat,
                    "command": p.command,
                }
                for p in processes
            ]
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_process_details":
        from .system_monitor import SystemMonitorError, get_process_details

        pid = args.get("pid")
        if not isinstance(pid, (int, float)):
            raise ToolError(code="invalid_args", message="pid is required")

        try:
            return get_process_details(int(pid))
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_list_containers":
        from .system_monitor import SystemMonitorError, list_containers

        all_containers = bool(args.get("all", False))

        try:
            return list_containers(all_containers=all_containers)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_container_stats":
        from .system_monitor import SystemMonitorError, get_container_stats

        try:
            return get_container_stats()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_container_logs":
        from .system_monitor import SystemMonitorError, get_container_logs

        container = args.get("container")
        if not isinstance(container, str) or not container.strip():
            raise ToolError(code="invalid_args", message="container is required")

        lines = int(args.get("lines", 100))
        if lines < 1 or lines > 1000:
            lines = 100

        try:
            return {"container": container, "logs": get_container_logs(container, lines=lines)}
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_list_docker_images":
        from .system_monitor import SystemMonitorError, list_docker_images

        try:
            return list_docker_images()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_list_services":
        from .system_monitor import SystemMonitorError, list_services

        state = args.get("state")

        try:
            return list_services(state=state)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_service_status":
        from .system_monitor import SystemMonitorError, get_service_status

        service = args.get("service")
        if not isinstance(service, str) or not service.strip():
            raise ToolError(code="invalid_args", message="service is required")

        try:
            return get_service_status(service)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_failed_services":
        from .system_monitor import SystemMonitorError, get_failed_services

        try:
            return get_failed_services()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_disk_usage":
        from .system_monitor import SystemMonitorError, get_disk_usage

        try:
            return get_disk_usage()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_memory_info":
        from .system_monitor import SystemMonitorError, get_memory_info

        try:
            return get_memory_info()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_cpu_info":
        from .system_monitor import SystemMonitorError, get_cpu_info

        try:
            return get_cpu_info()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_network_connections":
        from .system_monitor import SystemMonitorError, get_network_connections

        state = args.get("state")
        protocol = args.get("protocol")

        try:
            return get_network_connections(state=state, protocol=protocol)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_listening_ports":
        from .system_monitor import SystemMonitorError, get_listening_ports

        try:
            return get_listening_ports()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_network_interfaces":
        from .system_monitor import SystemMonitorError, get_network_interfaces

        try:
            return get_network_interfaces()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_journal_logs":
        from .system_monitor import SystemMonitorError, get_journal_logs

        unit = args.get("unit")
        priority = args.get("priority")
        since = args.get("since")
        lines = int(args.get("lines", 100))
        grep = args.get("grep")

        if lines < 1 or lines > 1000:
            lines = 100

        try:
            return get_journal_logs(unit=unit, priority=priority, since=since, lines=lines, grep=grep)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_logged_in_users":
        from .system_monitor import SystemMonitorError, get_logged_in_users

        try:
            return get_logged_in_users()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_last_logins":
        from .system_monitor import SystemMonitorError, get_last_logins

        limit = int(args.get("limit", 20))
        if limit < 1 or limit > 100:
            limit = 20

        try:
            return get_last_logins(limit=limit)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    # GPU monitoring tool handlers
    if name == "reos_gpu_info":
        from .system_monitor import SystemMonitorError, get_gpu_info

        try:
            return get_gpu_info()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_gpu_usage":
        from .system_monitor import SystemMonitorError, get_gpu_usage

        try:
            return get_gpu_usage()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_gpu_processes":
        from .system_monitor import SystemMonitorError, get_gpu_processes

        try:
            return get_gpu_processes()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_gpu_summary":
        from .system_monitor import get_gpu_summary

        return get_gpu_summary()

    # Unified GPU tools (vendor-agnostic)
    if name == "reos_detect_gpus":
        from .system_monitor import detect_gpus

        return detect_gpus()

    if name == "reos_all_gpu_info":
        from .system_monitor import get_all_gpu_info

        return get_all_gpu_info()

    if name == "reos_all_gpu_usage":
        from .system_monitor import get_all_gpu_usage

        return get_all_gpu_usage()

    if name == "reos_all_gpu_summary":
        from .system_monitor import get_all_gpu_summary

        return get_all_gpu_summary()

    # File structure and drive tools
    if name == "reos_list_directory":
        from .system_monitor import SystemMonitorError, list_directory

        path = args.get("path", "/")
        show_hidden = bool(args.get("show_hidden", False))
        include_stats = bool(args.get("include_stats", True))

        try:
            return list_directory(path, show_hidden=show_hidden, include_stats=include_stats)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_directory_tree":
        from .system_monitor import SystemMonitorError, get_directory_tree

        path = args.get("path", "/")
        max_depth = int(args.get("max_depth", 2))
        show_hidden = bool(args.get("show_hidden", False))

        try:
            return get_directory_tree(path, max_depth=max_depth, show_hidden=show_hidden)
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_block_devices":
        from .system_monitor import SystemMonitorError, get_block_devices

        try:
            return get_block_devices()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_drive_info":
        from .system_monitor import SystemMonitorError, get_drive_info

        try:
            return get_drive_info()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_mount_points":
        from .system_monitor import SystemMonitorError, get_mount_points

        try:
            return get_mount_points()
        except SystemMonitorError as exc:
            raise ToolError(code="system_error", message=str(exc)) from exc

    if name == "reos_filesystem_overview":
        from .system_monitor import get_filesystem_overview

        return get_filesystem_overview()

    raise ToolError(code="unknown_tool", message=f"Unknown tool: {name}")


def render_tool_result(result: Any) -> str:
    if result is None:
        return "null"
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, ensure_ascii=False)
