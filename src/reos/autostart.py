"""Autostart manager for Talking Rock on Ubuntu/Linux.

Manages the XDG autostart .desktop file in ~/.config/autostart/ to enable
or disable starting Talking Rock automatically when the user logs in.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# XDG autostart directory
AUTOSTART_DIR = Path.home() / ".config" / "autostart"

# Desktop file name
DESKTOP_FILE_NAME = "talking-rock.desktop"

# Full path to desktop file
DESKTOP_FILE_PATH = AUTOSTART_DIR / DESKTOP_FILE_NAME


def _get_reos_executable() -> str:
    """Get the path to the reos executable.

    Returns:
        Absolute path to the reos launcher script.
    """
    # The reos script is at the root of the ReOS repository
    # We can find it relative to this module
    module_path = Path(__file__).resolve()
    # Go up from src/reos/autostart.py to repo root
    repo_root = module_path.parent.parent.parent
    reos_path = repo_root / "reos"

    if reos_path.exists():
        return str(reos_path)

    # Fallback: check if installed system-wide
    import shutil

    system_reos = shutil.which("reos")
    if system_reos:
        return system_reos

    # Last resort: return the expected path even if not found
    return str(reos_path)


def _generate_desktop_content() -> str:
    """Generate the .desktop file content.

    Returns:
        Complete .desktop file content.
    """
    reos_path = _get_reos_executable()

    return f"""[Desktop Entry]
Type=Application
Name=Talking Rock
Comment=Your Linux assistant - Start automatically on login
Exec={reos_path} --ui tauri
Icon=assistant
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""


def is_autostart_enabled() -> bool:
    """Check if autostart is currently enabled.

    Returns:
        True if the autostart desktop file exists and is enabled.
    """
    if not DESKTOP_FILE_PATH.exists():
        return False

    # Check if the file is disabled via X-GNOME-Autostart-enabled=false
    try:
        content = DESKTOP_FILE_PATH.read_text()
        # If explicitly disabled, return False
        if "X-GNOME-Autostart-enabled=false" in content:
            return False
        # If file exists and not explicitly disabled, it's enabled
        return True
    except OSError as e:
        logger.warning("Failed to read autostart file: %s", e)
        return False


def enable_autostart() -> dict:
    """Enable autostart for Talking Rock.

    Creates or updates the .desktop file in ~/.config/autostart/.

    Returns:
        Result dict with success status and any error message.
    """
    try:
        # Ensure autostart directory exists
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)

        # Write the desktop file
        content = _generate_desktop_content()
        DESKTOP_FILE_PATH.write_text(content)

        # Make it executable (some desktop environments require this)
        os.chmod(DESKTOP_FILE_PATH, 0o755)

        logger.info("Autostart enabled: %s", DESKTOP_FILE_PATH)
        return {
            "success": True,
            "enabled": True,
            "path": str(DESKTOP_FILE_PATH),
        }

    except OSError as e:
        logger.error("Failed to enable autostart: %s", e)
        return {
            "success": False,
            "enabled": False,
            "error": str(e),
        }


def disable_autostart() -> dict:
    """Disable autostart for Talking Rock.

    Removes the .desktop file from ~/.config/autostart/.

    Returns:
        Result dict with success status and any error message.
    """
    try:
        if DESKTOP_FILE_PATH.exists():
            DESKTOP_FILE_PATH.unlink()
            logger.info("Autostart disabled: removed %s", DESKTOP_FILE_PATH)

        return {
            "success": True,
            "enabled": False,
        }

    except OSError as e:
        logger.error("Failed to disable autostart: %s", e)
        return {
            "success": False,
            "enabled": is_autostart_enabled(),  # Return current state
            "error": str(e),
        }


def set_autostart(enabled: bool) -> dict:
    """Set autostart state.

    Args:
        enabled: True to enable autostart, False to disable.

    Returns:
        Result dict with success status and current state.
    """
    if enabled:
        return enable_autostart()
    else:
        return disable_autostart()


def get_autostart_status() -> dict:
    """Get current autostart status.

    Returns:
        Status dict with enabled state and desktop file path.
    """
    enabled = is_autostart_enabled()
    reos_path = _get_reos_executable()

    return {
        "enabled": enabled,
        "desktop_file": str(DESKTOP_FILE_PATH),
        "reos_executable": reos_path,
        "reos_exists": Path(reos_path).exists(),
    }
