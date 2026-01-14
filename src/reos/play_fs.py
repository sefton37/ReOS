from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .session import get_current_crypto_storage
from .settings import settings


_JSON = dict[str, Any]

# =============================================================================
# Constants for "Your Story" Act and Stage Direction
# =============================================================================

YOUR_STORY_ACT_ID = "your-story"
STAGE_DIRECTION_SCENE_ID_PREFIX = "stage-direction-"


def _get_stage_direction_scene_id(act_id: str) -> str:
    """Get the Stage Direction scene ID for an Act."""
    return f"{STAGE_DIRECTION_SCENE_ID_PREFIX}{act_id[:12]}"


class BeatStage(Enum):
    """The stage/state of a Beat in The Play.

    Beats progress through these stages:
    - PLANNING: No date set, still being organized
    - IN_PROGRESS: Has a date, actively working on it
    - AWAITING_DATA: Waiting for external input/data
    - COMPLETE: Done
    """
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    AWAITING_DATA = "awaiting_data"
    COMPLETE = "complete"


def _migrate_status_to_stage(status: str) -> str:
    """Migrate old Beat status values to new stage values."""
    mapping = {
        "pending": BeatStage.PLANNING.value,
        "todo": BeatStage.PLANNING.value,
        "in_progress": BeatStage.IN_PROGRESS.value,
        "active": BeatStage.IN_PROGRESS.value,
        "blocked": BeatStage.AWAITING_DATA.value,
        "waiting": BeatStage.AWAITING_DATA.value,
        "completed": BeatStage.COMPLETE.value,
        "done": BeatStage.COMPLETE.value,
    }
    return mapping.get(status.lower().strip(), BeatStage.PLANNING.value)


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
    # Code Mode fields
    repo_path: str | None = None           # Absolute path to git repo
    artifact_type: str | None = None       # "python", "typescript", "rust", etc.
    code_config: dict[str, Any] | None = None  # Per-Act code configuration


@dataclass(frozen=True)
class Scene:
    scene_id: str
    title: str
    intent: str
    status: str
    time_horizon: str
    notes: str


