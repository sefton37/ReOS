"""System handlers.

Manages system dashboard, services, containers, state, and personas.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from typing import Any

from reos.db import Database
from reos.rpc.router import register
from reos.rpc.types import INVALID_PARAMS, RpcError
from reos.security import (
    AuditEventType,
    RateLimitExceeded,
    audit_log,
    check_rate_limit,
    escape_shell_arg,
    validate_container_id,
    validate_service_name,
    ValidationError,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# System Dashboard handlers
# -------------------------------------------------------------------------


@register("system/live_state", needs_db=True)
def handle_live_state(db: Database) -> dict[str, Any]:
    """Get comprehensive system state for dashboard."""
    from reos import linux_tools

    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "memory": {"used_mb": 0, "total_mb": 0, "percent": 0.0},
        "disks": [],
        "load_avg": [0.0, 0.0, 0.0],
        "services": [],
        "containers": [],
        "network": [],
        "ports": [],
        "traffic": [],
    }

    # Get system info
    try:
        info = linux_tools.get_system_info()
        result["cpu_percent"] = info.get("cpu_percent", 0.0)
        result["memory"] = {
            "used_mb": info.get("memory_used_mb", 0),
            "total_mb": info.get("memory_total_mb", 0),
            "percent": info.get("memory_percent", 0.0),
        }
        result["disks"] = [
            {
                "mount": "/",
                "used_gb": info.get("disk_used_gb", 0),
                "total_gb": info.get("disk_total_gb", 0),
                "percent": info.get("disk_percent", 0.0),
            }
        ]
        result["load_avg"] = info.get("load_avg", [0.0, 0.0, 0.0])
    except Exception as e:
        logger.debug("Failed to get system info: %s", e)
        result["_errors"] = result.get("_errors", []) + ["system_info"]

    # Get services (top 10 most relevant)
    try:
        all_services = linux_tools.list_services()
        # Prioritize running services, then sort by name
        sorted_services = sorted(
            all_services,
            key=lambda s: (0 if s.active_state == "active" else 1, s.name)
        )[:10]
        result["services"] = [
            {
                "name": s.name,
                "status": s.active_state,
                "active": s.active_state == "active",
            }
            for s in sorted_services
        ]
    except Exception as e:
        logger.debug("Failed to list services: %s", e)
        result["_errors"] = result.get("_errors", []) + ["services"]

    # Get containers if Docker is available
    try:
        containers = linux_tools.list_docker_containers()
        result["containers"] = [
            {
                "id": c.get("id", "")[:12],
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "status": c.get("status", "unknown"),
                "ports": c.get("ports", ""),
            }
            for c in containers[:10]
        ]
    except Exception as e:
        logger.debug("Failed to list containers (Docker may not be available): %s", e)
        # Don't add to errors - Docker being unavailable is normal

    # Get network interfaces
    try:
        network = linux_tools.get_network_info()
        if "interfaces" in network:
            result["network"] = [
                {
                    "interface": iface.get("name", ""),
                    "ip": iface.get("ipv4", ""),
                    "state": iface.get("state", "unknown"),
                }
                for iface in network["interfaces"][:5]
            ]
    except Exception as e:
        logger.debug("Failed to get network info: %s", e)
        result["_errors"] = result.get("_errors", []) + ["network"]

    # Get listening ports
    try:
        ports = linux_tools.list_listening_ports()
        result["ports"] = [
            {
                "port": p.port,
                "protocol": p.protocol,
                "address": p.address,
                "process": p.process,
                "pid": p.pid,
            }
            for p in ports[:20]  # Limit to 20 ports
        ]
    except Exception as e:
        logger.debug("Failed to list listening ports: %s", e)
        result["_errors"] = result.get("_errors", []) + ["ports"]

    # Get network traffic
    try:
        traffic = linux_tools.get_network_traffic()
        result["traffic"] = [
            {
                "interface": t.interface,
                "rx_bytes": t.rx_bytes,
                "tx_bytes": t.tx_bytes,
                "rx_formatted": linux_tools.format_bytes(t.rx_bytes),
                "tx_formatted": linux_tools.format_bytes(t.tx_bytes),
            }
            for t in traffic
        ]
    except Exception as e:
        logger.debug("Failed to get network traffic: %s", e)
        result["_errors"] = result.get("_errors", []) + ["traffic"]

    return result


def _detect_system_hardware() -> dict[str, Any]:
    """Detect system hardware for model recommendations."""
    result = {
        "ram_gb": 0,
        "gpu_available": False,
        "gpu_name": None,
        "gpu_vram_gb": None,
        "gpu_type": None,  # "nvidia", "amd", "apple", None
        "recommended_max_params": "3b",  # Conservative default
    }

    # Detect RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    result["ram_gb"] = round(kb / 1024 / 1024, 1)
                    break
    except Exception as e:
        logger.debug("Failed to detect RAM from /proc/meminfo: %s", e)

    # Detect NVIDIA GPU
    try:
        nvidia_out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if nvidia_out.returncode == 0 and nvidia_out.stdout.strip():
            lines = nvidia_out.stdout.strip().split("\n")
            if lines:
                parts = lines[0].split(", ")
                if len(parts) >= 2:
                    result["gpu_available"] = True
                    result["gpu_type"] = "nvidia"
                    result["gpu_name"] = parts[0].strip()
                    result["gpu_vram_gb"] = round(int(parts[1]) / 1024, 1)
    except FileNotFoundError:
        logger.debug("nvidia-smi not found - no NVIDIA GPU detected")
    except Exception as e:
        logger.debug("Failed to detect NVIDIA GPU: %s", e)

    # Detect AMD GPU (ROCm)
    if not result["gpu_available"]:
        try:
            rocm_out = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=5
            )
            if rocm_out.returncode == 0 and "GPU" in rocm_out.stdout:
                result["gpu_available"] = True
                result["gpu_type"] = "amd"
                result["gpu_name"] = "AMD GPU (ROCm)"
                # Parse VRAM from rocm-smi output (format varies)
                for line in rocm_out.stdout.split("\n"):
                    if "Total" in line and "MB" in line:
                        try:
                            mb = int("".join(filter(str.isdigit, line.split("Total")[1].split("MB")[0])))
                            result["gpu_vram_gb"] = round(mb / 1024, 1)
                        except (ValueError, IndexError) as e:
                            logger.debug("Failed to parse ROCm VRAM: %s", e)
        except FileNotFoundError:
            logger.debug("rocm-smi not found - no AMD GPU detected")
        except Exception as e:
            logger.debug("Failed to detect AMD GPU: %s", e)

    # Calculate recommended max parameters based on available memory
    gpu_mem = result["gpu_vram_gb"] or 0
    ram_mem = result["ram_gb"] or 0
    available_mem = max(gpu_mem, ram_mem)

    if available_mem:
        if available_mem >= 128:
            result["recommended_max_params"] = "405b"
        elif available_mem >= 64:
            result["recommended_max_params"] = "70b"
        elif available_mem >= 32:
            result["recommended_max_params"] = "34b"
        elif available_mem >= 16:
            result["recommended_max_params"] = "13b"
        elif available_mem >= 8:
            result["recommended_max_params"] = "8b"
        elif available_mem >= 6:
            result["recommended_max_params"] = "7b"
        elif available_mem >= 4:
            result["recommended_max_params"] = "3b"
        else:
            result["recommended_max_params"] = "1b"

    return result


@register("system/hardware", needs_db=True)
def handle_hardware(db: Database) -> dict[str, Any]:
    """Get system hardware info for model recommendations."""
    return _detect_system_hardware()


@register("system/open-terminal", needs_db=True)
def handle_open_terminal(_db: Database) -> dict[str, Any]:
    """Open a terminal emulator window."""
    # Try common Linux terminal emulators in order of preference
    terminals = [
        ["gnome-terminal"],
        ["konsole"],
        ["xfce4-terminal"],
        ["mate-terminal"],
        ["tilix"],
        ["x-terminal-emulator"],
        ["xterm"],
    ]

    for term_cmd in terminals:
        if shutil.which(term_cmd[0]):
            try:
                # Spawn detached from parent process
                subprocess.Popen(
                    term_cmd,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {"success": True, "terminal": term_cmd[0]}
            except Exception as e:
                logger.warning(f"Failed to launch {term_cmd[0]}: {e}")
                continue

    return {"success": False, "error": "No terminal emulator found"}


# -------------------------------------------------------------------------
# Service management handlers
# -------------------------------------------------------------------------


@register("service/action", needs_db=True)
def handle_service_action(
    db: Database,
    *,
    name: str,
    action: str,
) -> dict[str, Any]:
    """Perform an action on a systemd service."""
    from reos import linux_tools

    # SECURITY: Validate service name to prevent command injection
    try:
        name = validate_service_name(name)
    except ValidationError as e:
        audit_log(AuditEventType.VALIDATION_FAILED, {"field": "name", "value": name[:50], "error": e.message})
        raise RpcError(code=INVALID_PARAMS, message=e.message)

    valid_actions = {"start", "stop", "restart", "status", "logs"}
    if action not in valid_actions:
        raise RpcError(code=INVALID_PARAMS, message=f"Invalid action: {action}. Must be one of: {', '.join(valid_actions)}")

    # SECURITY: Rate limit service operations
    try:
        check_rate_limit("service")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "service", "action": action})
        raise RpcError(code=-32429, message=str(e))

    # SECURITY: Escape service name for shell (defense in depth)
    safe_name = escape_shell_arg(name)

    # For logs, return recent journal entries
    if action == "logs":
        try:
            result = linux_tools.execute_command(f"journalctl -u {safe_name} -n 50 --no-pager")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "command": f"journalctl -u {name}",
                "action": action,
                "return_code": result.returncode,
            }, success=result.returncode == 0)
            return {
                "ok": result.returncode == 0,
                "logs": result.stdout if result.stdout else result.stderr,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For status, just check the service
    if action == "status":
        try:
            result = linux_tools.execute_command(f"systemctl status {safe_name} --no-pager")
            return {
                "ok": True,
                "status": result.stdout if result.stdout else result.stderr,
                "active": result.returncode == 0,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For start/stop/restart, create an approval request
    approval_id = uuid.uuid4().hex[:12]
    command = f"sudo systemctl {action} {safe_name}"

    db.create_approval(
        approval_id=approval_id,
        conversation_id="system",
        command=command,
        explanation=f"{action.capitalize()} the {name} service",
        risk_level="medium",
    )

    audit_log(AuditEventType.APPROVAL_REQUESTED, {
        "approval_id": approval_id,
        "command": command,
        "service": name,
        "action": action,
    })

    return {
        "requires_approval": True,
        "approval_id": approval_id,
        "command": command,
        "message": f"Service {action} requires approval",
    }


@register("container/action", needs_db=True)
def handle_container_action(
    db: Database,
    *,
    container_id: str,
    action: str,
) -> dict[str, Any]:
    """Perform an action on a Docker container."""
    from reos import linux_tools

    # SECURITY: Validate container ID to prevent command injection
    try:
        container_id = validate_container_id(container_id)
    except ValidationError as e:
        audit_log(AuditEventType.VALIDATION_FAILED, {"field": "container_id", "value": container_id[:50], "error": e.message})
        raise RpcError(code=INVALID_PARAMS, message=e.message)

    valid_actions = {"start", "stop", "restart", "logs"}
    if action not in valid_actions:
        raise RpcError(code=INVALID_PARAMS, message=f"Invalid action: {action}. Must be one of: {', '.join(valid_actions)}")

    # SECURITY: Rate limit container operations
    try:
        check_rate_limit("container")
    except RateLimitExceeded as e:
        audit_log(AuditEventType.RATE_LIMIT_EXCEEDED, {"category": "container", "action": action})
        raise RpcError(code=-32429, message=str(e))

    # SECURITY: Escape container ID for shell (defense in depth)
    safe_id = escape_shell_arg(container_id)

    # For logs, return recent container logs
    if action == "logs":
        try:
            result = linux_tools.execute_command(f"docker logs --tail 50 {safe_id}")
            audit_log(AuditEventType.COMMAND_EXECUTED, {
                "command": f"docker logs {container_id}",
                "action": action,
                "return_code": result.returncode,
            }, success=result.returncode == 0)
            return {
                "ok": result.returncode == 0,
                "logs": result.stdout if result.stdout else result.stderr,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # For start/stop/restart
    try:
        result = linux_tools.execute_command(f"docker {action} {safe_id}")
        audit_log(AuditEventType.COMMAND_EXECUTED, {
            "command": f"docker {action} {container_id}",
            "action": action,
            "return_code": result.returncode,
        }, success=result.returncode == 0)
        return {
            "ok": result.returncode == 0,
            "message": result.stdout if result.stdout else f"Container {action} completed",
            "error": result.stderr if result.returncode != 0 else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -------------------------------------------------------------------------
# State handlers
# -------------------------------------------------------------------------


@register("state/get", needs_db=True)
def handle_state_get(db: Database, *, key: str) -> dict[str, Any]:
    """Get a key-value from the state store."""
    return {"key": key, "value": db.get_state(key=key)}


@register("state/set", needs_db=True)
def handle_state_set(db: Database, *, key: str, value: str | None) -> dict[str, Any]:
    """Set a key-value in the state store."""
    db.set_state(key=key, value=value)
    return {"ok": True}


# -------------------------------------------------------------------------
# Persona handlers
# -------------------------------------------------------------------------


@register("personas/list", needs_db=True)
def handle_personas_list(db: Database) -> dict[str, Any]:
    """List all agent personas."""
    return {"personas": db.iter_agent_personas(), "active_persona_id": db.get_active_persona_id()}


@register("personas/get", needs_db=True)
def handle_persona_get(db: Database, *, persona_id: str) -> dict[str, Any]:
    """Get a specific persona by ID."""
    persona = db.get_agent_persona(persona_id=persona_id)
    return {"persona": persona}


@register("personas/upsert", needs_db=True)
def handle_persona_upsert(db: Database, *, persona: dict[str, Any]) -> dict[str, Any]:
    """Create or update a persona."""
    required = {
        "id",
        "name",
        "system_prompt",
        "default_context",
        "temperature",
        "top_p",
        "tool_call_limit",
    }
    missing = sorted(required - set(persona.keys()))
    if missing:
        raise RpcError(code=INVALID_PARAMS, message=f"persona missing fields: {', '.join(missing)}")

    db.upsert_agent_persona(
        persona_id=str(persona["id"]),
        name=str(persona["name"]),
        system_prompt=str(persona["system_prompt"]),
        default_context=str(persona["default_context"]),
        temperature=float(persona["temperature"]),
        top_p=float(persona["top_p"]),
        tool_call_limit=int(persona["tool_call_limit"]),
    )
    return {"ok": True}


@register("personas/set_active", needs_db=True)
def handle_persona_set_active(db: Database, *, persona_id: str | None) -> dict[str, Any]:
    """Set the active persona."""
    if persona_id is not None and not isinstance(persona_id, str):
        raise RpcError(code=INVALID_PARAMS, message="persona_id must be a string or null")
    db.set_active_persona_id(persona_id=persona_id)
    return {"ok": True}
