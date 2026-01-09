"""Type definitions for ReOS.

This module provides TypedDict definitions for structured return types,
improving type safety and IDE support across the codebase.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


# =============================================================================
# Linux Tools Return Types
# =============================================================================


class AddressInfo(TypedDict, total=False):
    """Network address information."""

    family: str | None
    address: str | None
    prefix: int | None


class InterfaceInfo(TypedDict, total=False):
    """Network interface information."""

    state: str
    mac: str | None
    addresses: list[AddressInfo]


class ServiceStatus(TypedDict, total=False):
    """Service status information."""

    name: str
    exists: bool
    active: bool
    enabled: bool
    status_output: str
    error: NotRequired[str]


class DiskUsageInfo(TypedDict, total=False):
    """Disk usage information."""

    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float
    error: NotRequired[str]


class DirectoryEntry(TypedDict, total=False):
    """Directory entry information."""

    name: str
    type: Literal["directory", "file"]
    size: NotRequired[int]
    mode: NotRequired[str]
    modified: NotRequired[float]
    error: NotRequired[str]


class LogFileResult(TypedDict, total=False):
    """Log file read result."""

    path: str
    lines: list[str]
    total_lines: int
    error: NotRequired[str]


class EnvironmentInfo(TypedDict, total=False):
    """System environment information."""

    shell: str
    user: str
    home: str
    path: list[str]
    display: str | None
    wayland: str | None
    desktop: str | None
    session_type: str | None
    lang: str | None
    term: str | None
    available_tools: dict[str, str]


class SystemHardware(TypedDict, total=False):
    """System hardware information."""

    ram_gb: float
    gpu_available: bool
    gpu_name: str | None
    gpu_vram_gb: float | None
    gpu_type: Literal["nvidia", "amd", "apple"] | None
    recommended_max_params: Literal["3b", "7b", "13b", "70b"]


class CommandResult(TypedDict, total=False):
    """Command execution result."""

    command: str
    success: bool
    return_code: int
    stdout: str
    stderr: str
    error: NotRequired[str]


class ProcessInfo(TypedDict, total=False):
    """Process information."""

    pid: int
    user: str
    cpu: float
    mem: float
    vsz: int
    rss: int
    tty: str
    stat: str
    start: str
    time: str
    command: str


# =============================================================================
# RPC Response Types
# =============================================================================


class ApprovalInfo(TypedDict, total=False):
    """Approval request information."""

    id: str
    conversation_id: str | None
    command: str
    explanation: str
    risk_level: Literal["low", "medium", "high"]
    affected_paths: list[str]
    undo_command: str | None
    plan_id: str | None
    step_id: str | None
    created_at: str


class ApprovalsResponse(TypedDict):
    """Response containing pending approvals."""

    approvals: list[ApprovalInfo]


class ChatRespondResult(TypedDict, total=False):
    """Chat response result."""

    conversation_id: str
    text: str
    thinking: NotRequired[str]
    tool_results: NotRequired[list[dict[str, str]]]
    status: Literal["completed", "executed", "requires_approval", "error"]
    requires_approval: bool


class ProviderStatus(TypedDict, total=False):
    """LLM provider status."""

    current_provider: str
    available_providers: list[dict[str, str]]
    keyring_available: bool
    ollama_available: bool
    anthropic_configured: bool


# =============================================================================
# Code Mode Types
# =============================================================================


class StepInfo(TypedDict, total=False):
    """Code execution step information."""

    id: str
    description: str
    action: str
    target_file: str | None
    status: Literal["pending", "in_progress", "completed", "failed"]


class CriterionInfo(TypedDict, total=False):
    """Acceptance criterion information."""

    id: str
    description: str
    type: str
    verified: bool


class ExecutionProgress(TypedDict, total=False):
    """Execution progress snapshot."""

    execution_id: str
    session_id: str
    prompt: str
    status: str
    phase: str
    phase_description: str
    phase_index: int
    iteration: int
    max_iterations: int
    steps_completed: int
    steps_total: int
    criteria_fulfilled: int
    criteria_total: int
    current_step: StepInfo | None
    current_criterion: CriterionInfo | None
    files_changed: list[str]
    is_complete: bool
    success: bool | None
    error: str | None
    elapsed_seconds: float
