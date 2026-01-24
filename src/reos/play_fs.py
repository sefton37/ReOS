from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .session import get_current_crypto_storage
from .settings import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Constants for "Your Story" Act and Stage Direction
# =============================================================================

YOUR_STORY_ACT_ID = "your-story"
STAGE_DIRECTION_SCENE_ID_PREFIX = "stage-direction-"


def _get_stage_direction_scene_id(act_id: str) -> str:
    """Get the Stage Direction scene ID for an Act."""
    return f"{STAGE_DIRECTION_SCENE_ID_PREFIX}{act_id[:12]}"


class SceneStage(Enum):
    """The stage/state of a Scene in The Play.

    Scenes progress through these stages:
    - PLANNING: No date set, still being organized
    - IN_PROGRESS: Has a date, actively working on it
    - AWAITING_DATA: Waiting for external input/data
    - COMPLETE: Done
    """
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    AWAITING_DATA = "awaiting_data"
    COMPLETE = "complete"


# Backward compatibility alias
BeatStage = SceneStage


# Color palette for Acts - visually distinct colors that work well in UI
# Each color is a tuple of (background_rgba, text_hex) for light theme compatibility
ACT_COLOR_PALETTE: list[str] = [
    "#8b5cf6",  # Purple (violet-500)
    "#3b82f6",  # Blue (blue-500)
    "#10b981",  # Green (emerald-500)
    "#f59e0b",  # Amber (amber-500)
    "#ef4444",  # Red (red-500)
    "#ec4899",  # Pink (pink-500)
    "#06b6d4",  # Cyan (cyan-500)
    "#84cc16",  # Lime (lime-500)
    "#f97316",  # Orange (orange-500)
    "#6366f1",  # Indigo (indigo-500)
    "#14b8a6",  # Teal (teal-500)
    "#a855f7",  # Fuchsia (purple-500)
]


@dataclass(frozen=True)
class Act:
    """An Act in The Play - a major phase or project.

    When repo_path is set, this Act is in "Code Mode" - ReOS will
    automatically detect code-related requests and provide agentic
    coding capabilities sandboxed to the assigned repository.
    """
    act_id: str
    title: str
    active: bool = False
    notes: str = ""
    color: str | None = None               # Hex color for UI display (e.g., "#8b5cf6")
    # Code Mode fields
    repo_path: str | None = None           # Absolute path to git repo
    artifact_type: str | None = None       # "python", "typescript", "rust", etc.
    code_config: dict[str, Any] | None = None  # Per-Act code configuration


@dataclass(frozen=True)
class Scene:
    """A Scene in The Play - an atomic task or event.

    Scenes can be linked to calendar events. For recurring events,
    ONE Scene represents the entire series (not expanded occurrences).

    Calendar integration fields:
    - calendar_event_id: Inbound sync - ID of the Thunderbird event this Scene reflects
    - thunderbird_event_id: Outbound sync - ID of the Thunderbird event created for this Scene
    """
    scene_id: str
    act_id: str  # Parent Act ID
    title: str
    stage: str  # SceneStage value
    notes: str
    link: str | None = None
    # Calendar integration fields
    calendar_event_id: str | None = None      # Inbound sync: TB event that Scene reflects
    recurrence_rule: str | None = None        # RRULE string if recurring
    thunderbird_event_id: str | None = None   # Outbound sync: TB event created for Scene


@dataclass(frozen=True)
class Beat:
    """Backward compatibility alias for Scene.

    DEPRECATED: Use Scene instead. Beats have been merged into Scenes in v4.
    """
    beat_id: str
    title: str
    stage: str  # SceneStage value
    notes: str
    link: str | None = None
    # Calendar integration fields
    calendar_event_id: str | None = None
    recurrence_rule: str | None = None
    thunderbird_event_id: str | None = None


@dataclass(frozen=True)
class FileAttachment:
    """A file attachment reference (stores path only, not file content)."""
    attachment_id: str
    file_path: str      # Absolute path on disk
    file_name: str      # Display name
    file_type: str      # Extension (pdf, docx, etc.)
    added_at: str       # ISO timestamp


