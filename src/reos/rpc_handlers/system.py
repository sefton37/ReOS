"""System, Thunderbird, and Autostart RPC handlers.

These handlers manage system dashboard state, Thunderbird
calendar/contact integration, and autostart settings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from reos.db import Database

from . import RpcError
from .play import get_current_play_path


logger = logging.getLogger(__name__)


# =============================================================================
# System Dashboard Handlers
# =============================================================================


def handle_system_live_state(db: Database) -> dict[str, Any]:
    """Get comprehensive system state for dashboard."""
    from reos import linux_tools

    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "cpu_model": "Unknown",
        "cpu_cores": 0,
        "memory": {"used_mb": 0, "total_mb": 0, "percent": 0.0},
        "disks": [],
        "load_avg": [0.0, 0.0, 0.0],
        "gpu": None,
        "services": [],
        "containers": [],
        "network": [],
        "ports": [],
        "traffic": [],
    }

    # Get system info
    try:
        info = linux_tools.get_system_info()
        result["cpu_percent"] = info.cpu_percent
        result["cpu_model"] = info.cpu_model
        result["cpu_cores"] = info.cpu_cores
        result["memory"] = {
            "used_mb": info.memory_used_mb,
            "total_mb": info.memory_total_mb,
            "percent": info.memory_percent,
        }
        result["disks"] = [
            {
                "mount": "/",
                "used_gb": info.disk_used_gb,
                "total_gb": info.disk_total_gb,
                "percent": info.disk_percent,
            }
        ]
        result["load_avg"] = list(info.load_avg)
        # Add GPU info if available
        if info.gpu_name is not None:
            result["gpu"] = {
                "name": info.gpu_name,
                "percent": info.gpu_percent,
                "memory_used_mb": info.gpu_memory_used_mb,
                "memory_total_mb": info.gpu_memory_total_mb,
            }
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


# =============================================================================
# Thunderbird Integration Handlers
# =============================================================================


def handle_cairn_thunderbird_status(_db: Database) -> dict[str, Any]:
    """Check if Thunderbird integration is available."""
    from reos.cairn.thunderbird import ThunderbirdBridge

    bridge = ThunderbirdBridge.auto_detect()
    if bridge is None:
        return {
            "available": False,
            "message": "Thunderbird profile not detected. Install Thunderbird and create a profile to enable calendar and contact integration.",
        }

    status = bridge.get_status()
    return {
        "available": True,
        "profile_path": str(bridge.config.profile_path),
        "has_contacts": status.get("contacts_available", False),
        "has_calendar": status.get("calendar_available", False),
        "contact_count": status.get("contact_count", 0),
    }


def handle_thunderbird_check(db: Database) -> dict[str, Any]:
    """Check Thunderbird installation and discover profiles."""
    from reos.cairn.thunderbird import (
        get_thunderbird_integration_state,
        ThunderbirdProfile,
        ThunderbirdAccount,
    )
    from reos.cairn.store import CairnStore

    # Get integration state from Thunderbird
    integration = get_thunderbird_integration_state()

    # Get stored preferences
    play_path = get_current_play_path(db)
    if play_path:
        store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
        stored_state = store.get_integration_state("thunderbird")
    else:
        stored_state = None

    # Determine integration state
    if stored_state and stored_state["state"] == "declined":
        state = "declined"
    elif stored_state and stored_state["state"] == "active":
        state = "active"
    else:
        state = "not_configured"

    # Serialize profiles
    def serialize_account(acc: ThunderbirdAccount) -> dict:
        return {
            "id": acc.id,
            "name": acc.name,
            "email": acc.email,
            "type": acc.type,
            "server": acc.server,
            "calendars": acc.calendars,
            "address_books": acc.address_books,
        }

    def serialize_profile(prof: ThunderbirdProfile) -> dict:
        return {
            "name": prof.name,
            "path": str(prof.path),
            "is_default": prof.is_default,
            "accounts": [serialize_account(a) for a in prof.accounts],
        }

    return {
        "installed": integration.installed,
        "install_suggestion": integration.install_suggestion,
        "profiles": [serialize_profile(p) for p in integration.profiles],
        "integration_state": state,
        "active_profiles": stored_state["config"].get("active_profiles", []) if stored_state and stored_state["config"] else [],
    }


def handle_thunderbird_configure(
    db: Database,
    *,
    active_profiles: list[str],
    active_accounts: list[str] | None = None,
    all_active: bool = False,
) -> dict[str, Any]:
    """Configure Thunderbird integration."""
    from reos.cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")

    config = {
        "active_profiles": active_profiles,
        "active_accounts": active_accounts or [],
        "all_active": all_active,
    }

    store.set_integration_active("thunderbird", config)

    return {"success": True, "config": config}


def handle_thunderbird_decline(db: Database) -> dict[str, Any]:
    """Mark Thunderbird integration as declined (never ask again)."""
    from reos.cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
    store.set_integration_declined("thunderbird")

    return {"success": True}


def handle_thunderbird_reset(db: Database) -> dict[str, Any]:
    """Reset Thunderbird integration (re-enable prompts)."""
    from reos.cairn.store import CairnStore

    play_path = get_current_play_path(db)
    if not play_path:
        raise RpcError(code=-32000, message="No Play path configured")

    store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
    store.clear_integration_decline("thunderbird")

    return {"success": True}


# =============================================================================
# Autostart Handlers
# =============================================================================


def handle_autostart_get(_db: Database) -> dict[str, Any]:
    """Get current autostart status for Talking Rock."""
    from reos.autostart import get_autostart_status

    return get_autostart_status()


def handle_autostart_set(_db: Database, *, enabled: bool) -> dict[str, Any]:
    """Enable or disable autostart for Talking Rock.

    Args:
        enabled: True to start Talking Rock on login, False to disable.
    """
    from reos.autostart import set_autostart

    return set_autostart(enabled)


# =============================================================================
# Open Terminal Handler
# =============================================================================


def handle_system_open_terminal(_db: Database) -> dict[str, Any]:
    """Open a terminal window in the user's preferred terminal emulator."""
    import shutil
    import subprocess

    # Common terminal emulators in preference order
    terminals = [
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "mate-terminal",
        "tilix",
        "terminator",
        "alacritty",
        "kitty",
        "xterm",
    ]

    for terminal in terminals:
        if shutil.which(terminal):
            try:
                subprocess.Popen([terminal], start_new_session=True)
                return {"success": True, "terminal": terminal}
            except Exception as e:
                logger.warning("Failed to launch %s: %s", terminal, e)
                continue

    return {
        "success": False,
        "error": "No supported terminal emulator found. Install gnome-terminal, konsole, or another terminal.",
    }