@dataclass(frozen=True)
class Beat:
    """A Beat in The Play - an atomic task or event.

    Beats can be linked to calendar events. For recurring events,
    ONE Beat represents the entire series (not expanded occurrences).
    """
    beat_id: str
    title: str
    stage: str  # BeatStage value
    notes: str
    link: str | None = None
    # Calendar integration fields
    calendar_event_id: str | None = None  # Source calendar event ID
    recurrence_rule: str | None = None    # RRULE string if recurring


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

    Stage Direction is the default container for Beats that haven't been
    assigned to a specific Scene within the Act.
    """
    scenes_path = _scenes_path(act_id)
    scenes_path.parent.mkdir(parents=True, exist_ok=True)

    stage_direction_id = _get_stage_direction_scene_id(act_id)

    if scenes_path.exists():
        data = _load_json(scenes_path)
        scenes_raw = data.get("scenes", [])
        if not isinstance(scenes_raw, list):
            scenes_raw = []

        # Check if Stage Direction already exists
        for scene in scenes_raw:
            if isinstance(scene, dict) and scene.get("scene_id") == stage_direction_id:
                return  # Already exists

        # Insert Stage Direction as the first scene
        stage_direction = {
            "scene_id": stage_direction_id,
            "title": "Stage Direction",
            "intent": "Default container for unassigned Beats",
            "status": "",
            "time_horizon": "",
            "notes": "",
            "beats": [],
            "is_stage_direction": True,
        }
        scenes_raw.insert(0, stage_direction)
        _write_json(scenes_path, {"scenes": scenes_raw})
    else:
        # Create new scenes file with Stage Direction
        stage_direction = {
            "scene_id": stage_direction_id,
            "title": "Stage Direction",
            "intent": "Default container for unassigned Beats",
            "status": "",
            "time_horizon": "",
            "notes": "",
            "beats": [],
            "is_stage_direction": True,
        }
        _write_json(scenes_path, {"scenes": [stage_direction]})


def ensure_your_story_act() -> tuple[list["Act"], str]:
    """Ensure 'Your Story' Act exists.

    'Your Story' is a special default Act that always exists. All other Acts
    relate to it conceptually (life projects vs. the story of your life).
    Unassigned Beats live in 'Your Story' under its 'Stage Direction' scene.

    Returns:
        Tuple of (all acts, your_story_act_id).
    """
    ensure_play_skeleton()
    data = _load_json(_acts_path())
    acts_raw = data.get("acts", [])
    if not isinstance(acts_raw, list):
        acts_raw = []

    # Check if "Your Story" exists
    your_story_exists = any(
        isinstance(a, dict) and a.get("act_id") == YOUR_STORY_ACT_ID
        for a in acts_raw
    )

    if not your_story_exists:
        # Create "Your Story" Act
        your_story = {
            "act_id": YOUR_STORY_ACT_ID,
            "title": "Your Story",
            "active": len(acts_raw) == 0,  # Active if no other acts
            "notes": "The overarching narrative of your life. Unassigned Beats live here.",
        }
        # Insert at the beginning
        acts_raw.insert(0, your_story)
        _write_json(_acts_path(), {"acts": acts_raw})

        # Create the Act directory and Stage Direction scene
        _act_dir(YOUR_STORY_ACT_ID).mkdir(parents=True, exist_ok=True)
        _ensure_stage_direction_scene(YOUR_STORY_ACT_ID)

    # Return the acts list (use list_acts to get proper Act objects)
    from . import play_fs  # Avoid circular import
    acts, _ = list_acts()
    return acts, YOUR_STORY_ACT_ID


def read_me_markdown() -> str:
    ensure_play_skeleton()
    return _me_path().read_text(encoding="utf-8", errors="replace")


def write_me_markdown(text: str) -> None:
    """Write the me.md file (Your Story / Play level content)."""
    ensure_play_skeleton()
    _me_path().write_text(text, encoding="utf-8")


def _load_json(path: Path) -> _JSON:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, obj: _JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_acts() -> tuple[list[Act], str | None]:
    ensure_play_skeleton()
    data = _load_json(_acts_path())

    acts_raw = data.get("acts")
    if not isinstance(acts_raw, list):
        acts_raw = []

    acts: list[Act] = []
    active_id: str | None = None

    for item in acts_raw:
        if not isinstance(item, dict):
            continue
        act_id = item.get("act_id")
        title = item.get("title")
        active = bool(item.get("active", False))
        notes = item.get("notes")

        if not isinstance(act_id, str) or not act_id:
            continue
        if not isinstance(title, str) or not title:
            continue
        if not isinstance(notes, str):
            notes = ""

        # Code Mode fields (optional)
        repo_path = item.get("repo_path")
        if repo_path is not None and not isinstance(repo_path, str):
            repo_path = None
        artifact_type = item.get("artifact_type")
        if artifact_type is not None and not isinstance(artifact_type, str):
            artifact_type = None
        code_config = item.get("code_config")
        if code_config is not None and not isinstance(code_config, dict):
            code_config = None

        if active and active_id is None:
            active_id = act_id

        acts.append(Act(
            act_id=act_id,
            title=title,
            active=active,
            notes=notes,
            repo_path=repo_path,
            artifact_type=artifact_type,
            code_config=code_config,
        ))

    # Enforce single-active invariant if the file has drifted.
    if active_id is not None:
        normalized: list[Act] = []
        for a in acts:
            normalized.append(Act(
                act_id=a.act_id,
                title=a.title,
                active=(a.act_id == active_id),
                notes=a.notes,
                repo_path=a.repo_path,
                artifact_type=a.artifact_type,
                code_config=a.code_config,
            ))
        acts = normalized
        _write_acts(acts)

    return acts, active_id


def _write_acts(acts: list[Act]) -> None:
    payload = {
        "acts": [
            {
                "act_id": a.act_id,
                "title": a.title,
                "active": bool(a.active),
                "notes": a.notes,
                # Code Mode fields (only include if set)
                **({"repo_path": a.repo_path} if a.repo_path else {}),
                **({"artifact_type": a.artifact_type} if a.artifact_type else {}),
                **({"code_config": a.code_config} if a.code_config else {}),
            }
            for a in acts
        ]
    }
    _write_json(_acts_path(), payload)


def set_active_act_id(*, act_id: str | None) -> tuple[list[Act], str | None]:
    """Set the active act, or clear it if act_id is None."""
    acts, _active = list_acts()

    if act_id is not None and not any(a.act_id == act_id for a in acts):
        raise ValueError("unknown act_id")

    updated = [
        Act(
            act_id=a.act_id,
            title=a.title,
            active=(a.act_id == act_id),
            notes=a.notes,
            repo_path=a.repo_path,
            artifact_type=a.artifact_type,
            code_config=a.code_config,
        )
        for a in acts
    ]
    _write_acts(updated)
    return updated, act_id


def list_scenes(*, act_id: str) -> list[Scene]:
    ensure_play_skeleton()
    scenes_path = _scenes_path(act_id)
    if not scenes_path.exists():
        # No scenes yet.
        return []

    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        return []

    out: list[Scene] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        scene_id = item.get("scene_id")
        title = item.get("title")
        intent = item.get("intent")
        status = item.get("status")
        time_horizon = item.get("time_horizon")
        notes = item.get("notes")

        if not isinstance(scene_id, str) or not scene_id:
            continue
        if not isinstance(title, str) or not title:
            continue

        out.append(
            Scene(
                scene_id=scene_id,
                title=title,
                intent=str(intent or ""),
                status=str(status or ""),
                time_horizon=str(time_horizon or ""),
                notes=str(notes or ""),
            )
        )

    return out


def list_beats(*, act_id: str, scene_id: str) -> list[Beat]:
    ensure_play_skeleton()
    scenes_path = _scenes_path(act_id)
    if not scenes_path.exists():
        return []

    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        return []

    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            continue
        beats_raw = item.get("beats")
        if not isinstance(beats_raw, list):
            return []

        beats: list[Beat] = []
        for b in beats_raw:
            if not isinstance(b, dict):
                continue
            beat_id = b.get("beat_id")
            title = b.get("title")
            notes = b.get("notes")
            link = b.get("link")

            # Migration: convert old 'status' to new 'stage'
            stage = b.get("stage")
            if stage is None:
                old_status = b.get("status", "")
                stage = _migrate_status_to_stage(old_status)

            # Calendar integration fields
            calendar_event_id = b.get("calendar_event_id")
            if calendar_event_id is not None and not isinstance(calendar_event_id, str):
                calendar_event_id = None
            recurrence_rule = b.get("recurrence_rule")
            if recurrence_rule is not None and not isinstance(recurrence_rule, str):
                recurrence_rule = None

            if not isinstance(beat_id, str) or not beat_id:
                continue
            if not isinstance(title, str) or not title:
                continue
            if link is not None and not isinstance(link, str):
                link = None

            beats.append(
                Beat(
                    beat_id=beat_id,
                    title=title,
                    stage=str(stage or BeatStage.PLANNING.value),
                    notes=str(notes or ""),
                    link=link,
                    calendar_event_id=calendar_event_id,
                    recurrence_rule=recurrence_rule,
                )
            )
        return beats

    return []


def _validate_id(*, name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(part in value for part in ("/", "\\", "..")):
        raise ValueError(f"invalid {name}")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def create_act(*, title: str, notes: str = "") -> tuple[list[Act], str]:
    """Create a new Act with its mandatory Stage Direction scene.

    - Generates a stable act_id.
    - If no act is active yet, the new act becomes active.
    - Auto-creates a 'Stage Direction' scene as the default Beat container.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")

    acts, active_id = list_acts()
    act_id = _new_id("act")

    is_active = active_id is None
    acts.append(Act(act_id=act_id, title=title.strip(), active=is_active, notes=notes))
    _write_acts(acts)

    # Ensure the act directory exists for scenes/kb.
    _act_dir(act_id).mkdir(parents=True, exist_ok=True)

    # Auto-create Stage Direction scene
    _ensure_stage_direction_scene(act_id)

    return acts, act_id


