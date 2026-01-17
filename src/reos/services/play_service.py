"""Play Service - The Play file and hierarchy management.

Wraps play_fs.py to provide a unified interface for managing
The Play hierarchy (Acts, Scenes, Beats, KB files, Attachments).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .. import play_fs

logger = logging.getLogger(__name__)


@dataclass
class ActInfo:
    """Information about an Act.

    When repo_path is set, this Act is in "Code Mode" - ReOS will
    automatically detect code-related requests and provide agentic
    coding capabilities sandboxed to the assigned repository.
    """

    act_id: str
    title: str
    active: bool = False
    notes: str = ""
    # Code Mode fields
    repo_path: str | None = None
    artifact_type: str | None = None
    code_config: dict[str, Any] | None = None

    @property
    def has_repo(self) -> bool:
        """Check if this Act has an assigned repository (Code Mode enabled)."""
        return self.repo_path is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "act_id": self.act_id,
            "title": self.title,
            "active": self.active,
            "notes": self.notes,
        }
        # Only include Code Mode fields if set
        if self.repo_path:
            result["repo_path"] = self.repo_path
        if self.artifact_type:
            result["artifact_type"] = self.artifact_type
        if self.code_config:
            result["code_config"] = self.code_config
        return result

    @classmethod
    def from_play_fs(cls, act: play_fs.Act) -> ActInfo:
        return cls(
            act_id=act.act_id,
            title=act.title,
            active=act.active,
            notes=act.notes,
            repo_path=act.repo_path,
            artifact_type=act.artifact_type,
            code_config=act.code_config,
        )


@dataclass
class SceneInfo:
    """Information about a Scene (the task/todo item in v4).

    In the 2-tier architecture, Scenes are the actionable items
    (formerly called Beats in the 3-tier architecture).
    """

    scene_id: str
    act_id: str
    title: str
    stage: str = "planning"
    notes: str = ""
    link: str | None = None
    calendar_event_id: str | None = None
    recurrence_rule: str | None = None
    thunderbird_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "scene_id": self.scene_id,
            "act_id": self.act_id,
            "title": self.title,
            "stage": self.stage,
            "notes": self.notes,
        }
        if self.link:
            result["link"] = self.link
        if self.calendar_event_id:
            result["calendar_event_id"] = self.calendar_event_id
        if self.recurrence_rule:
            result["recurrence_rule"] = self.recurrence_rule
        if self.thunderbird_event_id:
            result["thunderbird_event_id"] = self.thunderbird_event_id
        return result

    @classmethod
    def from_play_fs(cls, scene: play_fs.Scene) -> SceneInfo:
        return cls(
            scene_id=scene.scene_id,
            act_id=scene.act_id,
            title=scene.title,
            stage=scene.stage,
            notes=scene.notes,
            link=scene.link,
            calendar_event_id=scene.calendar_event_id,
            recurrence_rule=scene.recurrence_rule,
            thunderbird_event_id=scene.thunderbird_event_id,
        )


@dataclass
class BeatInfo:
    """Backward compatibility class for Beats.

    DEPRECATED: Use SceneInfo instead. In v4, Beats have been merged into Scenes.
    """

    beat_id: str
    title: str
    stage: str = ""  # Renamed from status
    notes: str = ""
    link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "title": self.title,
            "stage": self.stage,
            "notes": self.notes,
            "link": self.link,
        }

    @classmethod
    def from_play_fs(cls, beat: play_fs.Beat) -> BeatInfo:
        return cls(
            beat_id=beat.beat_id,
            title=beat.title,
            stage=beat.stage,
            notes=beat.notes,
            link=beat.link,
        )

    @classmethod
    def from_scene_info(cls, scene: SceneInfo) -> BeatInfo:
        """Convert SceneInfo to BeatInfo for backward compatibility."""
        return cls(
            beat_id=scene.scene_id,
            title=scene.title,
            stage=scene.stage,
            notes=scene.notes,
            link=scene.link,
        )


@dataclass
class AttachmentInfo:
    """Information about a file attachment."""

    attachment_id: str
    file_path: str
    file_name: str
    file_type: str
    added_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "added_at": self.added_at,
        }

    @classmethod
    def from_play_fs(cls, att: play_fs.FileAttachment) -> AttachmentInfo:
        return cls(
            attachment_id=att.attachment_id,
            file_path=att.file_path,
            file_name=att.file_name,
            file_type=att.file_type,
            added_at=att.added_at,
        )


class PlayService:
    """Unified service for The Play hierarchy management."""

    # --- Your Story (me.md) ---

    def read_story(self) -> str:
        """Read the user's story (me.md content)."""
        return play_fs.read_me_markdown()

    def write_story(self, content: str) -> bool:
        """Write the user's story.

        Args:
            content: The new story content

        Returns:
            True if successful
        """
        try:
            play_fs.write_me_markdown(content)
            return True
        except Exception as e:
            logger.error("Failed to write story: %s", e)
            return False

    # --- Acts ---

    def list_acts(self) -> tuple[list[ActInfo], str | None]:
        """List all acts and the active act ID.

        Returns:
            Tuple of (list of ActInfo, active_act_id or None)
        """
        acts, active_id = play_fs.list_acts()
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def create_act(self, title: str, notes: str = "") -> tuple[list[ActInfo], str]:
        """Create a new act.

        Args:
            title: Act title
            notes: Optional notes

        Returns:
            Tuple of (updated act list, new act_id)
        """
        acts, act_id = play_fs.create_act(title=title, notes=notes)
        return [ActInfo.from_play_fs(a) for a in acts], act_id

    def update_act(
        self,
        act_id: str,
        title: str | None = None,
        notes: str | None = None,
    ) -> tuple[list[ActInfo], str | None]:
        """Update an act's fields.

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.update_act(act_id=act_id, title=title, notes=notes)
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def set_active_act(self, act_id: str | None) -> tuple[list[ActInfo], str | None]:
        """Set the active act (or clear if None).

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.set_active_act_id(act_id=act_id)
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    # --- Code Mode (Repo Assignment) ---

    def assign_repo(
        self,
        act_id: str,
        repo_path: str | None,
        artifact_type: str | None = None,
        code_config: dict[str, Any] | None = None,
    ) -> tuple[list[ActInfo], str | None]:
        """Assign a repository to an Act, enabling Code Mode.

        Args:
            act_id: The Act to modify
            repo_path: Absolute path to git repository, or None to disable Code Mode
            artifact_type: Language/type hint (e.g., "python", "typescript")
            code_config: Per-Act code configuration

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.assign_repo_to_act(
            act_id=act_id,
            repo_path=repo_path,
            artifact_type=artifact_type,
            code_config=code_config,
        )
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def configure_code_mode(
        self,
        act_id: str,
        code_config: dict[str, Any],
    ) -> tuple[list[ActInfo], str | None]:
        """Update Code Mode configuration for an Act.

        Args:
            act_id: The Act to modify
            code_config: Code configuration dict (test_command, build_command, etc.)

        Returns:
            Tuple of (updated act list, active_act_id)
        """
        acts, active_id = play_fs.configure_code_mode(
            act_id=act_id,
            code_config=code_config,
        )
        return [ActInfo.from_play_fs(a) for a in acts], active_id

    def get_active_act_with_repo(self) -> ActInfo | None:
        """Get the active Act if it has a repo assigned (Code Mode enabled).

        Returns:
            ActInfo if active Act has repo_path, else None
        """
        acts, active_id = self.list_acts()
        if not active_id:
            return None

        active_act = next((a for a in acts if a.act_id == active_id), None)
        if not active_act or not active_act.has_repo:
            return None

        return active_act

    # --- Scenes ---

    def list_scenes(self, act_id: str) -> list[SceneInfo]:
        """List scenes under an act."""
        scenes = play_fs.list_scenes(act_id=act_id)
        return [SceneInfo.from_play_fs(s) for s in scenes]

    def create_scene(
        self,
        act_id: str,
        title: str,
        stage: str = "",
        notes: str = "",
        link: str | None = None,
        calendar_event_id: str | None = None,
        recurrence_rule: str | None = None,
        thunderbird_event_id: str | None = None,
    ) -> tuple[list[SceneInfo], str]:
        """Create a new scene under an act.

        Returns:
            Tuple of (updated list of scenes, new scene_id)
        """
        scenes, scene_id = play_fs.create_scene(
            act_id=act_id,
            title=title,
            stage=stage,
            notes=notes,
            link=link,
            calendar_event_id=calendar_event_id,
            recurrence_rule=recurrence_rule,
            thunderbird_event_id=thunderbird_event_id,
        )
        return [SceneInfo.from_play_fs(s) for s in scenes], scene_id

    def update_scene(
        self,
        act_id: str,
        scene_id: str,
        title: str | None = None,
        stage: str | None = None,
        notes: str | None = None,
        link: str | None = None,
        calendar_event_id: str | None = None,
        recurrence_rule: str | None = None,
        thunderbird_event_id: str | None = None,
    ) -> list[SceneInfo]:
        """Update a scene's fields.

        Returns:
            Updated list of scenes
        """
        scenes = play_fs.update_scene(
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
        return [SceneInfo.from_play_fs(s) for s in scenes]

    def delete_scene(self, act_id: str, scene_id: str) -> list[SceneInfo]:
        """Delete a scene from an act.

        Returns:
            Updated list of scenes
        """
        scenes = play_fs.delete_scene(act_id=act_id, scene_id=scene_id)
        return [SceneInfo.from_play_fs(s) for s in scenes]

    def move_scene(
        self,
        scene_id: str,
        source_act_id: str,
        target_act_id: str,
    ) -> dict[str, Any]:
        """Move a scene to a different act.

        Returns:
            Dict with scene_id and target_act_id
        """
        return play_fs.move_scene(
            scene_id=scene_id,
            source_act_id=source_act_id,
            target_act_id=target_act_id,
        )

    # --- Beats (Backward Compatibility) ---
    # In v4, Beats have been merged into Scenes. These methods wrap Scene operations.

    def list_beats(self, act_id: str, scene_id: str | None = None) -> list[BeatInfo]:
        """List beats (scenes) under an act.

        DEPRECATED: Use list_scenes instead.
        The scene_id parameter is ignored in v4.
        """
        scenes = self.list_scenes(act_id)
        return [BeatInfo.from_scene_info(s) for s in scenes]

    def create_beat(
        self,
        act_id: str,
        scene_id: str,  # Ignored in v4
        title: str,
        stage: str = "",
        notes: str = "",
        link: str | None = None,
    ) -> list[BeatInfo]:
        """Create a new beat (scene) under an act.

        DEPRECATED: Use create_scene instead.
        The scene_id parameter is ignored in v4.

        Returns:
            Updated list of beats (scenes)
        """
        scenes, _ = self.create_scene(
            act_id=act_id,
            title=title,
            stage=stage,
            notes=notes,
            link=link,
        )
        return [BeatInfo.from_scene_info(s) for s in scenes]

    def update_beat(
        self,
        act_id: str,
        scene_id: str,  # Ignored in v4
        beat_id: str,
        title: str | None = None,
        stage: str | None = None,
        notes: str | None = None,
        link: str | None = None,
    ) -> list[BeatInfo]:
        """Update a beat's (scene's) fields.

        DEPRECATED: Use update_scene instead.

        Returns:
            Updated list of beats (scenes)
        """
        scenes = self.update_scene(
            act_id=act_id,
            scene_id=beat_id,  # beat_id is now scene_id
            title=title,
            stage=stage,
            notes=notes,
            link=link,
        )
        return [BeatInfo.from_scene_info(s) for s in scenes]

    def delete_beat(
        self,
        act_id: str,
        scene_id: str,  # Ignored in v4
        beat_id: str,
    ) -> list[BeatInfo]:
        """Delete a beat (scene).

        DEPRECATED: Use delete_scene instead.

        Returns:
            Updated list of beats (scenes)
        """
        scenes = self.delete_scene(act_id=act_id, scene_id=beat_id)
        return [BeatInfo.from_scene_info(s) for s in scenes]

    # --- Knowledge Base (KB) Files ---

    def list_kb_files(
        self,
        act_id: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[str]:
        """List KB files at the specified level.

        Returns:
            List of relative file paths
        """
        return play_fs.kb_list_files(act_id=act_id, scene_id=scene_id, beat_id=beat_id)

    def read_kb_file(
        self,
        act_id: str,
        path: str = "kb.md",
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> str:
        """Read a KB file.

        Args:
            act_id: The act ID
            path: Relative file path (default: kb.md)
            scene_id: Optional scene ID
            beat_id: Optional beat ID

        Returns:
            File content as string
        """
        return play_fs.kb_read(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
        )

    def preview_kb_write(
        self,
        act_id: str,
        path: str,
        text: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> dict[str, Any]:
        """Preview a KB file write (diff, hashes).

        Returns:
            Dict with exists, sha256_current, sha256_new, diff
        """
        return play_fs.kb_write_preview(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
        )

    def apply_kb_write(
        self,
        act_id: str,
        path: str,
        text: str,
        expected_sha256: str,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply a KB file write with hash verification.

        Args:
            expected_sha256: SHA256 of current content (from preview)

        Returns:
            Dict with ok and sha256_current
        """
        return play_fs.kb_write_apply(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            path=path,
            text=text,
            expected_sha256_current=expected_sha256,
        )

    # --- Attachments ---

    def list_attachments(
        self,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """List attachments at the specified level.

        Args:
            act_id: None for Play-level attachments

        Returns:
            List of AttachmentInfo
        """
        attachments = play_fs.list_attachments(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    def add_attachment(
        self,
        file_path: str,
        file_name: str | None = None,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """Add a file attachment.

        Args:
            file_path: Absolute path to the file
            file_name: Optional display name
            act_id: None for Play-level

        Returns:
            Updated list of attachments
        """
        attachments = play_fs.add_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            file_path=file_path,
            file_name=file_name,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    def remove_attachment(
        self,
        attachment_id: str,
        act_id: str | None = None,
        scene_id: str | None = None,
        beat_id: str | None = None,
    ) -> list[AttachmentInfo]:
        """Remove a file attachment.

        Returns:
            Updated list of attachments
        """
        attachments = play_fs.remove_attachment(
            act_id=act_id,
            scene_id=scene_id,
            beat_id=beat_id,
            attachment_id=attachment_id,
        )
        return [AttachmentInfo.from_play_fs(a) for a in attachments]

    # --- Utility Methods ---

    def get_active_act_context(self) -> dict[str, Any] | None:
        """Get full context for the active act.

        Returns dict with act and scenes (v4 2-tier structure) or None if no active act.
        """
        acts, active_id = self.list_acts()
        if not active_id:
            return None

        active_act = next((a for a in acts if a.act_id == active_id), None)
        if not active_act:
            return None

        scenes = self.list_scenes(active_id)

        return {
            "act": active_act.to_dict(),
            "scenes": [s.to_dict() for s in scenes],
        }

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search across all Play content.

        Searches story, act titles, scene titles/notes.

        Returns:
            List of matching items with type and content
        """
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Search story
        story = self.read_story()
        if query_lower in story.lower():
            results.append({
                "type": "story",
                "title": "Your Story",
                "snippet": self._extract_snippet(story, query_lower),
            })

        # Search acts
        acts, _ = self.list_acts()
        for act in acts:
            if query_lower in act.title.lower() or query_lower in act.notes.lower():
                results.append({
                    "type": "act",
                    "act_id": act.act_id,
                    "title": act.title,
                    "snippet": self._extract_snippet(
                        act.title + " " + act.notes, query_lower
                    ),
                })

            # Search scenes under this act
            scenes = self.list_scenes(act.act_id)
            for scene in scenes:
                if query_lower in scene.title.lower() or query_lower in scene.notes.lower():
                    results.append({
                        "type": "scene",
                        "act_id": act.act_id,
                        "scene_id": scene.scene_id,
                        "title": scene.title,
                        "snippet": self._extract_snippet(
                            scene.title + " " + scene.notes, query_lower
                        ),
                    })

        return results

    def _extract_snippet(self, text: str, query: str, context: int = 50) -> str:
        """Extract a snippet around the query match."""
        idx = text.lower().find(query)
        if idx < 0:
            return text[:100] + "..." if len(text) > 100 else text

        start = max(0, idx - context)
        end = min(len(text), idx + len(query) + context)

        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet
