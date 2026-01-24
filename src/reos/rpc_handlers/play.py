"""Play RPC handlers - Acts, Scenes, KB, Attachments, Pages.

These handlers manage the Play hierarchy (Acts/Scenes) and related operations.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from reos.db import Database
from reos.play_fs import (
    add_attachment as play_add_attachment,
    assign_repo_to_act as play_assign_repo_to_act,
    create_act as play_create_act,
    create_scene as play_create_scene,
    delete_scene as play_delete_scene,
    kb_list_files as play_kb_list_files,
    kb_read as play_kb_read,
    kb_write_apply as play_kb_write_apply,
    kb_write_preview as play_kb_write_preview,
    list_acts as play_list_acts,
    list_attachments as play_list_attachments,
    list_scenes as play_list_scenes,
    move_scene as play_move_scene,
    play_root,
    read_me_markdown as play_read_me_markdown,
    remove_attachment as play_remove_attachment,
    set_active_act_id as play_set_active_act_id,
    update_act as play_update_act,
    update_scene as play_update_scene,
    write_me_markdown as play_write_me_markdown,
)

from . import RpcError

logger = logging.getLogger(__name__)


def get_current_play_path(db: Database) -> str | None:
    """Get the current play path.

    Returns the path to the play root directory, or None if not available.
    """
    try:
        path = play_root()
        if path.exists():
            return str(path)
        return None
    except Exception:
        return None


def _sha256_text(text: str) -> str:
    """Compute SHA256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# =============================================================================
# Me.md Handlers
# =============================================================================


def handle_play_me_read(_db: Database) -> dict[str, Any]:
    """Read me.md content."""
    return {"markdown": play_read_me_markdown()}


def handle_play_me_write(_db: Database, *, text: str) -> dict[str, Any]:
    """Write me.md content."""
    play_write_me_markdown(text)
    return {"ok": True}


# =============================================================================
# Acts Handlers
# =============================================================================


def handle_play_acts_list(_db: Database) -> dict[str, Any]:
    """List all acts."""
    acts, active_id = play_list_acts()
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def handle_play_acts_set_active(_db: Database, *, act_id: str | None) -> dict[str, Any]:
    """Set active act, or clear it if act_id is None."""
    try:
        acts, active_id = play_set_active_act_id(act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def handle_play_acts_create(_db: Database, *, title: str, notes: str | None = None) -> dict[str, Any]:
    """Create a new act."""
    try:
        acts, created_id = play_create_act(title=title, notes=notes or "")
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "created_act_id": created_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path}
            for a in acts
        ],
    }


def handle_play_acts_update(
    _db: Database,
    *,
    act_id: str,
    title: str | None = None,
    notes: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Update an act."""
    try:
        acts, active_id = play_update_act(act_id=act_id, title=title, notes=notes, color=color)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "active_act_id": active_id,
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path, "color": a.color}
            for a in acts
        ],
    }


def handle_play_acts_assign_repo(
    _db: Database,
    *,
    act_id: str,
    repo_path: str,
) -> dict[str, Any]:
    """Assign a repository path to an act. Creates the directory if it doesn't exist."""
    import subprocess

    path = Path(repo_path).expanduser().resolve()

    # Create directory if it doesn't exist
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    # Initialize git repo if not already a git repo
    git_dir = path / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        # Create initial commit to have a valid repo
        readme = path / "README.md"
        if not readme.exists():
            readme.write_text(f"# Project\n\nCreated by ReOS\n")
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), capture_output=True, check=True)

    try:
        acts, _active_id = play_assign_repo_to_act(act_id=act_id, repo_path=str(path))
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc

    return {
        "success": True,
        "repo_path": str(path),
        "acts": [
            {"act_id": a.act_id, "title": a.title, "active": bool(a.active), "notes": a.notes, "repo_path": a.repo_path}
            for a in acts
        ],
    }


# =============================================================================
# Scenes Handlers
# =============================================================================


def handle_play_scenes_list(_db: Database, *, act_id: str) -> dict[str, Any]:
    """List scenes for an act."""
    scenes = play_list_scenes(act_id=act_id)
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "act_id": s.act_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