def update_act(*, act_id: str, title: str | None = None, notes: str | None = None) -> tuple[list[Act], str | None]:
    """Update an Act's user-editable fields."""

    _validate_id(name="act_id", value=act_id)

    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")

    acts, active_id = list_acts()
    found = False
    updated: list[Act] = []
    for a in acts:
        if a.act_id != act_id:
            updated.append(a)
            continue
        found = True
        updated.append(
            Act(
                act_id=a.act_id,
                title=(title.strip() if isinstance(title, str) else a.title),
                active=bool(a.active),
                notes=(notes if isinstance(notes, str) else a.notes),
                repo_path=a.repo_path,
                artifact_type=a.artifact_type,
                code_config=a.code_config,
            )
        )

    if not found:
        raise ValueError("unknown act_id")

    _write_acts(updated)
    return updated, active_id


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

    acts, active_id = list_acts()
    found = False
    updated: list[Act] = []

    for a in acts:
        if a.act_id != act_id:
            updated.append(a)
            continue
        found = True
        updated.append(
            Act(
                act_id=a.act_id,
                title=a.title,
                active=a.active,
                notes=a.notes,
                repo_path=repo_path,
                artifact_type=artifact_type if artifact_type else a.artifact_type,
                code_config=code_config if code_config else a.code_config,
            )
        )

    if not found:
        raise ValueError("unknown act_id")

    _write_acts(updated)
    return updated, active_id


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

    acts, active_id = list_acts()
    found = False
    updated: list[Act] = []

    for a in acts:
        if a.act_id != act_id:
            updated.append(a)
            continue
        found = True

        if not a.repo_path:
            raise ValueError("Cannot configure Code Mode: no repo_path assigned to this Act")

        updated.append(
            Act(
                act_id=a.act_id,
                title=a.title,
                active=a.active,
                notes=a.notes,
                repo_path=a.repo_path,
                artifact_type=a.artifact_type,
                code_config=code_config,
            )
        )

    if not found:
        raise ValueError("unknown act_id")

    _write_acts(updated)
    return updated, active_id


