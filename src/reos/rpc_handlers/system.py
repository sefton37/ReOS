"""ReOS system vitals RPC handlers.

Thin wrappers over linux_tools functions, serialized for JSON-RPC transport
to the Cairn Tauri frontend. The dashboard polls these every 5 seconds.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)


def handle_reos_vitals(db: Any = None) -> dict[str, Any]:
    """Return live system vitals for the dashboard.

    Called every 5 seconds by the frontend. Must be fast and non-blocking.
    Core vitals use /proc reads and os.statvfs. Network and container data
    use subprocess calls with short timeouts.
    The db param is unused (Cairn dispatch compatibility).
    """
    from dataclasses import asdict as _asdict

    from reos.linux_tools import get_system_info

    try:
        info = get_system_info()
        result = asdict(info)
    except Exception as e:
        logger.warning("Failed to get system vitals: %s", e)
        result = {
            "hostname": "unknown",
            "kernel": "unknown",
            "distro": "unknown",
            "uptime": "unknown",
            "cpu_model": "unknown",
            "cpu_cores": 0,
            "cpu_percent": 0.0,
            "memory_total_mb": 0,
            "memory_used_mb": 0,
            "memory_percent": 0.0,
            "disk_total_gb": 0.0,
            "disk_used_gb": 0.0,
            "disk_percent": 0.0,
            "load_avg": [0.0, 0.0, 0.0],
            "gpu_name": None,
            "gpu_percent": None,
            "gpu_memory_used_mb": None,
            "gpu_memory_total_mb": None,
            "package_manager": None,
            "active_service_count": None,
        }

    # Network interfaces and traffic
    try:
        from reos.linux_tools import get_network_info, get_network_traffic

        interfaces = get_network_info()
        traffic_list = get_network_traffic()
        traffic_by_iface = {t.interface: _asdict(t) for t in traffic_list}

        network = []
        for name, info_dict in interfaces.items():
            if name == "lo":
                continue
            entry: dict[str, Any] = {
                "name": name,
                "state": info_dict.get("state", "unknown"),
                "mac": info_dict.get("mac"),
                "addresses": info_dict.get("addresses", []),
            }
            if name in traffic_by_iface:
                t = traffic_by_iface[name]
                entry["rx_bytes"] = t["rx_bytes"]
                entry["tx_bytes"] = t["tx_bytes"]
                entry["rx_packets"] = t["rx_packets"]
                entry["tx_packets"] = t["tx_packets"]
                entry["rx_errors"] = t["rx_errors"]
                entry["tx_errors"] = t["tx_errors"]
            network.append(entry)
        result["network"] = network
    except Exception as e:
        logger.warning("Failed to get network info: %s", e)
        result["network"] = []

    # Containers (Docker / Podman)
    try:
        from reos.linux_tools import detect_container_runtime, list_containers

        runtime = detect_container_runtime()
        if runtime:
            containers_raw = list_containers(all_containers=True)
            result["containers"] = {
                "runtime": runtime,
                "items": containers_raw,
            }
        else:
            result["containers"] = None
    except Exception as e:
        logger.warning("Failed to get container info: %s", e)
        result["containers"] = None

    # Package manager (for context sidebar)
    try:
        import shutil as _shutil

        for _pm in ("apt", "dnf", "pacman", "zypper"):
            if _shutil.which(_pm):
                result["package_manager"] = _pm
                break
        else:
            result["package_manager"] = "unknown"
    except Exception:
        result["package_manager"] = None

    # Active service count (for context sidebar)
    try:
        import subprocess as _sp

        _r = _sp.run(
            ["systemctl", "list-units", "--type=service", "--state=active",
             "--no-legend", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        result["active_service_count"] = len(
            [line for line in _r.stdout.splitlines() if line.strip()]
        )
    except Exception:
        result["active_service_count"] = None

    return result