def handle_play_scenes_list_all(db: Database) -> dict[str, Any]:
    """List all scenes across all acts with act information for Kanban display.

    Calendar metadata is now stored directly in play.db (single source of truth).
    This function:
    1. Syncs calendar events to scenes (with 5-year lookahead)
    2. Refreshes next_occurrence for recurring events
    3. Classifies scenes without a category
    4. Enriches with computed fields (effective_stage, etc.)
    """
    from reos import play_db
    from reos.cairn.scene_calendar_sync import get_next_occurrence

    # Sync calendar events to scenes before listing (5 years = 43800 hours)
    # This ensures all future calendar events have corresponding scenes
    play_path = get_current_play_path(db)
    if play_path:
        try:
            cairn_db_path = Path(play_path) / ".cairn" / "cairn.db"
            if cairn_db_path.exists():
                from reos.cairn.store import CairnStore
                store = CairnStore(cairn_db_path)
                from reos.cairn.thunderbird import ThunderbirdBridge
                thunderbird = ThunderbirdBridge.auto_detect()
                if thunderbird and thunderbird.has_calendar():
                    from reos.cairn.scene_calendar_sync import sync_calendar_to_scenes
                    # Sync with 5-year window to capture all future events
                    sync_calendar_to_scenes(thunderbird, store, hours=43800)
        except Exception as e:
            logger.debug("Failed to sync calendar for play/scenes/list_all: %s", e)

    # Get scenes from play.db (calendar metadata is now included)
    scenes = play_db.list_all_scenes()

    # Refresh next_occurrence for recurring events (time-dependent computation)
    now = datetime.now()
    for scene in scenes:
        recurrence_rule = scene.get("recurrence_rule")
        if recurrence_rule:
            start_str = scene.get("calendar_event_start")
            if start_str:
                try:
                    if isinstance(start_str, str):
                        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        if start_dt.tzinfo is not None:
                            start_dt = start_dt.replace(tzinfo=None)
                    else:
                        start_dt = start_str
                    # Compute next occurrence from NOW
                    next_occ = get_next_occurrence(recurrence_rule, start_dt, after=now - timedelta(hours=1))
                    scene["next_occurrence"] = next_occ.isoformat() if next_occ else None
                except Exception:
                    pass  # Keep existing next_occurrence

    # Classify scenes without a category
    def classify_scene(scene: dict) -> str:
        """Classify a scene as 'event', 'holiday', or 'birthday'."""
        # If category is already set (from calendar sync), use it
        existing = scene.get("category")
        if existing:
            return existing

        title = (scene.get("title") or "").lower()

        # Title-based classification
        # Holidays: common holiday patterns
        holiday_keywords = [
            "day", "eve", "christmas", "thanksgiving", "easter", "independence",
            "memorial", "labor", "veterans", "mlk", "president", "columbus",
            "new year", "valentine", "st. patrick", "mother's day", "father's day",
            "halloween", "juneteenth", "indigenous"
        ]
        if any(kw in title for kw in holiday_keywords) and "'s birthday" not in title:
            if not any(title.endswith(f"'s {kw}") for kw in ["meeting", "call", "appointment"]):
                return "holiday"

        # Birthdays and anniversaries
        if "birthday" in title or "anniversary" in title:
            return "birthday"

        return "event"

    for scene in scenes:
        scene["category"] = classify_scene(scene)

    # Enrich scenes with computed fields (effective_stage, is_unscheduled, is_overdue)
    from reos.play_computed import enrich_scene_for_display
    enriched_scenes = [enrich_scene_for_display(scene) for scene in scenes]

    return {"scenes": enriched_scenes}