def _ensure_scenes_file(*, act_id: str) -> Path:
    _validate_id(name="act_id", value=act_id)
    ensure_play_skeleton()
    act_dir = _act_dir(act_id)
    act_dir.mkdir(parents=True, exist_ok=True)
    p = _scenes_path(act_id)
    if not p.exists():
        _write_json(p, {"scenes": []})
    return p


def create_scene(
    *,
    act_id: str,
    title: str,
    intent: str = "",
    status: str = "",
    time_horizon: str = "",
    notes: str = "",
) -> list[Scene]:
    """Create a Scene under an Act."""

    _validate_id(name="act_id", value=act_id)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    if not isinstance(intent, str):
        raise ValueError("intent must be a string")
    if not isinstance(status, str):
        raise ValueError("status must be a string")
    if not isinstance(time_horizon, str):
        raise ValueError("time_horizon must be a string")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    scene_id = _new_id("scene")
    scenes_raw.append(
        {
            "scene_id": scene_id,
            "title": title.strip(),
            "intent": intent,
            "status": status,
            "time_horizon": time_horizon,
            "notes": notes,
            "beats": [],
        }
    )
    _write_json(scenes_path, {"scenes": scenes_raw})
    return list_scenes(act_id=act_id)


def update_scene(
    *,
    act_id: str,
    scene_id: str,
    title: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    time_horizon: str | None = None,
    notes: str | None = None,
) -> list[Scene]:
    """Update a Scene's fields (beats preserved)."""

    _validate_id(name="act_id", value=act_id)
    _validate_id(name="scene_id", value=scene_id)

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    found = False
    out: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out.append(item)
            continue
        found = True
        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []
        new_title = title.strip() if isinstance(title, str) and title.strip() else item.get("title")
        if not isinstance(new_title, str) or not new_title.strip():
            raise ValueError("title must be a non-empty string")

        out.append(
            {
                "scene_id": scene_id,
                "title": new_title,
                "intent": (intent if isinstance(intent, str) else str(item.get("intent") or "")),
                "status": (status if isinstance(status, str) else str(item.get("status") or "")),
                "time_horizon": (
                    time_horizon if isinstance(time_horizon, str) else str(item.get("time_horizon") or "")
                ),
                "notes": (notes if isinstance(notes, str) else str(item.get("notes") or "")),
                "beats": beats,
            }
        )

    if not found:
        raise ValueError("unknown scene_id")

    _write_json(scenes_path, {"scenes": out})
    return list_scenes(act_id=act_id)


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
) -> list[Beat]:
    """Create a Beat under a Scene.

    Args:
        act_id: The Act containing the Scene.
        scene_id: The Scene to add the Beat to.
        title: Beat title.
        stage: BeatStage value (planning, in_progress, awaiting_data, complete).
        notes: Optional notes.
        link: Optional external link.
        calendar_event_id: Optional calendar event ID this Beat is linked to.
        recurrence_rule: Optional RRULE string for recurring events.
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

    # Default stage to PLANNING if not specified
    if not stage:
        stage = BeatStage.PLANNING.value

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    beat_id = _new_id("beat")
    found_scene = False
    out: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out.append(item)
            continue
        found_scene = True

        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []

        beat_data: dict[str, Any] = {
            "beat_id": beat_id,
            "title": title.strip(),
            "stage": stage,
            "notes": notes,
            "link": link,
        }
        # Only include calendar fields if set
        if calendar_event_id:
            beat_data["calendar_event_id"] = calendar_event_id
        if recurrence_rule:
            beat_data["recurrence_rule"] = recurrence_rule

        beats.append(beat_data)
        item = dict(item)
        item["beats"] = beats
        out.append(item)

    if not found_scene:
        raise ValueError("unknown scene_id")

    _write_json(scenes_path, {"scenes": out})
    return list_beats(act_id=act_id, scene_id=scene_id)


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

    scenes_path = _ensure_scenes_file(act_id=act_id)
    data = _load_json(scenes_path)
    scenes_raw = data.get("scenes")
    if not isinstance(scenes_raw, list):
        scenes_raw = []

    found_scene = False
    found_beat = False
    out_scenes: list[dict[str, Any]] = []
    for item in scenes_raw:
        if not isinstance(item, dict):
            continue
        if item.get("scene_id") != scene_id:
            out_scenes.append(item)
            continue
        found_scene = True
        beats = item.get("beats")
        if not isinstance(beats, list):
            beats = []

        out_beats: list[dict[str, Any]] = []
        for b in beats:
            if not isinstance(b, dict):
                continue
            if b.get("beat_id") != beat_id:
                out_beats.append(b)
                continue
            found_beat = True
            new_title = title.strip() if isinstance(title, str) else str(b.get("title") or "")
            if not new_title.strip():
                raise ValueError("title must be a non-empty string")

            # Preserve stage or migrate from old status field
            existing_stage = b.get("stage")
            if existing_stage is None:
                existing_stage = _migrate_status_to_stage(str(b.get("status") or ""))

            beat_data: dict[str, Any] = {
                "beat_id": beat_id,
                "title": new_title,
                "stage": (stage if isinstance(stage, str) else existing_stage),
                "notes": (notes if isinstance(notes, str) else str(b.get("notes") or "")),
                "link": (link if isinstance(link, str) else b.get("link")),
            }
            # Preserve calendar fields
            if b.get("calendar_event_id"):
                beat_data["calendar_event_id"] = b["calendar_event_id"]
            if b.get("recurrence_rule"):
                beat_data["recurrence_rule"] = b["recurrence_rule"]

            out_beats.append(beat_data)

        item = dict(item)
        item["beats"] = out_beats
        out_scenes.append(item)

    if not found_scene:
        raise ValueError("unknown scene_id")
    if not found_beat:
        raise ValueError("unknown beat_id")

    _write_json(scenes_path, {"scenes": out_scenes})
    return list_beats(act_id=act_id, scene_id=scene_id)


def move_beat(
    *,
    beat_id: str,
    source_act_id: str,
    source_scene_id: str,
    target_act_id: str,
    target_scene_id: str,
) -> dict[str, Any]:
    """Move a Beat from one Scene to another (possibly different Acts).

    Args:
        beat_id: The Beat to move.
        source_act_id: The source Act.
        source_scene_id: The source Scene.
        target_act_id: The target Act.
        target_scene_id: The target Scene.

    Returns:
        Dict with moved beat_id and target location.

    Raises:
        ValueError: If beat, source, or target not found.
    """
    _validate_id(name="beat_id", value=beat_id)
    _validate_id(name="source_act_id", value=source_act_id)
    _validate_id(name="source_scene_id", value=source_scene_id)
    _validate_id(name="target_act_id", value=target_act_id)
    _validate_id(name="target_scene_id", value=target_scene_id)

    # 1. Find and remove the beat from the source scene
    source_scenes_path = _scenes_path(source_act_id)
    if not source_scenes_path.exists():
        raise ValueError("source act not found")

    source_data = _load_json(source_scenes_path)
    source_scenes_raw = source_data.get("scenes", [])
    if not isinstance(source_scenes_raw, list):
        source_scenes_raw = []

    beat_data: dict[str, Any] | None = None
    new_source_scenes: list[dict[str, Any]] = []

    for scene in source_scenes_raw:
        if not isinstance(scene, dict):
            continue
        if scene.get("scene_id") != source_scene_id:
            new_source_scenes.append(scene)
            continue

        # Found source scene - look for the beat
        beats = scene.get("beats", [])
        if not isinstance(beats, list):
            beats = []

        new_beats: list[dict[str, Any]] = []
        for b in beats:
            if not isinstance(b, dict):
                continue
            if b.get("beat_id") == beat_id:
                beat_data = dict(b)  # Extract the beat
            else:
                new_beats.append(b)

        scene_copy = dict(scene)
        scene_copy["beats"] = new_beats
        new_source_scenes.append(scene_copy)

    if beat_data is None:
        raise ValueError("beat not found in source scene")

    # 2. Add the beat to the target scene
    if source_act_id == target_act_id:
        # Same act - work with the same scenes list
        target_scenes_raw = new_source_scenes
    else:
        target_scenes_path = _scenes_path(target_act_id)
        if not target_scenes_path.exists():
            raise ValueError("target act not found")
        target_data = _load_json(target_scenes_path)
        target_scenes_raw = target_data.get("scenes", [])
        if not isinstance(target_scenes_raw, list):
            target_scenes_raw = []

    target_found = False
    new_target_scenes: list[dict[str, Any]] = []

    for scene in target_scenes_raw:
        if not isinstance(scene, dict):
            continue
        if scene.get("scene_id") != target_scene_id:
            new_target_scenes.append(scene)
            continue

        target_found = True
        # Found target scene - add the beat
        beats = scene.get("beats", [])
        if not isinstance(beats, list):
            beats = []
        beats.append(beat_data)

        scene_copy = dict(scene)
        scene_copy["beats"] = beats
        new_target_scenes.append(scene_copy)

    if not target_found:
        raise ValueError("target scene not found")

    # 3. Write changes
    if source_act_id == target_act_id:
        # Same act - write once
        _write_json(source_scenes_path, {"scenes": new_target_scenes})
    else:
        # Different acts - write both
        _write_json(source_scenes_path, {"scenes": new_source_scenes})
        target_scenes_path = _scenes_path(target_act_id)
        _write_json(target_scenes_path, {"scenes": new_target_scenes})

    return {
        "beat_id": beat_id,
        "target_act_id": target_act_id,
        "target_scene_id": target_scene_id,
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


def _attachments_path(*, act_id: str | None = None, scene_id: str | None = None, beat_id: str | None = None) -> Path:
    """Return path to attachments.json for the given level."""
    if act_id is None:
        # Play-level attachments (root level)
        return play_root() / "attachments.json"
    kb_root = _kb_root_for(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    return kb_root / "attachments.json"


def _load_attachments(path: Path) -> list[dict[str, Any]]:
    """Load attachments list from JSON file."""
    if not path.exists():
        return []
    data = _load_json(path)
    attachments = data.get("attachments")
    return attachments if isinstance(attachments, list) else []


def _write_attachments(path: Path, attachments: list[dict[str, Any]]) -> None:
    """Write attachments list to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"attachments": attachments})