def play_root() -> Path:
    """Return the on-disk root for the theatrical model.

    If running with an authenticated session, uses per-user isolated storage
    at ~/.reos-data/{username}/play. Otherwise falls back to the repo-local
    .reos-data/ directory.

    Security:
        - Per-user data isolation when session context is active
        - Data can optionally be encrypted via CryptoStorage
    """
    # Check for per-user session context
    crypto = get_current_crypto_storage()
    if crypto is not None:
        # Use per-user isolated storage
        return crypto.user_data_root / "play"

    # Fallback to default location (development/unauthenticated mode)
    base = Path(os.environ["REOS_DATA_DIR"]) if os.environ.get("REOS_DATA_DIR") else settings.data_dir
    return base / "play"


def _acts_path() -> Path:
    return play_root() / "acts.json"


def _me_path() -> Path:
    return play_root() / "me.md"


def _act_dir(act_id: str) -> Path:
    return play_root() / "acts" / act_id


def _scenes_path(act_id: str) -> Path:
    return _act_dir(act_id) / "scenes.json"


def ensure_play_skeleton() -> None:
    root = play_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "acts").mkdir(parents=True, exist_ok=True)

    me = _me_path()
    if not me.exists():
        me.write_text(
            "# Me (The Play)\n\n"
            "Personal facts, principles, constraints, and identity-level context.\n"
            "\n"
            "This is read-mostly and slow-changing. It is not a task list.\n",
            encoding="utf-8",
        )

    acts = _acts_path()
    if not acts.exists():
        acts.write_text(json.dumps({"acts": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_stage_direction_scene(act_id: str) -> None:
    """Ensure an Act has a Stage Direction scene as its first scene.

    DEPRECATED: With SQLite backend, this is handled automatically in play_db.
    Kept for backward compatibility.
    """
    pass  # No-op - SQLite backend handles this automatically


def ensure_your_story_act() -> tuple[list["Act"], str]:
    """Ensure 'Your Story' Act exists.

    'Your Story' is a special default Act that always exists. All other Acts
    relate to it conceptually (life projects vs. the story of your life).

    Returns:
        Tuple of (all acts, your_story_act_id).
    """
    from . import play_db
    acts_data, your_story_id = play_db.ensure_your_story_act()
    # Ensure directory exists for KB files
    _act_dir(YOUR_STORY_ACT_ID).mkdir(parents=True, exist_ok=True)
    return [_dict_to_act(d) for d in acts_data], your_story_id


def read_me_markdown() -> str:
    ensure_play_skeleton()
    return _me_path().read_text(encoding="utf-8", errors="replace")


def write_me_markdown(text: str) -> None:
    """Write the me.md file (Your Story / Play level content)."""
    ensure_play_skeleton()
    _me_path().write_text(text, encoding="utf-8")




def _dict_to_act(d: dict[str, Any]) -> Act:
    """Convert a dict to an Act dataclass."""
    return Act(
        act_id=d.get("act_id", ""),
        title=d.get("title", ""),
        active=bool(d.get("active", False)),
        notes=d.get("notes", ""),
        color=d.get("color"),
        repo_path=d.get("repo_path"),
        artifact_type=d.get("artifact_type"),
        code_config=d.get("code_config"),
    )


def _dict_to_scene(d: dict[str, Any]) -> Scene:
    """Convert a dict to a Scene dataclass (v4 structure)."""
    return Scene(
        scene_id=d.get("scene_id", ""),
        act_id=d.get("act_id", ""),
        title=d.get("title", ""),
        stage=d.get("stage", SceneStage.PLANNING.value),
        notes=d.get("notes", ""),
        link=d.get("link"),
        calendar_event_id=d.get("calendar_event_id"),
        recurrence_rule=d.get("recurrence_rule"),
        thunderbird_event_id=d.get("thunderbird_event_id"),
    )


def _dict_to_beat(d: dict[str, Any]) -> Beat:
    """Convert a dict to a Beat dataclass (backward compat)."""
    return Beat(
        beat_id=d.get("beat_id", d.get("scene_id", "")),  # Accept either
        title=d.get("title", ""),
        stage=d.get("stage", SceneStage.PLANNING.value),
        notes=d.get("notes", ""),
        link=d.get("link"),
        calendar_event_id=d.get("calendar_event_id"),
        recurrence_rule=d.get("recurrence_rule"),
        thunderbird_event_id=d.get("thunderbird_event_id"),
    )


def list_acts() -> tuple[list[Act], str | None]:
    """List all Acts and return the active Act ID."""
    from . import play_db
    acts_data, active_id = play_db.list_acts()
    acts = [_dict_to_act(d) for d in acts_data]
    return acts, active_id




def set_active_act_id(*, act_id: str | None) -> tuple[list[Act], str | None]:
    """Set the active act, or clear it if act_id is None."""
    from . import play_db
    acts_data, active_id = play_db.set_active_act(act_id)
    acts = [_dict_to_act(d) for d in acts_data]
    return acts, active_id


def list_scenes(*, act_id: str) -> list[Scene]:
    """List all Scenes for an Act."""
    from . import play_db
    scenes_data = play_db.list_scenes(act_id)
    return [_dict_to_scene(d) for d in scenes_data]


def list_beats(*, act_id: str, scene_id: str) -> list[Beat]:
    """List all Beats for a Scene."""
    from . import play_db
    beats_data = play_db.list_beats(act_id, scene_id)
    return [_dict_to_beat(d) for d in beats_data]


def find_scene_location(scene_id: str) -> dict[str, str | None] | None:
    """Find the Act containing a Scene.

    This is the CANONICAL source for scene location - never cache this elsewhere.

    Args:
        scene_id: The Scene ID to find.

    Returns:
        Dict with act_id, act_title, scene_id, or None if not found.
    """
    from . import play_db
    return play_db.find_scene_location(scene_id)


def find_beat_location(beat_id: str) -> dict[str, str | None] | None:
    """Backward compatibility wrapper - finds a scene by beat_id.

    DEPRECATED: Use find_scene_location instead.
    """
    return find_scene_location(beat_id)


def _validate_id(*, name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(part in value for part in ("/", "\\", "..")):
        raise ValueError(f"invalid {name}")


def _pick_unused_color(existing_acts: list[Act]) -> str:
    """Pick a color from the palette that's not already in use.

    If all colors are used, returns the first color in the palette.
    Prefers colors that are most different from existing ones.
    """
    used_colors = {a.color for a in existing_acts if a.color}

    # Find unused colors
    unused = [c for c in ACT_COLOR_PALETTE if c not in used_colors]

    if unused:
        # Return the first unused color (maintains consistent assignment order)
        return unused[0]

    # All colors used - just return the first one
    return ACT_COLOR_PALETTE[0]


def create_act(*, title: str, notes: str = "", color: str | None = None) -> tuple[list[Act], str]:
    """Create a new Act.

    - Generates a stable act_id.
    - If no act is active yet, the new act becomes active.
    - Auto-assigns a color from the palette if not specified.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")

    # Auto-assign color if not provided
    if color is None:
        existing_acts, _ = list_acts()
        color = _pick_unused_color(existing_acts)

    from . import play_db
    acts_data, act_id = play_db.create_act(title=title.strip(), notes=notes, color=color)
    acts = [_dict_to_act(d) for d in acts_data]
    # Create directory for KB files
    _act_dir(act_id).mkdir(parents=True, exist_ok=True)
    return acts, act_id


def update_act(
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
    color: str | None = None,
) -> tuple[list[Act], str | None]:
    """Update an Act's user-editable fields including color."""
    _validate_id(name="act_id", value=act_id)

    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if color is not None and not isinstance(color, str):
        raise ValueError("color must be a string")

    from . import play_db
    acts_data, active_id = play_db.update_act(act_id=act_id, title=title, notes=notes, color=color)
    acts = [_dict_to_act(d) for d in acts_data]
    return acts, active_id


def delete_act(*, act_id: str) -> tuple[list[Act], str | None]:
    """Delete an Act and all its Scenes and Beats.

    IMPORTANT: The "Your Story" act (act_id="your-story") cannot be deleted.

    Args:
        act_id: The Act ID to delete.

    Returns:
        Tuple of (remaining acts list, active_act_id or None).

    Raises:
        ValueError: If act_id is "your-story" or not found.
    """
    _validate_id(name="act_id", value=act_id)

    # Protect "Your Story" act from deletion
    if act_id == YOUR_STORY_ACT_ID:
        raise ValueError("Cannot delete 'Your Story' act - it is a protected system act")

    from . import play_db
    import shutil

    # Delete from SQLite (cascades to scenes/beats)
    acts_data, active_id = play_db.delete_act(act_id)
    # Also delete the act's directory (KB files)
    act_dir = _act_dir(act_id)
    if act_dir.exists():
        shutil.rmtree(act_dir)
    return [_dict_to_act(d) for d in acts_data], active_id


def assign_repo_to_act(
    *,
    act_id: str,
    repo_path: str | None,
    artifact_type: str | None = None,
    code_config: dict[str, Any] | None = None,
) -> tuple[list[Act], str | None]:
    """Assign a repository to an Act, enabling Code Mode.

    Args:
        act_id: The Act to modify
        repo_path: Absolute path to git repository, or None to disable Code Mode
        artifact_type: Language/type hint (e.g., "python", "typescript")
        code_config: Per-Act code configuration

    Returns:
        Updated acts list and active_id
    """
    _validate_id(name="act_id", value=act_id)

    # Validate repo_path is a real git repo if provided
    if repo_path is not None:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            raise ValueError(f"repo_path does not exist: {repo_path}")
        if not (repo / ".git").is_dir():
            raise ValueError(f"repo_path is not a git repository: {repo_path}")
        repo_path = str(repo)  # Normalize to absolute path

    from . import play_db
    acts_data, active_id = play_db.assign_repo_to_act(
        act_id=act_id,
        repo_path=repo_path,
        artifact_type=artifact_type,
        code_config=code_config,
    )
    return [_dict_to_act(d) for d in acts_data], active_id


def configure_code_mode(
    *,
    act_id: str,
    code_config: dict[str, Any],
) -> tuple[list[Act], str | None]:
    """Update Code Mode configuration for an Act.

    Args:
        act_id: The Act to modify
        code_config: Code configuration dict (test_command, build_command, etc.)

    Returns:
        Updated acts list and active_id
    """
    _validate_id(name="act_id", value=act_id)

    if not isinstance(code_config, dict):
        raise ValueError("code_config must be a dictionary")

    from . import play_db
    acts_data, active_id = play_db.configure_code_mode(
        act_id=act_id,
        code_config=code_config,
    )
    return [_dict_to_act(d) for d in acts_data], active_id


def create_scene(
    *,
    act_id: str,
    title: str,
    stage: str = "",
    notes: str = "",
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
) -> tuple[list[Scene], str]:
    """Create a Scene under an Act.

    Args:
        act_id: The Act to add the Scene to.
        title: Scene title.
        stage: SceneStage value (planning, in_progress, awaiting_data, complete).
        notes: Optional notes.
        link: Optional external link.
        calendar_event_id: Optional calendar event ID this Scene is linked to (inbound sync).
        recurrence_rule: Optional RRULE string for recurring events.
        thunderbird_event_id: Optional Thunderbird event ID created for this Scene (outbound sync).

    Returns:
        Tuple of (list of scenes in act, new scene_id).
    """
    _validate_id(name="act_id", value=act_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(stage, str):
        raise ValueError("stage must be a string")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")
    if calendar_event_id is not None and not isinstance(calendar_event_id, str):
        raise ValueError("calendar_event_id must be a string or null")
    if recurrence_rule is not None and not isinstance(recurrence_rule, str):
        raise ValueError("recurrence_rule must be a string or null")
    if thunderbird_event_id is not None and not isinstance(thunderbird_event_id, str):
        raise ValueError("thunderbird_event_id must be a string or null")

    # Default stage to PLANNING if not specified
    if not stage:
        stage = SceneStage.PLANNING.value

    from . import play_db
    scenes_data, scene_id = play_db.create_scene(
        act_id=act_id, title=title.strip(), stage=stage, notes=notes, link=link,
        calendar_event_id=calendar_event_id, recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id
    )
    return [_dict_to_scene(d) for d in scenes_data], scene_id


def update_scene(
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
) -> list[Scene]:
    """Update a Scene's fields.

    Args:
        act_id: The Act containing the Scene.
        scene_id: The Scene to update.
        title: New title (optional).
        stage: New SceneStage value (optional).
        notes: New notes (optional).
        link: New external link (optional).
        calendar_event_id: New calendar event ID (optional).
        recurrence_rule: New recurrence rule (optional).
        thunderbird_event_id: New Thunderbird event ID (optional).
    """
    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if stage is not None and not isinstance(stage, str):
        raise ValueError("stage must be a string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")

    from . import play_db
    scenes_data = play_db.update_scene(
        act_id=act_id, scene_id=scene_id, title=title.strip() if title else None,
        stage=stage, notes=notes, link=link,
        calendar_event_id=calendar_event_id, recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id
    )
    return [_dict_to_scene(d) for d in scenes_data]


def delete_scene(*, act_id: str, scene_id: str) -> list[Scene]:
    """Delete a Scene and all its Beats.

    IMPORTANT: Stage Direction scenes cannot be deleted.

    Args:
        act_id: The parent Act ID.
        scene_id: The Scene ID to delete.

    Returns:
        List of remaining Scene objects in the act.

    Raises:
        ValueError: If scene is Stage Direction or not found.
    """
    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)

    # Protect Stage Direction scenes from deletion
    stage_direction_id = _get_stage_direction_scene_id(act_id)
    if scene_id == stage_direction_id:
        raise ValueError("Cannot delete 'Stage Direction' scene - it is a protected system scene")

    from . import play_db
    scenes_data = play_db.delete_scene(act_id, scene_id)
    return [_dict_to_scene(d) for d in scenes_data]


def move_scene(
    *,
    scene_id: str,
    source_act_id: str,
    target_act_id: str,
) -> dict[str, Any]:
    """Move a Scene to a different Act.

    Args:
        scene_id: The Scene to move.
        source_act_id: The source Act.
        target_act_id: The target Act.

    Returns:
        Dict with moved scene_id and target_act_id.

    Raises:
        ValueError: If scene or acts not found.
    """
    _validate_id(name="scene_id", value=scene_id)
    _validate_id(name="source_act_id", value=source_act_id)
    _validate_id(name="target_act_id", value=target_act_id)

    from . import play_db
    return play_db.move_scene(
        scene_id=scene_id,
        source_act_id=source_act_id,
        target_act_id=target_act_id,
    )


def create_beat(
    *,
    act_id: str,
    scene_id: str,
    title: str,
    stage: str = "",
    notes: str = "",
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
) -> list[Beat]:
    """Create a Beat under a Scene.

    Args:
        act_id: The Act containing the Scene.
        scene_id: The Scene to add the Beat to.
        title: Beat title.
        stage: BeatStage value (planning, in_progress, awaiting_data, complete).
        notes: Optional notes.
        link: Optional external link.
        calendar_event_id: Optional calendar event ID this Beat is linked to (inbound sync).
        recurrence_rule: Optional RRULE string for recurring events.
        thunderbird_event_id: Optional Thunderbird event ID created for this Beat (outbound sync).
    """
    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(stage, str):
        raise ValueError("stage must be a string")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")
    if calendar_event_id is not None and not isinstance(calendar_event_id, str):
        raise ValueError("calendar_event_id must be a string or null")
    if recurrence_rule is not None and not isinstance(recurrence_rule, str):
        raise ValueError("recurrence_rule must be a string or null")
    if thunderbird_event_id is not None and not isinstance(thunderbird_event_id, str):
        raise ValueError("thunderbird_event_id must be a string or null")

    # Default stage to PLANNING if not specified
    if not stage:
        stage = BeatStage.PLANNING.value

    from . import play_db
    beats_data, _ = play_db.create_beat(
        act_id=act_id, scene_id=scene_id, title=title.strip(),
        stage=stage, notes=notes, link=link,
        calendar_event_id=calendar_event_id, recurrence_rule=recurrence_rule,
        thunderbird_event_id=thunderbird_event_id,
    )
    return [_dict_to_beat(d) for d in beats_data]


def update_beat(
    *,
    act_id: str,
    scene_id: str,
    beat_id: str,
    title: str | None = None,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> list[Beat]:
    """Update a Beat's fields.

    Args:
        act_id: The Act containing the Beat.
        scene_id: The Scene containing the Beat.
        beat_id: The Beat to update.
        title: New title (optional).
        stage: New BeatStage value (optional).
        notes: New notes (optional).
        link: New external link (optional).
    """
    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    _validate_id(name="beat_id", value=beat_id)
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if stage is not None and not isinstance(stage, str):
        raise ValueError("stage must be a string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if link is not None and not isinstance(link, str):
        raise ValueError("link must be a string or null")

    from . import play_db
    beats_data = play_db.update_beat(
        act_id=act_id, scene_id=scene_id, beat_id=beat_id,
        title=title.strip() if title else None,
        stage=stage, notes=notes, link=link
    )
    return [_dict_to_beat(d) for d in beats_data]


def delete_beat(*, act_id: str, scene_id: str, beat_id: str) -> list[Beat]:
    """Delete a Beat from a Scene.

    Args:
        act_id: The parent Act ID.
        scene_id: The parent Scene ID.
        beat_id: The Beat ID to delete.

    Returns:
        List of remaining Beat objects in the scene.

    Raises:
        ValueError: If beat not found.
    """
    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)
    _validate_id(name="beat_id", value=beat_id)

    from . import play_db
    beats_data = play_db.delete_beat(act_id, scene_id, beat_id)
    return [_dict_to_beat(d) for d in beats_data]


def move_beat(
    *,
    beat_id: str,
    source_act_id: str,
    source_scene_id: str,
    target_act_id: str,
    target_scene_id: str,
) -> dict[str, Any]:
    """Backward compatibility wrapper - moves a scene between acts.

    DEPRECATED: Use move_scene instead. In the new 2-tier structure,
    beats are now scenes. The source_scene_id and target_scene_id
    parameters are ignored.
    """
    result = move_scene(
        scene_id=beat_id,
        source_act_id=source_act_id,
        target_act_id=target_act_id,
    )
    return {
        "beat_id": result["scene_id"],
        "target_act_id": result["target_act_id"],
        "target_scene_id": target_scene_id,  # Return for backward compat
    }


def _kb_root_for(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None) -> Path:
    _validate_id(name="act_id", value=act_id)
    base = play_root() / "kb" / "acts" / act_id
    if scene_id is None:
        return base
    _validate_id(name="scene_id", value=scene_id)
    base = base / "scenes" / scene_id
    if beat_id is None:
        return base
    _validate_id(name="beat_id", value=beat_id)
    return base / "beats" / beat_id


def _resolve_kb_file(*, kb_root: Path, rel_path: str) -> Path:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("path is required")
    p = Path(rel_path)
    if p.is_absolute():
        raise ValueError("path must be relative")
    if any(part in {"..", ""} for part in p.parts):
        raise ValueError("path escapes kb root")
    candidate = (kb_root / p).resolve()
    kb_root_resolved = kb_root.resolve()
    if candidate != kb_root_resolved and kb_root_resolved not in candidate.parents:
        raise ValueError("path escapes kb root")
    return candidate


def kb_list_files(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None) -> list[str]:
    """List markdown/text files under an item's KB root.

    The default KB file is `kb.md` (created on demand).
    """

    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    default = kb_root / "kb.md"
    if not default.exists():
        default.write_text("# KB\n\n", encoding="utf-8")

    files: list[str] = []
    for path in kb_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        files.append(path.relative_to(kb_root).as_posix())

    return sorted(set(files))


def kb_read(*, act_id: str, scene_id: str | None = None, beat_id: str | None = None, path: str = "kb.md") -> str:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)
    if not target.exists():
        if Path(path).as_posix() == "kb.md":
            target.write_text("# KB\n\n", encoding="utf-8")
        else:
            raise FileNotFoundError(path)
    return target.read_text(encoding="utf-8", errors="replace")


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kb_write_preview(
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)

    exists = target.exists() and target.is_file()
    current = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    current_sha = _sha256_text(current)
    new_sha = _sha256_text(text)

    diff_lines = difflib.unified_diff(
        current.splitlines(keepends=True),
        text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    diff = "\n".join(diff_lines)

    return {
        "exists": exists,
        "sha256_current": current_sha,
        "sha256_new": new_sha,
        "diff": diff,
    }


def kb_write_apply(
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    ensure_play_skeleton()
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    kb_root.mkdir(parents=True, exist_ok=True)
    target = _resolve_kb_file(kb_root=kb_root, rel_path=path)

    exists = target.exists() and target.is_file()
    current = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    current_sha = _sha256_text(current)
    if current_sha != expected_sha256_current:
        raise ValueError("conflict: file changed since preview")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    after_sha = _sha256_text(text)
    return {"ok": True, "sha256_current": after_sha}


# --- File Attachments (stores paths only, not file content) ---


def list_attachments(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> list[FileAttachment]:
    """List file attachments at the specified level (Play, Act, Scene, or Beat)."""
    from . import play_db
    attachments_data = play_db.list_attachments(
        act_id=act_id, scene_id=scene_id, beat_id=beat_id
    )
    return [
        FileAttachment(
            attachment_id=d["attachment_id"],
            file_path=d["file_path"],
            file_name=d["file_name"],
            file_type=d["file_type"],
            added_at=d["added_at"],
        )
        for d in attachments_data
    ]


def add_attachment(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> list[FileAttachment]:
    """Add a file attachment (stores path only, validates file exists).

    If act_id is None, adds to Play-level attachments.
    """
    if act_id is not None:
        _validate_id(name="act_id", value=act_id)
    if scene_id is not None:
        _validate_id(name="scene_id", value=scene_id)
    if beat_id is not None:
        _validate_id(name="beat_id", value=beat_id)

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("file_path is required")

    # Validate the file exists
    p = Path(file_path)
    if not p.exists():
        raise ValueError(f"file does not exist: {file_path}")
    if not p.is_file():
        raise ValueError(f"path is not a file: {file_path}")

    # Derive file_name if not provided
    if not file_name:
        file_name = p.name

    from . import play_db
    play_db.add_attachment(
        act_id=act_id, scene_id=scene_id, beat_id=beat_id,
        file_path=file_path, file_name=file_name
    )
    return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)


def remove_attachment(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    attachment_id: str,
) -> list[FileAttachment]:
    """Remove a file attachment reference by ID.

    If act_id is None, removes from Play-level attachments.
    """
    if act_id is not None:
        _validate_id(name="act_id", value=act_id)
    if scene_id is not None:
        _validate_id(name="scene_id", value=scene_id)
    if beat_id is not None:
        _validate_id(name="beat_id", value=beat_id)
    _validate_id(name="attachment_id", value=attachment_id)

    from . import play_db
    removed = play_db.remove_attachment(attachment_id)
    if not removed:
        raise ValueError("unknown attachment_id")
    return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