# =============================================================================
# CAIRN Attention Handler
# =============================================================================


def handle_cairn_attention(
    db: Database,
    *,
    hours: int = 168,  # 7 days
    limit: int = 10,
) -> dict[str, Any]:
    """Get items that need attention - primarily upcoming calendar events.

    Shows the next 7 days by default for the 'What Needs My Attention' section.
    """
    from reos.cairn.store import CairnStore
    from reos.cairn.surfacing import CairnSurfacer
    from reos.cairn.thunderbird import ThunderbirdBridge
    from reos import play_fs

    play_path = get_current_play_path(db)
    if not play_path:
        return {"count": 0, "items": []}

    # Set up CAIRN components
    cairn_db_path = Path(play_path) / ".cairn" / "cairn.db"
    store = CairnStore(cairn_db_path)

    # Get Thunderbird bridge if configured
    thunderbird = None
    tb_state = store.get_integration_state("thunderbird")
    if tb_state and tb_state["state"] == "active":
        thunderbird = ThunderbirdBridge.auto_detect()

    # Create surfacer and get attention items
    surfacer = CairnSurfacer(
        cairn_store=store,
        thunderbird=thunderbird,
    )

    items = surfacer.surface_attention(hours=hours, limit=limit)

    # Build act_id -> title/color lookup from play_fs
    acts, _ = play_fs.list_acts()
    act_info = {a.act_id: {"title": a.title, "color": a.color} for a in acts}

    return {
        "count": len(items),
        "items": [
            {
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "title": item.title,
                "reason": item.reason,
                "urgency": item.urgency,
                "calendar_start": item.calendar_start.isoformat() if item.calendar_start else None,
                "calendar_end": item.calendar_end.isoformat() if item.calendar_end else None,
                "is_recurring": item.is_recurring,
                "recurrence_frequency": item.recurrence_frequency,
                "next_occurrence": item.next_occurrence.isoformat() if item.next_occurrence else None,
                "act_id": item.act_id,
                "scene_id": item.scene_id,
                "act_title": act_info.get(item.act_id, {}).get("title") if item.act_id else None,
                "act_color": act_info.get(item.act_id, {}).get("color") if item.act_id else None,
            }
            for item in items
        ],
    }


# =============================================================================
# Debug Log Handler
# =============================================================================


def handle_debug_log(_db: Database, *, msg: str) -> dict[str, Any]:
    """Log a debug message from the frontend to stderr."""
    import sys
    print(f"[JS] {msg}", file=sys.stderr, flush=True)
    return {"ok": True}