def list_attachments(
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> list[FileAttachment]:
    """List file attachments at the specified level (Play, Act, Scene, or Beat)."""
    ensure_play_skeleton()
    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    attachments: list[FileAttachment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        attachment_id = item.get("attachment_id")
        file_path = item.get("file_path")
        file_name = item.get("file_name")
        file_type = item.get("file_type")
        added_at = item.get("added_at")

        if not isinstance(attachment_id, str) or not attachment_id:
            continue
        if not isinstance(file_path, str) or not file_path:
            continue
        if not isinstance(file_name, str):
            file_name = Path(file_path).name
        if not isinstance(file_type, str):
            file_type = Path(file_path).suffix.lstrip(".").lower()
        if not isinstance(added_at, str):
            added_at = ""

        attachments.append(
            FileAttachment(
                attachment_id=attachment_id,
                file_path=file_path,
                file_name=file_name,
                file_type=file_type,
                added_at=added_at,
            )
        )

    return attachments


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
    ensure_play_skeleton()
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

    # Derive file_name and file_type if not provided
    if not file_name:
        file_name = p.name
    file_type = p.suffix.lstrip(".").lower()

    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    # Check for duplicates by path
    for item in raw:
        if isinstance(item, dict) and item.get("file_path") == file_path:
            # Already attached, return current list
            return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)

    attachment_id = _new_id("att")
    added_at = datetime.now(timezone.utc).isoformat()

    raw.append({
        "attachment_id": attachment_id,
        "file_path": file_path,
        "file_name": file_name,
        "file_type": file_type,
        "added_at": added_at,
    })

    _write_attachments(att_path, raw)
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
    ensure_play_skeleton()
    if act_id is not None:
        _validate_id(name="act_id", value=act_id)
    if scene_id is not None:
        _validate_id(name="scene_id", value=scene_id)
    if beat_id is not None:
        _validate_id(name="beat_id", value=beat_id)
    _validate_id(name="attachment_id", value=attachment_id)

    att_path = _attachments_path(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    raw = _load_attachments(att_path)

    found = False
    updated: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("attachment_id") == attachment_id:
            found = True
            continue
        updated.append(item)

    if not found:
        raise ValueError("unknown attachment_id")

    _write_attachments(att_path, updated)
    return list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
