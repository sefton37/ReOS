"""Shared tool implementations for ReOS MCP + internal agent.

ReOS provides two categories of tools:

1. **Linux System Tools** (always available):
   - Shell command execution (with safety guardrails)
   - System monitoring (CPU, RAM, disk, network)
   - Package management (apt/dnf/pacman)
   - Service management (systemd)
   - Process and file management
   - Docker/container management

2. **Git Integration Tools** (optional - M5 roadmap feature):
   - Disabled by default (set REOS_GIT_INTEGRATION_ENABLED=true to enable)
   - Repository discovery and analysis
   - Change tracking vs roadmap/charter
   - Commit review and suggestions

The MCP server wraps these results into MCP's `content` envelope.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .alignment import get_git_summary, is_git_repo
from .db import Database
from .repo_discovery import discover_git_repos
from .repo_sandbox import RepoSandboxError, safe_repo_path
from .settings import settings
from . import linux_tools

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
    """List all available tools based on settings.

    Linux system tools are always available.
    Git integration tools require settings.git_integration_enabled = True.
    """
    tools: list[Tool] = []

    # =========================================================================
    # Git/Repo Tools (Optional - M5 Roadmap Feature)
    # Only included if git_integration_enabled = True
    # =========================================================================
    if settings.git_integration_enabled:
        tools.extend([
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
        ])

    # =========================================================================
    # Linux System Tools (Always Available - Core ReOS Functionality)
    # =========================================================================
    tools.extend([
        # --- Linux System Tools ---
        Tool(
            name="linux_run_command",
            description=(
                "Execute a shell command on the Linux system. Has safety guardrails to block "
                "dangerous commands. Use for running terminal commands, scripts, and system operations."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"},
                    "timeout": {"type": "number", "description": "Timeout in seconds (default: 30, max: 120)"},
                    "cwd": {"type": "string", "description": "Working directory for the command"},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="linux_preview_command",
            description=(
                "Preview what a command would do BEFORE executing it. Shows affected files, "
                "warnings, and whether the action can be undone. Use this for destructive commands "
                "like rm, mv, package installs, or service management to let users confirm first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to preview"},
                    "cwd": {"type": "string", "description": "Working directory for resolving paths"},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="linux_system_info",
            description=(
                "Get comprehensive Linux system information including hostname, kernel, distro, "
                "CPU, memory usage, disk usage, and load averages."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_network_info",
            description="Get network interface information including IP addresses and states.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_list_processes",
            description="List running processes sorted by CPU or memory usage.",
            input_schema={
                "type": "object",
                "properties": {
                    "sort_by": {"type": "string", "enum": ["cpu", "mem"], "description": "Sort by cpu or mem"},
                    "limit": {"type": "number", "description": "Max processes to return (default: 20)"},
                },
            },
        ),
        Tool(
            name="linux_list_services",
            description="List systemd services on the system.",
            input_schema={
                "type": "object",
                "properties": {
                    "filter_active": {"type": "boolean", "description": "Only show active services"},
                },
            },
        ),
        Tool(
            name="linux_service_status",
            description="Get detailed status of a specific systemd service.",
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Name of the service (e.g., 'nginx', 'docker')"},
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="linux_manage_service",
            description="Manage a systemd service (start, stop, restart, enable, disable). May require sudo.",
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Name of the service"},
                    "action": {"type": "string", "enum": ["start", "stop", "restart", "reload", "enable", "disable"]},
                },
                "required": ["service_name", "action"],
            },
        ),
        Tool(
            name="linux_search_packages",
            description="Search for packages using the system's package manager (apt/dnf/pacman/etc).",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Package name or keyword to search"},
                    "limit": {"type": "number", "description": "Max results (default: 20)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="linux_install_package",
            description=(
                "Install a package using the system's package manager. Requires sudo. "
                "Set confirm=true to actually execute the install."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "package_name": {"type": "string", "description": "Name of the package to install"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["package_name"],
            },
        ),
        Tool(
            name="linux_list_installed_packages",
            description="List installed packages, optionally filtered by search term.",
            input_schema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Optional filter term"},
                },
            },
        ),
        Tool(
            name="linux_disk_usage",
            description="Get disk usage information for a path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to check (default: /)"},
                },
            },
        ),
        Tool(
            name="linux_list_directory",
            description="List contents of a directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "show_hidden": {"type": "boolean", "description": "Include hidden files"},
                    "details": {"type": "boolean", "description": "Include size, permissions, etc."},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="linux_find_files",
            description="Find files matching criteria in a directory tree.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Starting directory"},
                    "name": {"type": "string", "description": "Filename pattern to match"},
                    "extension": {"type": "string", "description": "File extension (e.g., '.py')"},
                    "max_depth": {"type": "number", "description": "Max directory depth (default: 3)"},
                    "limit": {"type": "number", "description": "Max results (default: 50)"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="linux_read_log",
            description="Read and optionally filter a log file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to log file"},
                    "lines": {"type": "number", "description": "Number of lines to read (default: 100)"},
                    "filter_pattern": {"type": "string", "description": "Regex pattern to filter lines"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="linux_docker_containers",
            description="List Docker containers.",
            input_schema={
                "type": "object",
                "properties": {
                    "all_containers": {"type": "boolean", "description": "Include stopped containers"},
                },
            },
        ),
        Tool(
            name="linux_docker_images",
            description="List Docker images.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_environment",
            description="Get environment information (shell, user, available dev tools, display server, etc.).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_package_manager",
            description="Detect the system's package manager (apt, dnf, pacman, etc.).",
            input_schema={"type": "object", "properties": {}},
        ),
        # --- System Index (RAG) ---
        Tool(
            name="system_index_status",
            description=(
                "Get status of the daily system state index. Shows when the last snapshot "
                "was captured and whether a refresh is needed."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="system_index_refresh",
            description=(
                "Force a refresh of the system state index. Captures current system state "
                "(OS, hardware, services, packages, containers, users, storage). "
                "This is normally done automatically once per day."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="system_index_view",
            description=(
                "View the current system state snapshot. Returns the RAG context that "
                "the agent uses for system awareness."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        # --- Package Removal ---
        Tool(
            name="linux_remove_package",
            description=(
                "Remove a package using the system's package manager. Requires sudo. "
                "Set confirm=true to actually execute the removal."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "package_name": {"type": "string", "description": "Name of the package to remove"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                    "purge": {"type": "boolean", "description": "Also remove configuration files (apt only)"},
                },
                "required": ["package_name"],
            },
        ),
        # --- Firewall Management ---
        Tool(
            name="linux_firewall_status",
            description="Get firewall status and rules. Supports ufw (Ubuntu/Debian) and firewalld (RHEL/Fedora).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_firewall_allow",
            description=(
                "Allow a port or service through the firewall. "
                "Set confirm=true to actually apply the rule."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "port": {"type": ["string", "integer"], "description": "Port number or service name (e.g., 80, 'ssh', 'http')"},
                    "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "Protocol (default: tcp)"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["port"],
            },
        ),
        Tool(
            name="linux_firewall_deny",
            description=(
                "Block a port or service in the firewall. "
                "Set confirm=true to actually apply the rule."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "port": {"type": ["string", "integer"], "description": "Port number or service name"},
                    "protocol": {"type": "string", "enum": ["tcp", "udp"], "description": "Protocol (default: tcp)"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["port"],
            },
        ),
        Tool(
            name="linux_firewall_enable",
            description="Enable the system firewall. Set confirm=true to execute.",
            input_schema={
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
            },
        ),
        Tool(
            name="linux_firewall_disable",
            description="Disable the system firewall. Set confirm=true to execute.",
            input_schema={
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
            },
        ),
        # --- Journalctl / Logging ---
        Tool(
            name="linux_service_logs",
            description="Get logs for a systemd service using journalctl.",
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Name of the service (e.g., 'nginx', 'docker')"},
                    "lines": {"type": "number", "description": "Number of log lines to retrieve (default: 50)"},
                    "since": {"type": "string", "description": "Time filter (e.g., '1 hour ago', 'today', '2024-01-01')"},
                    "priority": {"type": "string", "enum": ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"], "description": "Filter by priority level"},
                },
                "required": ["service_name"],
            },
        ),
        Tool(
            name="linux_system_logs",
            description="Get system-wide logs using journalctl.",
            input_schema={
                "type": "object",
                "properties": {
                    "lines": {"type": "number", "description": "Number of log lines to retrieve (default: 100)"},
                    "since": {"type": "string", "description": "Time filter (e.g., '1 hour ago', 'today')"},
                    "priority": {"type": "string", "enum": ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"], "description": "Filter by priority level"},
                    "grep": {"type": "string", "description": "Filter messages containing this pattern"},
                },
            },
        ),
        Tool(
            name="linux_boot_logs",
            description="Get boot logs from journalctl.",
            input_schema={
                "type": "object",
                "properties": {
                    "current_boot": {"type": "boolean", "description": "If true (default), show current boot; false shows previous boot"},
                    "lines": {"type": "number", "description": "Number of log lines to retrieve (default: 100)"},
                },
            },
        ),
        Tool(
            name="linux_failed_services",
            description="List all failed systemd services.",
            input_schema={"type": "object", "properties": {}},
        ),
        # --- Container Management (Docker + Podman) ---
        Tool(
            name="linux_container_runtime",
            description="Detect available container runtime (Docker or Podman).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_containers",
            description="List containers using Docker or Podman (auto-detected).",
            input_schema={
                "type": "object",
                "properties": {
                    "all_containers": {"type": "boolean", "description": "Include stopped containers"},
                },
            },
        ),
        Tool(
            name="linux_container_images",
            description="List container images using Docker or Podman.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_container_logs",
            description="Get logs from a container.",
            input_schema={
                "type": "object",
                "properties": {
                    "container_id": {"type": "string", "description": "Container ID or name"},
                    "lines": {"type": "number", "description": "Number of log lines (default: 100)"},
                    "follow": {"type": "boolean", "description": "If true, returns command to follow logs"},
                },
                "required": ["container_id"],
            },
        ),
        Tool(
            name="linux_container_exec",
            description="Execute a command inside a running container.",
            input_schema={
                "type": "object",
                "properties": {
                    "container_id": {"type": "string", "description": "Container ID or name"},
                    "command": {"type": "string", "description": "Command to execute"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["container_id", "command"],
            },
        ),
        # --- User and Group Management ---
        Tool(
            name="linux_list_users",
            description="List system users.",
            input_schema={
                "type": "object",
                "properties": {
                    "system_users": {"type": "boolean", "description": "Include system users (UID < 1000)"},
                },
            },
        ),
        Tool(
            name="linux_list_groups",
            description="List system groups (excluding most system groups).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="linux_add_user",
            description="Add a new user to the system. Requires sudo.",
            input_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Username to create"},
                    "home_dir": {"type": "string", "description": "Home directory path"},
                    "shell": {"type": "string", "description": "Login shell (default: /bin/bash)"},
                    "groups": {"type": "array", "items": {"type": "string"}, "description": "Additional groups to add user to"},
                    "create_home": {"type": "boolean", "description": "Create home directory (default: true)"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["username"],
            },
        ),
        Tool(
            name="linux_delete_user",
            description="Delete a user from the system. Requires sudo.",
            input_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Username to delete"},
                    "remove_home": {"type": "boolean", "description": "Also remove home directory (default: false)"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["username"],
            },
        ),
        Tool(
            name="linux_add_user_to_group",
            description="Add a user to a group. Requires sudo.",
            input_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Username"},
                    "group": {"type": "string", "description": "Group to add user to"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["username", "group"],
            },
        ),
        Tool(
            name="linux_remove_user_from_group",
            description="Remove a user from a group. Requires sudo.",
            input_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Username"},
                    "group": {"type": "string", "description": "Group to remove user from"},
                    "confirm": {"type": "boolean", "description": "Set to true to execute (default: preview only)"},
                },
                "required": ["username", "group"],
            },
        ),
    ])

    # =========================================================================
    # CAIRN Tools (Knowledge Management & Thunderbird Integration)
    # CAIRN is the Attention Minder - helps manage tasks, calendar, contacts
    # =========================================================================
    tools.extend([
        Tool(
            name="cairn_get_calendar",
            description=(
                "Get calendar events from Thunderbird for a date range. "
                "Use this to see the user's schedule, appointments, and meetings."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Start date (ISO format, default: now)"},
                    "end": {"type": "string", "description": "End date (ISO format, default: 30 days from start)"},
                },
            },
        ),
        Tool(
            name="cairn_get_upcoming_events",
            description=(
                "Get upcoming calendar events in the next N hours. "
                "Great for showing what's coming up soon."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "Hours to look ahead (default: 24)"},
                    "limit": {"type": "number", "description": "Max events to return (default: 10)"},
                },
            },
        ),
        Tool(
            name="cairn_get_todos",
            description="Get todos/tasks from Thunderbird calendar.",
            input_schema={
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean", "description": "Include completed todos (default: false)"},
                },
            },
        ),
        Tool(
            name="cairn_search_contacts",
            description="Search Thunderbird contacts by name, email, or organization.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "number", "description": "Max results (default: 20)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cairn_thunderbird_status",
            description="Check Thunderbird integration status (detected paths, availability).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_surface_today",
            description="Get everything relevant for today (calendar events, due items, priorities).",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_surface_next",
            description="Get the next thing that needs attention based on priority, due dates, and context.",
            input_schema={
                "type": "object",
                "properties": {
                    "max_items": {"type": "number", "description": "Max items to surface (default: 5)"},
                },
            },
        ),
        # --- Play CRUD Tools (Acts, Scenes, Beats management) ---
        Tool(
            name="cairn_list_acts",
            description="List all Acts in The Play. Shows the organizational structure.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="cairn_create_act",
            description="Create a new Act in The Play. An Act is a major area of life/work.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title for the new Act"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="cairn_update_act",
            description="Update an Act's title. Use fuzzy matching for act_name.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Name of the Act to update (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                    "new_title": {"type": "string", "description": "New title for the Act"},
                },
                "required": ["new_title"],
            },
        ),
        Tool(
            name="cairn_delete_act",
            description="Delete an Act and all its contents. Cannot delete 'Your Story' act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Name of the Act to delete (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                },
            },
        ),
        Tool(
            name="cairn_set_active_act",
            description="Set the active Act for the current session.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Name of the Act to set active (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                },
            },
        ),
        Tool(
            name="cairn_list_scenes",
            description="List all Scenes in an Act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Name of the Act (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                },
            },
        ),
        Tool(
            name="cairn_create_scene",
            description="Create a new Scene in an Act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Name of the Act (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                    "title": {"type": "string", "description": "Title for the new Scene"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="cairn_update_scene",
            description="Update a Scene's title.",
            input_schema={
                "type": "object",
                "properties": {
                    "scene_name": {"type": "string", "description": "Name of the Scene to update (fuzzy matched)"},
                    "scene_id": {"type": "string", "description": "Scene ID (alternative to scene_name)"},
                    "act_name": {"type": "string", "description": "Name of the Act containing the Scene"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                    "new_title": {"type": "string", "description": "New title for the Scene"},
                },
                "required": ["new_title"],
            },
        ),
        Tool(
            name="cairn_delete_scene",
            description="Delete a Scene and all its Beats. Cannot delete 'Stage Direction' scene.",
            input_schema={
                "type": "object",
                "properties": {
                    "scene_name": {"type": "string", "description": "Name of the Scene to delete (fuzzy matched)"},
                    "scene_id": {"type": "string", "description": "Scene ID (alternative to scene_name)"},
                    "act_name": {"type": "string", "description": "Name of the Act containing the Scene"},
                    "act_id": {"type": "string", "description": "Act ID (alternative to act_name)"},
                },
            },
        ),
        Tool(
            name="cairn_list_beats",
            description="List Beats, optionally filtered by Act.",
            input_schema={
                "type": "object",
                "properties": {
                    "act_name": {"type": "string", "description": "Filter by Act name (fuzzy matched)"},
                    "act_id": {"type": "string", "description": "Filter by Act ID"},
                },
            },
        ),
        Tool(
            name="cairn_create_beat",
            description="Create a new Beat (task/item) in a Scene.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title for the Beat"},
                    "act_name": {"type": "string", "description": "Act name (fuzzy matched, default: Your Story)"},
                    "scene_name": {"type": "string", "description": "Scene name (fuzzy matched, default: Stage Direction)"},
                    "stage": {"type": "string", "enum": ["planning", "in_progress", "awaiting_data", "complete"], "description": "Stage (default: planning)"},
                    "notes": {"type": "string", "description": "Notes for the Beat"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="cairn_update_beat",
            description="Update a Beat's title, stage, or notes.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {"type": "string", "description": "Name of the Beat to update (fuzzy matched)"},
                    "beat_id": {"type": "string", "description": "Beat ID (alternative to beat_name)"},
                    "new_title": {"type": "string", "description": "New title for the Beat"},
                    "stage": {"type": "string", "enum": ["planning", "in_progress", "awaiting_data", "complete"], "description": "New stage"},
                    "notes": {"type": "string", "description": "New notes"},
                },
            },
        ),
        Tool(
            name="cairn_delete_beat",
            description="Delete a Beat.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {"type": "string", "description": "Name of the Beat to delete (fuzzy matched)"},
                    "beat_id": {"type": "string", "description": "Beat ID (alternative to beat_name)"},
                },
            },
        ),
        Tool(
            name="cairn_move_beat_to_act",
            description="Move a Beat to a different Act. Uses fuzzy matching for names.",
            input_schema={
                "type": "object",
                "properties": {
                    "beat_name": {"type": "string", "description": "Name of the Beat to move (fuzzy matched)"},
                    "beat_id": {"type": "string", "description": "Beat ID (alternative to beat_name)"},
                    "target_act_name": {"type": "string", "description": "Target Act name (fuzzy matched)"},
                    "target_act_id": {"type": "string", "description": "Target Act ID (alternative to target_act_name)"},
                },
            },
        ),
        # --- Self-Knowledge Tools (RAG for codebase understanding) ---
        Tool(
            name="reos_search_codebase",
            description=(
                "Search the ReOS codebase for relevant code. Use this to understand how "
                "features are implemented, find function definitions, or locate relevant files. "
                "Returns functions, classes, and modules matching the query."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query (e.g., 'intent engine', 'calendar sync')"},
                    "limit": {"type": "number", "description": "Max results to return (default: 10)"},
                    "entity_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by type: function, class, module, method, type",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="reos_get_architecture",
            description=(
                "Get the ReOS architecture blueprint. Returns a comprehensive overview of "
                "the system including data models, component architecture, MCP tools, and "
                "file index. Use this to understand how ReOS works."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reos_file_summary",
            description=(
                "Get a summary of a specific source file. Shows functions, classes, and "
                "their purposes. Useful for understanding what a file does."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path (e.g., 'src/reos/cairn/intent_engine.py')"},
                },
                "required": ["file_path"],
            },
        ),
    ])

    return tools


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


# =============================================================================
# Tool Handler Registry
# =============================================================================
# Simple handlers that just wrap linux_tools functions.
# Complex handlers with validation remain in call_tool for now.

def _handle_linux_system_info(db: Database, args: dict) -> Any:
    return asdict(linux_tools.get_system_info())

def _handle_linux_network_info(db: Database, args: dict) -> Any:
    return linux_tools.get_network_info()

def _handle_linux_list_processes(db: Database, args: dict) -> Any:
    sort_by = args.get("sort_by", "cpu")
    limit = int(args.get("limit", 20))
    return [asdict(p) for p in linux_tools.list_processes(sort_by=sort_by, limit=limit)]

def _handle_linux_list_services(db: Database, args: dict) -> Any:
    filter_active = bool(args.get("filter_active", False))
    return [asdict(s) for s in linux_tools.list_services(filter_active=filter_active)]

def _handle_linux_list_installed_packages(db: Database, args: dict) -> Any:
    search = args.get("search")
    packages = linux_tools.list_installed_packages(search=search)
    return {"packages": packages, "count": len(packages)}

def _handle_linux_disk_usage(db: Database, args: dict) -> Any:
    return linux_tools.get_disk_usage(args.get("path", "/"))

def _handle_linux_environment(db: Database, args: dict) -> Any:
    return linux_tools.get_environment()

def _handle_linux_package_manager(db: Database, args: dict) -> Any:
    pm = linux_tools.detect_package_manager()
    return {"name": pm.name, "command": pm.command, "install_cmd": pm.install_cmd}

def _handle_linux_docker_containers(db: Database, args: dict) -> Any:
    all_containers = bool(args.get("all_containers", False))
    containers = linux_tools.list_docker_containers(all_containers=all_containers)
    return {"containers": containers, "docker_available": len(containers) > 0 or linux_tools.check_docker_available()}

def _handle_linux_docker_images(db: Database, args: dict) -> Any:
    images = linux_tools.list_docker_images()
    return {"images": images, "docker_available": len(images) > 0 or linux_tools.check_docker_available()}

def _handle_linux_environment(db: Database, args: dict) -> Any:
    return linux_tools.get_environment_info()

def _handle_linux_package_manager(db: Database, args: dict) -> Any:
    pm = linux_tools.detect_package_manager()
    distro = linux_tools.detect_distro()
    return {"package_manager": pm, "distro": distro}

def _handle_linux_container_runtime(db: Database, args: dict) -> Any:
    runtime = linux_tools.detect_container_runtime()
    return {"runtime": runtime, "available": runtime is not None}

def _handle_linux_containers(db: Database, args: dict) -> Any:
    all_containers = bool(args.get("all_containers", False))
    containers = linux_tools.list_containers(all_containers=all_containers)
    runtime = linux_tools.detect_container_runtime()
    return {"runtime": runtime, "containers": containers, "count": len(containers)}

def _handle_linux_container_images(db: Database, args: dict) -> Any:
    images = linux_tools.list_container_images()
    runtime = linux_tools.detect_container_runtime()
    return {"runtime": runtime, "images": images, "count": len(images)}

def _handle_linux_list_users(db: Database, args: dict) -> Any:
    system_users = bool(args.get("system_users", False))
    users = linux_tools.list_users(system_users=system_users)
    return {
        "count": len(users),
        "users": [
            {"username": u.username, "uid": u.uid, "gid": u.gid,
             "home": u.home, "shell": u.shell, "groups": u.groups}
            for u in users
        ],
    }

def _handle_linux_list_groups(db: Database, args: dict) -> Any:
    groups = linux_tools.list_groups()
    return {"count": len(groups), "groups": groups}

def _handle_linux_failed_services(db: Database, args: dict) -> Any:
    services = linux_tools.get_failed_services()
    return {"count": len(services), "services": [asdict(s) for s in services]}

def _handle_linux_firewall_status(db: Database, args: dict) -> Any:
    status = linux_tools.get_firewall_status()
    return {
        "enabled": status.enabled,
        "backend": status.backend,
        "default_policy": status.default_policy,
        "rules": status.rules,
    }


# Registry of simple handlers - maps tool name to handler function
SIMPLE_TOOL_HANDLERS: dict[str, Any] = {
    "linux_system_info": _handle_linux_system_info,
    "linux_network_info": _handle_linux_network_info,
    "linux_list_processes": _handle_linux_list_processes,
    "linux_list_services": _handle_linux_list_services,
    "linux_list_installed_packages": _handle_linux_list_installed_packages,
    "linux_disk_usage": _handle_linux_disk_usage,
    "linux_environment": _handle_linux_environment,
    "linux_package_manager": _handle_linux_package_manager,
    "linux_docker_containers": _handle_linux_docker_containers,
    "linux_docker_images": _handle_linux_docker_images,
    "linux_container_runtime": _handle_linux_container_runtime,
    "linux_containers": _handle_linux_containers,
    "linux_container_images": _handle_linux_container_images,
    "linux_list_users": _handle_linux_list_users,
    "linux_list_groups": _handle_linux_list_groups,
    "linux_failed_services": _handle_linux_failed_services,
    "linux_firewall_status": _handle_linux_firewall_status,
}


def call_tool(db: Database, *, name: str, arguments: dict[str, Any] | None) -> Any:
    """Dispatch tool calls to appropriate handlers.

    Simple tools use SIMPLE_TOOL_HANDLERS registry.
    Complex tools with validation use inline handlers below.
    CAIRN tools delegate to CairnToolHandler.
    """
    args = arguments or {}

    # Fast path: check simple handlers registry first
    if name in SIMPLE_TOOL_HANDLERS:
        return SIMPLE_TOOL_HANDLERS[name](db, args)

    # Complex handlers with validation logic follow...

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

    # --- Linux System Tools ---

    if name == "linux_run_command":
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError(code="invalid_args", message="command is required")

        timeout = min(int(args.get("timeout", 30)), 120)  # Max 120 seconds
        cwd = args.get("cwd")

        result = linux_tools.execute_command(command, timeout=timeout, cwd=cwd)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_preview_command":
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError(code="invalid_args", message="command is required")

        cwd = args.get("cwd")
        preview = linux_tools.preview_command(command, cwd=cwd)
        return {
            "command": preview.command,
            "is_destructive": preview.is_destructive,
            "description": preview.description,
            "affected_paths": preview.affected_paths,
            "warnings": preview.warnings,
            "can_undo": preview.can_undo,
            "undo_command": preview.undo_command,
        }

    # linux_system_info, linux_network_info, linux_list_processes, linux_list_services
    # now handled by SIMPLE_TOOL_HANDLERS registry above

    if name == "linux_service_status":
        service_name = args.get("service_name")
        if not isinstance(service_name, str) or not service_name.strip():
            raise ToolError(code="invalid_args", message="service_name is required")
        return linux_tools.get_service_status(service_name)

    if name == "linux_manage_service":
        service_name = args.get("service_name")
        action = args.get("action")
        if not isinstance(service_name, str) or not service_name.strip():
            raise ToolError(code="invalid_args", message="service_name is required")
        if not isinstance(action, str) or not action.strip():
            raise ToolError(code="invalid_args", message="action is required")

        result = linux_tools.manage_service(service_name, action)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_search_packages":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError(code="invalid_args", message="query is required")
        limit = int(args.get("limit", 20))
        return linux_tools.search_packages(query, limit=limit)

    if name == "linux_install_package":
        package_name = args.get("package_name")
        if not isinstance(package_name, str) or not package_name.strip():
            raise ToolError(code="invalid_args", message="package_name is required")
        confirm = bool(args.get("confirm", False))

        result = linux_tools.install_package(package_name, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # linux_list_installed_packages, linux_disk_usage now in SIMPLE_TOOL_HANDLERS

    if name == "linux_list_directory":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError(code="invalid_args", message="path is required")
        show_hidden = bool(args.get("show_hidden", False))
        details = bool(args.get("details", False))
        return linux_tools.list_directory(path, show_hidden=show_hidden, details=details)

    if name == "linux_find_files":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError(code="invalid_args", message="path is required")

        name_pattern = args.get("name")
        extension = args.get("extension")
        max_depth = int(args.get("max_depth", 3))
        limit = int(args.get("limit", 50))

        files = linux_tools.find_files(
            path,
            name=name_pattern,
            extension=extension,
            max_depth=max_depth,
            limit=limit,
        )
        return {"files": files, "count": len(files)}

    if name == "linux_read_log":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError(code="invalid_args", message="path is required")

        lines = int(args.get("lines", 100))
        filter_pattern = args.get("filter_pattern")

        return linux_tools.read_log_file(path, lines=lines, filter_pattern=filter_pattern)

    # linux_docker_containers, linux_docker_images, linux_environment, linux_package_manager
    # now handled by SIMPLE_TOOL_HANDLERS registry

    # --- System Index (RAG) ---

    if name == "system_index_status":
        from .system_index import SystemIndexer
        indexer = SystemIndexer(db)
        snapshot = indexer.get_latest_snapshot()
        needs_refresh = indexer.needs_refresh()
        return {
            "has_snapshot": snapshot is not None,
            "needs_refresh": needs_refresh,
            "last_captured": snapshot.captured_at if snapshot else None,
            "hostname": snapshot.hostname if snapshot else None,
            "snapshot_id": snapshot.snapshot_id if snapshot else None,
        }

    if name == "system_index_refresh":
        from .system_index import SystemIndexer
        indexer = SystemIndexer(db)
        snapshot = indexer.capture_snapshot()
        return {
            "success": True,
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at,
            "hostname": snapshot.hostname,
            "message": "System state snapshot captured successfully",
        }

    if name == "system_index_view":
        from .system_index import SystemIndexer, build_rag_context
        indexer = SystemIndexer(db)
        snapshot = indexer.get_latest_snapshot()
        if snapshot is None:
            return {
                "has_snapshot": False,
                "context": "",
                "message": "No system snapshot available. Run system_index_refresh first.",
            }
        context = build_rag_context(snapshot)
        return {
            "has_snapshot": True,
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at,
            "context": context,
        }

    # --- Package Removal ---

    if name == "linux_remove_package":
        package_name = args.get("package_name")
        if not isinstance(package_name, str) or not package_name.strip():
            raise ToolError(code="invalid_args", message="package_name is required")
        confirm = bool(args.get("confirm", False))
        purge = bool(args.get("purge", False))

        result = linux_tools.remove_package(package_name, confirm=confirm, purge=purge)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # --- Firewall Management ---
    # linux_firewall_status now in SIMPLE_TOOL_HANDLERS

    if name == "linux_firewall_allow":
        port = args.get("port")
        if port is None:
            raise ToolError(code="invalid_args", message="port is required")
        protocol = args.get("protocol", "tcp")
        confirm = bool(args.get("confirm", False))

        result = linux_tools.firewall_allow(port, protocol=protocol, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_firewall_deny":
        port = args.get("port")
        if port is None:
            raise ToolError(code="invalid_args", message="port is required")
        protocol = args.get("protocol", "tcp")
        confirm = bool(args.get("confirm", False))

        result = linux_tools.firewall_deny(port, protocol=protocol, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_firewall_enable":
        confirm = bool(args.get("confirm", False))
        result = linux_tools.firewall_enable(confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_firewall_disable":
        confirm = bool(args.get("confirm", False))
        result = linux_tools.firewall_disable(confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # --- Journalctl / Logging ---

    if name == "linux_service_logs":
        service_name = args.get("service_name")
        if not isinstance(service_name, str) or not service_name.strip():
            raise ToolError(code="invalid_args", message="service_name is required")

        lines = int(args.get("lines", 50))
        since = args.get("since")
        priority = args.get("priority")

        entries = linux_tools.get_service_logs(
            service_name,
            lines=lines,
            since=since,
            priority=priority,
        )
        return {
            "service": service_name,
            "count": len(entries),
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "unit": e.unit,
                    "priority": e.priority,
                    "message": e.message,
                }
                for e in entries
            ],
        }

    if name == "linux_system_logs":
        lines = int(args.get("lines", 100))
        since = args.get("since")
        priority = args.get("priority")
        grep = args.get("grep")

        entries = linux_tools.get_system_logs(
            lines=lines,
            since=since,
            priority=priority,
            grep=grep,
        )
        return {
            "count": len(entries),
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "unit": e.unit,
                    "priority": e.priority,
                    "message": e.message,
                }
                for e in entries
            ],
        }

    if name == "linux_boot_logs":
        current_boot = bool(args.get("current_boot", True))
        lines = int(args.get("lines", 100))

        entries = linux_tools.get_boot_logs(current_boot=current_boot, lines=lines)
        return {
            "boot": "current" if current_boot else "previous",
            "count": len(entries),
            "entries": [
                {
                    "timestamp": e.timestamp,
                    "unit": e.unit,
                    "message": e.message,
                }
                for e in entries
            ],
        }

    # linux_failed_services, linux_container_runtime, linux_containers, linux_container_images
    # now handled by SIMPLE_TOOL_HANDLERS registry

    if name == "linux_container_logs":
        container_id = args.get("container_id")
        if not isinstance(container_id, str) or not container_id.strip():
            raise ToolError(code="invalid_args", message="container_id is required")

        lines = int(args.get("lines", 100))
        follow = bool(args.get("follow", False))

        result = linux_tools.get_container_logs(container_id, lines=lines, follow=follow)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_container_exec":
        container_id = args.get("container_id")
        command = args.get("command")
        if not isinstance(container_id, str) or not container_id.strip():
            raise ToolError(code="invalid_args", message="container_id is required")
        if not isinstance(command, str) or not command.strip():
            raise ToolError(code="invalid_args", message="command is required")

        confirm = bool(args.get("confirm", False))
        result = linux_tools.container_exec(container_id, command, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # --- User and Group Management ---
    # linux_list_users, linux_list_groups now in SIMPLE_TOOL_HANDLERS

    if name == "linux_add_user":
        username = args.get("username")
        if not isinstance(username, str) or not username.strip():
            raise ToolError(code="invalid_args", message="username is required")

        home_dir = args.get("home_dir")
        shell = args.get("shell")
        groups = args.get("groups")
        create_home = bool(args.get("create_home", True))
        confirm = bool(args.get("confirm", False))

        result = linux_tools.add_user(
            username,
            home_dir=home_dir,
            shell=shell,
            groups=groups,
            create_home=create_home,
            confirm=confirm,
        )
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_delete_user":
        username = args.get("username")
        if not isinstance(username, str) or not username.strip():
            raise ToolError(code="invalid_args", message="username is required")

        remove_home = bool(args.get("remove_home", False))
        confirm = bool(args.get("confirm", False))

        result = linux_tools.delete_user(username, remove_home=remove_home, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_add_user_to_group":
        username = args.get("username")
        group = args.get("group")
        if not isinstance(username, str) or not username.strip():
            raise ToolError(code="invalid_args", message="username is required")
        if not isinstance(group, str) or not group.strip():
            raise ToolError(code="invalid_args", message="group is required")

        confirm = bool(args.get("confirm", False))
        result = linux_tools.add_user_to_group(username, group, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    if name == "linux_remove_user_from_group":
        username = args.get("username")
        group = args.get("group")
        if not isinstance(username, str) or not username.strip():
            raise ToolError(code="invalid_args", message="username is required")
        if not isinstance(group, str) or not group.strip():
            raise ToolError(code="invalid_args", message="group is required")

        confirm = bool(args.get("confirm", False))
        result = linux_tools.remove_user_from_group(username, group, confirm=confirm)
        return {
            "command": result.command,
            "success": result.success,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # --- Self-Knowledge Tools (RAG for codebase understanding) ---
    if name == "reos_search_codebase":
        from .architecture.code_index import search_codebase

        query = args.get("query", "")
        if not query:
            raise ToolError(code="invalid_args", message="query is required")

        limit = int(args.get("limit", 10))
        entity_types = args.get("entity_types")

        results = search_codebase(query, limit=limit)

        if entity_types:
            results = [r for r in results if r.entity_type in entity_types]

        return {
            "query": query,
            "count": len(results),
            "results": [asdict(r) for r in results],
        }

    if name == "reos_get_architecture":
        from pathlib import Path
        arch_path = Path(__file__).parent / "architecture" / "ARCHITECTURE.md"

        if arch_path.exists():
            content = arch_path.read_text(encoding="utf-8")
            return {
                "success": True,
                "architecture": content,
                "file": str(arch_path),
            }
        else:
            return {
                "success": False,
                "error": "Architecture document not found",
            }

    if name == "reos_file_summary":
        from .architecture.code_index import get_indexer

        file_path = args.get("file_path", "")
        if not file_path:
            raise ToolError(code="invalid_args", message="file_path is required")

        indexer = get_indexer()
        summary = indexer.get_file_summary(file_path)

        return {
            "file_path": file_path,
            "summary": summary,
        }

    # --- CAIRN Tools (Knowledge Management & Thunderbird Integration) ---
    if name.startswith("cairn_"):
        from pathlib import Path
        from .cairn.mcp_tools import CairnToolHandler, CairnToolError
        from .cairn.store import CairnStore
        from .play_fs import play_root
        import logging

        def get_current_play_path(db):
            """Get current play path, or None."""
            try:
                path = play_root()
                return str(path) if path.exists() else None
            except Exception:
                return None

        cairn_logger = logging.getLogger("reos.cairn")
        cairn_logger.info("CAIRN tool called: %s with args: %s", name, args)

        try:
            play_path = get_current_play_path(db)
            if not play_path:
                cairn_logger.warning("CAIRN tool %s failed: No Play path configured", name)
                return {"error": "No Play path configured. Select or create an Act first.", "tool": name}

            store_path = Path(play_path) / ".cairn" / "cairn.db"
            store = CairnStore(store_path)

            # Get LLM for entity resolution (cheap local inference)
            from reos.providers import get_provider
            try:
                llm = get_provider(db)
            except Exception:
                llm = None  # Fallback to fuzzy match if no LLM available

            handler = CairnToolHandler(store=store, llm=llm)

            result = handler.call_tool(name, args)
            cairn_logger.info("CAIRN tool %s succeeded: %s", name, result)
            return result

        except CairnToolError as e:
            cairn_logger.error("CAIRN tool %s error: %s", name, e.message)
            return {"error": e.message, "code": e.code, "tool": name}
        except Exception as e:
            cairn_logger.exception("CAIRN tool %s unexpected error: %s", name, e)
            return {"error": str(e), "tool": name}

    raise ToolError(code="unknown_tool", message=f"Unknown tool: {name}")


def render_tool_result(result: Any) -> str:
    if result is None:
        return "null"
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, ensure_ascii=False)