def handle_play_scenes_create(
    _db: Database,
    *,
    act_id: str,
    title: str,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
    calendar_event_id: str | None = None,
    recurrence_rule: str | None = None,
    thunderbird_event_id: str | None = None,
) -> dict[str, Any]:
    """Create a new scene."""
    try:
        scenes, scene_id = play_create_scene(
            act_id=act_id,
            title=title,
            stage=stage or "",
            notes=notes or "",
            link=link,
            calendar_event_id=calendar_event_id,
            recurrence_rule=recurrence_rule,
            thunderbird_event_id=thunderbird_event_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "created_scene_id": scene_id,
        "scenes": [
            {
                "scene_id": s.scene_id,
                "act_id": s.act_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


def handle_play_scenes_update(
    _db: Database,
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
) -> dict[str, Any]:
    """Update a scene."""
    try:
        scenes = play_update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title=title,
            stage=stage,
            notes=notes,
            link=link,
            calendar_event_id=calendar_event_id,
            recurrence_rule=recurrence_rule,
            thunderbird_event_id=thunderbird_event_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "scenes": [
            {
                "scene_id": s.scene_id,
                "act_id": s.act_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


# =============================================================================
# Beats Handlers (Backward Compatibility - Now Scenes)
# =============================================================================


def handle_play_beats_list(_db: Database, *, act_id: str, scene_id: str) -> dict[str, Any]:
    """Backward compatibility: beats are now scenes. The scene_id param is ignored."""
    scenes = play_list_scenes(act_id=act_id)
    return {
        "beats": [
            {
                "beat_id": s.scene_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


def handle_play_beats_create(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,  # Ignored in v4 - beats are now scenes
    title: str,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    """Backward compatibility: create a scene (formerly beat)."""
    try:
        scenes, scene_id = play_create_scene(
            act_id=act_id,
            title=title,
            stage=stage or "",
            notes=notes or "",
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": s.scene_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


def handle_play_beats_update(
    _db: Database,
    *,
    act_id: str,
    scene_id: str,  # Ignored in v4 - beats are now scenes
    beat_id: str,
    title: str | None = None,
    stage: str | None = None,
    notes: str | None = None,
    link: str | None = None,
) -> dict[str, Any]:
    """Backward compatibility: update a scene (formerly beat)."""
    try:
        scenes = play_update_scene(
            act_id=act_id,
            scene_id=beat_id,  # beat_id is now scene_id
            title=title,
            stage=stage,
            notes=notes,
            link=link,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "beats": [
            {
                "beat_id": s.scene_id,
                "title": s.title,
                "stage": s.stage,
                "notes": s.notes,
                "link": s.link,
                "calendar_event_id": s.calendar_event_id,
                "recurrence_rule": s.recurrence_rule,
                "thunderbird_event_id": s.thunderbird_event_id,
            }
            for s in scenes
        ]
    }


def handle_play_beats_move(
    db: Database,
    *,
    beat_id: str,
    source_act_id: str,
    source_scene_id: str,  # Ignored in v4
    target_act_id: str,
    target_scene_id: str,  # Ignored in v4
) -> dict[str, Any]:
    """Backward compatibility: move a scene (formerly beat) between acts."""
    try:
        result = play_move_scene(
            scene_id=beat_id,
            source_act_id=source_act_id,
            target_act_id=target_act_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc

    # After successful move, update CAIRN cache so "What Needs Attention" shows correct Act
    try:
        play_path = get_current_play_path(db)
        if play_path:
            from reos.cairn.store import CairnStore

            store = CairnStore(Path(play_path) / ".cairn" / "cairn.db")
            store.update_scene_location(beat_id, target_act_id)
    except Exception:
        pass  # Don't fail the move if cache update fails

    return {
        "beat_id": result["scene_id"],
        "target_act_id": result["target_act_id"],
        "target_scene_id": target_scene_id,  # Return for backward compat
    }


# =============================================================================
# KB (Knowledge Base) Handlers
# =============================================================================


def handle_play_kb_list(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    """List KB files."""
    try:
        files = play_kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"files": files}


def handle_play_kb_read(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str = "kb.md",
) -> dict[str, Any]:
    """Read a KB file."""
    try:
        text = play_kb_read(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path)
    except FileNotFoundError as exc:
        raise RpcError(code=-32602, message=f"file not found: {exc}") from exc
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {"path": path, "text": text}


def handle_play_kb_write_preview(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
) -> dict[str, Any]:
    """Preview KB write (get current hash for conflict detection)."""
    try:
        res = play_kb_write_preview(act_id=act_id, scene_id=scene_id, beat_id=beat_id, path=path, text=text)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "path": path,
        "expected_sha256_current": res["sha256_current"],
        **res,
    }


def handle_play_kb_write_apply(
    _db: Database,
    *,
    act_id: str,
    scene_id: str | None = None,
    beat_id: str | None = None,
    path: str,
    text: str,
    expected_sha256_current: str,
) -> dict[str, Any]:
    """Apply KB write with conflict detection."""
    if not isinstance(expected_sha256_current, str) or not expected_sha256_current:
        raise RpcError(code=-32602, message="expected_sha256_current is required")
    try:
        res = play_kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256_current,
        )
    except ValueError as exc:
        # Surface conflicts as a deterministic JSON-RPC error.
        raise RpcError(code=-32009, message=str(exc)) from exc
    return {"path": path, **res}


# =============================================================================
# Attachments Handlers
# =============================================================================


def handle_play_attachments_list(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
) -> dict[str, Any]:
    """List attachments."""
    try:
        attachments = play_list_attachments(act_id=act_id, scene_id=scene_id, beat_id=beat_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


def handle_play_attachments_add(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    file_path: str,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Add an attachment."""
    try:
        attachments = play_add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            file_path=file_path,
            file_name=file_name,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


def handle_play_attachments_remove(
    _db: Database,
    *,
    act_id: str | None = None,
    scene_id: str | None = None,
    beat_id: str | None = None,
    attachment_id: str,
) -> dict[str, Any]:
    """Remove an attachment."""
    try:
        attachments = play_remove_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    return {
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "file_path": a.file_path,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "added_at": a.added_at,
            }
            for a in attachments
        ]
    }


# =============================================================================
# Pages Handlers (Nested Knowledgebase)
# =============================================================================


def handle_play_pages_list(_db: Database, *, act_id: str, parent_page_id: str | None = None) -> dict[str, Any]:
    """List pages for an act, optionally filtered by parent."""
    from reos import play_db
    pages = play_db.list_pages(act_id, parent_page_id)
    return {"pages": pages}


def handle_play_pages_tree(_db: Database, *, act_id: str) -> dict[str, Any]:
    """Get the full page tree for an act."""
    from reos import play_db
    pages = play_db.get_page_tree(act_id)
    return {"pages": pages}


def handle_play_pages_create(_db: Database, *, act_id: str, title: str,
                              parent_page_id: str | None = None,
                              icon: str | None = None) -> dict[str, Any]:
    """Create a new page."""
    from reos import play_db
    pages, page_id = play_db.create_page(
        act_id=act_id, title=title, parent_page_id=parent_page_id, icon=icon
    )
    return {"pages": pages, "created_page_id": page_id}


def handle_play_pages_update(_db: Database, *, page_id: str,
                              title: str | None = None,
                              icon: str | None = None) -> dict[str, Any]:
    """Update a page's metadata."""
    from reos import play_db
    page = play_db.update_page(page_id=page_id, title=title, icon=icon)
    if not page:
        raise RpcError(code=-32602, message="Page not found")
    return {"page": page}


def handle_play_pages_delete(_db: Database, *, page_id: str) -> dict[str, Any]:
    """Delete a page and its descendants."""
    from reos import play_db
    deleted = play_db.delete_page(page_id)
    if not deleted:
        raise RpcError(code=-32602, message="Page not found")
    return {"deleted": True}


def handle_play_pages_move(_db: Database, *, page_id: str,
                            new_parent_id: str | None = None,
                            new_position: int | None = None) -> dict[str, Any]:
    """Move a page to a new parent or position."""
    from reos import play_db
    page = play_db.move_page(page_id=page_id, new_parent_id=new_parent_id, new_position=new_position)
    if not page:
        raise RpcError(code=-32602, message="Page not found")
    return {"page": page}


def handle_play_pages_content_read(_db: Database, *, act_id: str, page_id: str) -> dict[str, Any]:
    """Read page content."""
    from reos import play_db
    text = play_db.read_page_content(act_id, page_id)
    return {"text": text}


def handle_play_pages_content_write(_db: Database, *, act_id: str, page_id: str, text: str) -> dict[str, Any]:
    """Write page content."""
    from reos import play_db
    play_db.write_page_content(act_id, page_id, text)
    return {"ok": True}
