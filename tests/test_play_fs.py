"""Tests for play_fs.py - File-based Play operations and KB management.

Tests the filesystem layer for The Play:
- Path utilities and helpers
- Act/Scene/Beat dataclass conversions
- KB file operations (list, read, write preview/apply)
- me.md (Your Story) operations
- File attachment operations
- Validation functions
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch, MagicMock

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Create isolated data directory for play_fs."""
    data_dir = tmp_path / "reos-data"
    data_dir.mkdir()
    monkeypatch.setenv("REOS_DATA_DIR", str(data_dir))

    # Close any existing connection before test
    import reos.play_db as play_db
    play_db.close_connection()

    yield data_dir

    # Cleanup after test
    play_db.close_connection()


@pytest.fixture
def initialized_fs(temp_data_dir: Path) -> Path:
    """Initialize play filesystem and return data dir."""
    import reos.play_db as play_db
    from reos.play_fs import ensure_play_skeleton

    play_db.init_db()
    ensure_play_skeleton()
    return temp_data_dir


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestSceneStageEnum:
    """Test SceneStage enum values."""

    def test_enum_values(self) -> None:
        """SceneStage should have expected values."""
        from reos.play_fs import SceneStage

        assert SceneStage.PLANNING.value == "planning"
        assert SceneStage.IN_PROGRESS.value == "in_progress"
        assert SceneStage.AWAITING_DATA.value == "awaiting_data"
        assert SceneStage.COMPLETE.value == "complete"

    def test_beat_stage_alias(self) -> None:
        """BeatStage should be alias for SceneStage."""
        from reos.play_fs import SceneStage, BeatStage

        assert BeatStage is SceneStage


class TestActDataclass:
    """Test Act dataclass."""

    def test_act_creation(self) -> None:
        """Act should store all fields."""
        from reos.play_fs import Act

        act = Act(
            act_id="act-123",
            title="Test Act",
            active=True,
            notes="Test notes",
            color="#8b5cf6",
            repo_path="/home/user/project",
            artifact_type="python",
            code_config={"test_command": "pytest"},
        )

        assert act.act_id == "act-123"
        assert act.title == "Test Act"
        assert act.active is True
        assert act.notes == "Test notes"
        assert act.color == "#8b5cf6"
        assert act.repo_path == "/home/user/project"
        assert act.artifact_type == "python"
        assert act.code_config == {"test_command": "pytest"}

    def test_act_defaults(self) -> None:
        """Act should have sensible defaults."""
        from reos.play_fs import Act

        act = Act(act_id="act-1", title="Minimal")

        assert act.active is False
        assert act.notes == ""
        assert act.color is None
        assert act.repo_path is None


class TestSceneDataclass:
    """Test Scene dataclass."""

    def test_scene_creation(self) -> None:
        """Scene should store all fields."""
        from reos.play_fs import Scene

        scene = Scene(
            scene_id="scene-123",
            act_id="act-456",
            title="Test Scene",
            stage="in_progress",
            notes="Scene notes",
            link="https://example.com",
            calendar_event_id="cal-789",
            recurrence_rule="FREQ=WEEKLY",
            thunderbird_event_id="tb-event-1",
        )

        assert scene.scene_id == "scene-123"
        assert scene.act_id == "act-456"
        assert scene.title == "Test Scene"
        assert scene.stage == "in_progress"
        assert scene.notes == "Scene notes"
        assert scene.link == "https://example.com"
        assert scene.calendar_event_id == "cal-789"
        assert scene.recurrence_rule == "FREQ=WEEKLY"
        assert scene.thunderbird_event_id == "tb-event-1"


class TestBeatDataclass:
    """Test Beat dataclass (backward compatibility)."""

    def test_beat_creation(self) -> None:
        """Beat should store all fields."""
        from reos.play_fs import Beat

        beat = Beat(
            beat_id="beat-123",
            title="Test Beat",
            stage="planning",
            notes="Beat notes",
            link="https://example.com/task",
        )

        assert beat.beat_id == "beat-123"
        assert beat.title == "Test Beat"
        assert beat.stage == "planning"


class TestFileAttachmentDataclass:
    """Test FileAttachment dataclass."""

    def test_attachment_creation(self) -> None:
        """FileAttachment should store path info."""
        from reos.play_fs import FileAttachment

        attachment = FileAttachment(
            attachment_id="att-123",
            file_path="/home/user/docs/report.pdf",
            file_name="report.pdf",
            file_type="pdf",
            added_at="2024-01-15T10:00:00",
        )

        assert attachment.attachment_id == "att-123"
        assert attachment.file_path == "/home/user/docs/report.pdf"
        assert attachment.file_name == "report.pdf"
        assert attachment.file_type == "pdf"


# =============================================================================
# Path Helper Tests
# =============================================================================


class TestPlayRoot:
    """Test play_root function."""

    def test_play_root_with_env_var(self, temp_data_dir: Path) -> None:
        """Should use REOS_DATA_DIR if set."""
        from reos.play_fs import play_root

        root = play_root()
        assert root == temp_data_dir / "play"

    def test_play_root_with_crypto_storage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should use crypto storage path when available."""
        from reos.play_fs import play_root

        mock_crypto = MagicMock()
        mock_crypto.user_data_root = Path("/secure/user")

        with patch("reos.play_fs.get_current_crypto_storage", return_value=mock_crypto):
            root = play_root()
            assert root == Path("/secure/user/play")


class TestActPathHelpers:
    """Test Act-related path helpers."""

    def test_acts_path(self, temp_data_dir: Path) -> None:
        """_acts_path should return correct path."""
        from reos.play_fs import _acts_path, play_root

        assert _acts_path() == play_root() / "acts.json"

    def test_me_path(self, temp_data_dir: Path) -> None:
        """_me_path should return correct path."""
        from reos.play_fs import _me_path, play_root

        assert _me_path() == play_root() / "me.md"

    def test_act_dir(self, temp_data_dir: Path) -> None:
        """_act_dir should return correct path."""
        from reos.play_fs import _act_dir, play_root

        assert _act_dir("act-123") == play_root() / "acts" / "act-123"

    def test_scenes_path(self, temp_data_dir: Path) -> None:
        """_scenes_path should return correct path."""
        from reos.play_fs import _scenes_path, play_root

        assert _scenes_path("act-123") == play_root() / "acts" / "act-123" / "scenes.json"


# =============================================================================
# Skeleton and Me.md Tests
# =============================================================================


class TestEnsurePlaySkeleton:
    """Test ensure_play_skeleton function."""

    def test_creates_directories(self, temp_data_dir: Path) -> None:
        """Should create play directories."""
        from reos.play_fs import ensure_play_skeleton, play_root

        ensure_play_skeleton()

        assert play_root().exists()
        assert (play_root() / "acts").exists()

    def test_creates_me_md(self, temp_data_dir: Path) -> None:
        """Should create me.md file."""
        from reos.play_fs import ensure_play_skeleton, _me_path

        ensure_play_skeleton()

        me_path = _me_path()
        assert me_path.exists()
        content = me_path.read_text()
        assert "# Me (The Play)" in content

    def test_creates_acts_json(self, temp_data_dir: Path) -> None:
        """Should create acts.json file."""
        from reos.play_fs import ensure_play_skeleton, _acts_path

        ensure_play_skeleton()

        acts_path = _acts_path()
        assert acts_path.exists()

    def test_idempotent(self, temp_data_dir: Path) -> None:
        """Should be safe to call multiple times."""
        from reos.play_fs import ensure_play_skeleton, _me_path

        ensure_play_skeleton()
        content1 = _me_path().read_text()

        ensure_play_skeleton()
        content2 = _me_path().read_text()

        assert content1 == content2


class TestMeMarkdown:
    """Test me.md read/write functions."""

    def test_read_me_markdown(self, initialized_fs: Path) -> None:
        """Should read me.md content."""
        from reos.play_fs import read_me_markdown

        content = read_me_markdown()
        assert "# Me (The Play)" in content

    def test_write_me_markdown(self, initialized_fs: Path) -> None:
        """Should write me.md content."""
        from reos.play_fs import write_me_markdown, read_me_markdown

        write_me_markdown("# Custom Content\n\nMy notes.")

        content = read_me_markdown()
        assert "# Custom Content" in content
        assert "My notes." in content


# =============================================================================
# Dict to Dataclass Conversion Tests
# =============================================================================


class TestDictConversions:
    """Test dict to dataclass conversion functions."""

    def test_dict_to_act(self) -> None:
        """Should convert dict to Act."""
        from reos.play_fs import _dict_to_act

        data = {
            "act_id": "act-123",
            "title": "Test",
            "active": True,
            "notes": "Notes",
            "color": "#ff0000",
            "repo_path": "/path/to/repo",
            "artifact_type": "python",
            "code_config": {"key": "value"},
        }
        act = _dict_to_act(data)

        assert act.act_id == "act-123"
        assert act.active is True
        assert act.repo_path == "/path/to/repo"

    def test_dict_to_act_defaults(self) -> None:
        """Should handle missing fields with defaults."""
        from reos.play_fs import _dict_to_act

        data = {}
        act = _dict_to_act(data)

        assert act.act_id == ""
        assert act.title == ""
        assert act.active is False
        assert act.color is None

    def test_dict_to_scene(self) -> None:
        """Should convert dict to Scene."""
        from reos.play_fs import _dict_to_scene, SceneStage

        data = {
            "scene_id": "scene-1",
            "act_id": "act-1",
            "title": "Scene Title",
            "stage": "complete",
            "notes": "Notes",
        }
        scene = _dict_to_scene(data)

        assert scene.scene_id == "scene-1"
        assert scene.stage == "complete"

    def test_dict_to_scene_defaults(self) -> None:
        """Should use PLANNING as default stage."""
        from reos.play_fs import _dict_to_scene, SceneStage

        data = {}
        scene = _dict_to_scene(data)

        assert scene.stage == SceneStage.PLANNING.value

    def test_dict_to_beat(self) -> None:
        """Should convert dict to Beat."""
        from reos.play_fs import _dict_to_beat

        data = {
            "beat_id": "beat-1",
            "title": "Beat Title",
            "stage": "in_progress",
            "notes": "Notes",
        }
        beat = _dict_to_beat(data)

        assert beat.beat_id == "beat-1"
        assert beat.stage == "in_progress"

    def test_dict_to_beat_accepts_scene_id(self) -> None:
        """Should accept scene_id as fallback for beat_id."""
        from reos.play_fs import _dict_to_beat

        data = {"scene_id": "scene-as-beat"}
        beat = _dict_to_beat(data)

        assert beat.beat_id == "scene-as-beat"


# =============================================================================
# Validation Tests
# =============================================================================


class TestValidateId:
    """Test _validate_id function."""

    def test_valid_id(self) -> None:
        """Should accept valid IDs."""
        from reos.play_fs import _validate_id

        _validate_id(name="test", value="valid-id-123")  # Should not raise

    def test_empty_id(self) -> None:
        """Should reject empty IDs."""
        from reos.play_fs import _validate_id

        with pytest.raises(ValueError, match="non-empty string"):
            _validate_id(name="test", value="")

    def test_whitespace_id(self) -> None:
        """Should reject whitespace-only IDs."""
        from reos.play_fs import _validate_id

        with pytest.raises(ValueError, match="non-empty string"):
            _validate_id(name="test", value="   ")

    def test_id_with_slash(self) -> None:
        """Should reject IDs with path separators."""
        from reos.play_fs import _validate_id

        with pytest.raises(ValueError, match="invalid"):
            _validate_id(name="test", value="path/traversal")

    def test_id_with_backslash(self) -> None:
        """Should reject IDs with backslash."""
        from reos.play_fs import _validate_id

        with pytest.raises(ValueError, match="invalid"):
            _validate_id(name="test", value="path\\traversal")

    def test_id_with_dotdot(self) -> None:
        """Should reject IDs with parent directory traversal."""
        from reos.play_fs import _validate_id

        with pytest.raises(ValueError, match="invalid"):
            _validate_id(name="test", value="attack..attempt")


# =============================================================================
# Color Palette Tests
# =============================================================================


class TestColorPalette:
    """Test color palette and assignment."""

    def test_palette_has_colors(self) -> None:
        """ACT_COLOR_PALETTE should have colors."""
        from reos.play_fs import ACT_COLOR_PALETTE

        assert len(ACT_COLOR_PALETTE) > 0
        assert all(c.startswith("#") for c in ACT_COLOR_PALETTE)

    def test_pick_unused_color(self) -> None:
        """Should pick unused color."""
        from reos.play_fs import _pick_unused_color, Act, ACT_COLOR_PALETTE

        existing = []
        color = _pick_unused_color(existing)
        assert color == ACT_COLOR_PALETTE[0]

    def test_pick_unused_color_skips_used(self) -> None:
        """Should skip already used colors."""
        from reos.play_fs import _pick_unused_color, Act, ACT_COLOR_PALETTE

        existing = [
            Act(act_id="1", title="1", color=ACT_COLOR_PALETTE[0]),
        ]
        color = _pick_unused_color(existing)
        assert color == ACT_COLOR_PALETTE[1]

    def test_pick_unused_color_wraps(self) -> None:
        """Should wrap around when all colors used."""
        from reos.play_fs import _pick_unused_color, Act, ACT_COLOR_PALETTE

        existing = [
            Act(act_id=str(i), title=str(i), color=c)
            for i, c in enumerate(ACT_COLOR_PALETTE)
        ]
        color = _pick_unused_color(existing)
        assert color == ACT_COLOR_PALETTE[0]


# =============================================================================
# KB Operations Tests
# =============================================================================


class TestKbRootFor:
    """Test _kb_root_for path resolution."""

    def test_act_level(self, temp_data_dir: Path) -> None:
        """Should return Act-level KB root."""
        from reos.play_fs import _kb_root_for, play_root

        path = _kb_root_for(act_id="act-1")
        assert path == play_root() / "kb" / "acts" / "act-1"

    def test_scene_level(self, temp_data_dir: Path) -> None:
        """Should return Scene-level KB root."""
        from reos.play_fs import _kb_root_for, play_root

        path = _kb_root_for(act_id="act-1", scene_id="scene-1")
        assert path == play_root() / "kb" / "acts" / "act-1" / "scenes" / "scene-1"

    def test_beat_level(self, temp_data_dir: Path) -> None:
        """Should return Beat-level KB root."""
        from reos.play_fs import _kb_root_for, play_root

        path = _kb_root_for(act_id="act-1", scene_id="scene-1", beat_id="beat-1")
        expected = play_root() / "kb" / "acts" / "act-1" / "scenes" / "scene-1" / "beats" / "beat-1"
        assert path == expected


class TestResolveKbFile:
    """Test _resolve_kb_file path resolution."""

    def test_resolve_relative_path(self, temp_data_dir: Path) -> None:
        """Should resolve relative paths."""
        from reos.play_fs import _resolve_kb_file

        kb_root = temp_data_dir / "kb"
        kb_root.mkdir(parents=True)

        result = _resolve_kb_file(kb_root=kb_root, rel_path="kb.md")
        assert result == kb_root / "kb.md"

    def test_reject_absolute_path(self, temp_data_dir: Path) -> None:
        """Should reject absolute paths."""
        from reos.play_fs import _resolve_kb_file

        kb_root = temp_data_dir / "kb"

        with pytest.raises(ValueError, match="relative"):
            _resolve_kb_file(kb_root=kb_root, rel_path="/etc/passwd")

    def test_reject_path_traversal(self, temp_data_dir: Path) -> None:
        """Should reject path traversal."""
        from reos.play_fs import _resolve_kb_file

        kb_root = temp_data_dir / "kb"

        with pytest.raises(ValueError, match="escapes"):
            _resolve_kb_file(kb_root=kb_root, rel_path="../escape.txt")

    def test_reject_empty_path(self, temp_data_dir: Path) -> None:
        """Should reject empty paths."""
        from reos.play_fs import _resolve_kb_file

        kb_root = temp_data_dir / "kb"

        with pytest.raises(ValueError, match="required"):
            _resolve_kb_file(kb_root=kb_root, rel_path="")


class TestKbListFiles:
    """Test kb_list_files function."""

    def test_list_files_creates_default(self, initialized_fs: Path) -> None:
        """Should create default kb.md if missing."""
        import reos.play_db as play_db
        from reos.play_fs import kb_list_files

        # Create an act first
        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        files = kb_list_files(act_id=act_id)
        assert "kb.md" in files

    def test_list_files_finds_md_files(self, initialized_fs: Path) -> None:
        """Should find .md and .txt files."""
        import reos.play_db as play_db
        from reos.play_fs import kb_list_files, _kb_root_for

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        kb_root = _kb_root_for(act_id=act_id)
        kb_root.mkdir(parents=True, exist_ok=True)
        (kb_root / "notes.md").write_text("Notes", encoding="utf-8")
        (kb_root / "data.txt").write_text("Data", encoding="utf-8")
        (kb_root / "ignore.json").write_text("{}", encoding="utf-8")

        files = kb_list_files(act_id=act_id)
        assert "notes.md" in files
        assert "data.txt" in files
        assert "ignore.json" not in files


class TestKbRead:
    """Test kb_read function."""

    def test_read_creates_default(self, initialized_fs: Path) -> None:
        """Should create default kb.md on first read."""
        import reos.play_db as play_db
        from reos.play_fs import kb_read

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        content = kb_read(act_id=act_id)
        assert "# KB" in content

    def test_read_existing_file(self, initialized_fs: Path) -> None:
        """Should read existing KB file."""
        import reos.play_db as play_db
        from reos.play_fs import kb_read, _kb_root_for

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        kb_root = _kb_root_for(act_id=act_id)
        kb_root.mkdir(parents=True, exist_ok=True)
        (kb_root / "kb.md").write_text("# Custom KB\n\nContent here.", encoding="utf-8")

        content = kb_read(act_id=act_id)
        assert "# Custom KB" in content

    def test_read_nonexistent_raises(self, initialized_fs: Path) -> None:
        """Should raise FileNotFoundError for missing non-default file."""
        import reos.play_db as play_db
        from reos.play_fs import kb_read

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        with pytest.raises(FileNotFoundError):
            kb_read(act_id=act_id, path="nonexistent.md")


class TestKbWritePreview:
    """Test kb_write_preview function."""

    def test_preview_new_file(self, initialized_fs: Path) -> None:
        """Should preview creating new file."""
        import reos.play_db as play_db
        from reos.play_fs import kb_write_preview

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        result = kb_write_preview(
            act_id=act_id,
            path="new.md",
            text="# New Content"
        )

        assert result["exists"] is False
        assert result["sha256_new"] is not None

    def test_preview_existing_file(self, initialized_fs: Path) -> None:
        """Should show diff for existing file."""
        import reos.play_db as play_db
        from reos.play_fs import kb_write_preview, _kb_root_for

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        kb_root = _kb_root_for(act_id=act_id)
        kb_root.mkdir(parents=True, exist_ok=True)
        (kb_root / "edit.md").write_text("Original content", encoding="utf-8")

        result = kb_write_preview(
            act_id=act_id,
            path="edit.md",
            text="Modified content"
        )

        assert result["exists"] is True
        assert "-Original content" in result["diff"]
        assert "+Modified content" in result["diff"]


class TestKbWriteApply:
    """Test kb_write_apply function."""

    def test_apply_creates_file(self, initialized_fs: Path) -> None:
        """Should create new file."""
        import reos.play_db as play_db
        from reos.play_fs import kb_write_apply, kb_write_preview, _kb_root_for

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        # Get preview first to get current SHA
        preview = kb_write_preview(act_id=act_id, path="new.md", text="Content")

        result = kb_write_apply(
            act_id=act_id,
            path="new.md",
            text="Content",
            expected_sha256_current=preview["sha256_current"],
        )

        assert result["ok"] is True

        # Verify file was created
        kb_root = _kb_root_for(act_id=act_id)
        assert (kb_root / "new.md").read_text() == "Content"

    def test_apply_rejects_conflict(self, initialized_fs: Path) -> None:
        """Should reject if file changed since preview."""
        import reos.play_db as play_db
        from reos.play_fs import kb_write_apply, _kb_root_for

        play_db.create_act(title="Test", notes="", color="#000000")
        acts, _ = play_db.list_acts()
        act_id = acts[0]["act_id"]

        kb_root = _kb_root_for(act_id=act_id)
        kb_root.mkdir(parents=True, exist_ok=True)
        (kb_root / "conflict.md").write_text("Original", encoding="utf-8")

        with pytest.raises(ValueError, match="conflict"):
            kb_write_apply(
                act_id=act_id,
                path="conflict.md",
                text="New",
                expected_sha256_current="wrong_sha",
            )


# =============================================================================
# Act Operations Tests (via play_db)
# =============================================================================


class TestActOperations:
    """Test Act CRUD operations."""

    def test_create_act(self, initialized_fs: Path) -> None:
        """Should create act with auto color."""
        from reos.play_fs import create_act, ACT_COLOR_PALETTE

        acts, act_id = create_act(title="My Act", notes="Notes")

        assert act_id is not None
        found = next((a for a in acts if a.act_id == act_id), None)
        assert found is not None
        assert found.title == "My Act"
        assert found.color == ACT_COLOR_PALETTE[0]  # First color

    def test_create_act_with_custom_color(self, initialized_fs: Path) -> None:
        """Should use provided color."""
        from reos.play_fs import create_act

        acts, act_id = create_act(title="Custom", color="#ff0000")

        found = next((a for a in acts if a.act_id == act_id), None)
        assert found.color == "#ff0000"

    def test_create_act_validates_title(self, initialized_fs: Path) -> None:
        """Should reject empty title."""
        from reos.play_fs import create_act

        with pytest.raises(ValueError, match="title"):
            create_act(title="")

    def test_update_act(self, initialized_fs: Path) -> None:
        """Should update act fields."""
        from reos.play_fs import create_act, update_act

        acts, act_id = create_act(title="Original")
        acts, _ = update_act(act_id=act_id, title="Updated", notes="New notes")

        found = next((a for a in acts if a.act_id == act_id), None)
        assert found.title == "Updated"
        assert found.notes == "New notes"

    def test_delete_act(self, initialized_fs: Path) -> None:
        """Should delete act."""
        from reos.play_fs import create_act, delete_act

        acts, act_id = create_act(title="To Delete")
        acts, _ = delete_act(act_id=act_id)

        found = next((a for a in acts if a.act_id == act_id), None)
        assert found is None

    def test_delete_your_story_protected(self, initialized_fs: Path) -> None:
        """Should not allow deleting Your Story act."""
        from reos.play_fs import delete_act, YOUR_STORY_ACT_ID

        with pytest.raises(ValueError, match="protected"):
            delete_act(act_id=YOUR_STORY_ACT_ID)


# =============================================================================
# Scene Operations Tests
# =============================================================================


class TestSceneOperations:
    """Test Scene CRUD operations."""

    def test_create_scene(self, initialized_fs: Path) -> None:
        """Should create scene."""
        from reos.play_fs import create_act, create_scene, SceneStage

        _, act_id = create_act(title="Act")
        scenes, scene_id = create_scene(act_id=act_id, title="Scene 1")

        assert scene_id is not None
        found = next((s for s in scenes if s.scene_id == scene_id), None)
        assert found.title == "Scene 1"
        assert found.stage == SceneStage.PLANNING.value

    def test_create_scene_validates_title(self, initialized_fs: Path) -> None:
        """Should reject empty title."""
        from reos.play_fs import create_act, create_scene

        _, act_id = create_act(title="Act")

        with pytest.raises(ValueError, match="title"):
            create_scene(act_id=act_id, title="")

    def test_update_scene(self, initialized_fs: Path) -> None:
        """Should update scene fields."""
        from reos.play_fs import create_act, create_scene, update_scene

        _, act_id = create_act(title="Act")
        _, scene_id = create_scene(act_id=act_id, title="Original")

        scenes = update_scene(
            act_id=act_id,
            scene_id=scene_id,
            title="Updated",
            stage="complete",
        )

        found = next((s for s in scenes if s.scene_id == scene_id), None)
        assert found.title == "Updated"
        assert found.stage == "complete"

    def test_delete_scene(self, initialized_fs: Path) -> None:
        """Should delete scene."""
        from reos.play_fs import create_act, create_scene, delete_scene

        _, act_id = create_act(title="Act")
        _, scene_id = create_scene(act_id=act_id, title="To Delete")

        scenes = delete_scene(act_id=act_id, scene_id=scene_id)

        found = next((s for s in scenes if s.scene_id == scene_id), None)
        assert found is None


# =============================================================================
# Stage Direction Tests
# =============================================================================


class TestStageDirection:
    """Test Stage Direction scene handling."""

    def test_get_stage_direction_scene_id(self) -> None:
        """Should generate consistent stage direction ID."""
        from reos.play_fs import _get_stage_direction_scene_id, STAGE_DIRECTION_SCENE_ID_PREFIX

        scene_id = _get_stage_direction_scene_id("act-123456789abc")
        assert scene_id.startswith(STAGE_DIRECTION_SCENE_ID_PREFIX)
        assert "act-12345678" in scene_id

    def test_cannot_delete_stage_direction(self, initialized_fs: Path) -> None:
        """Should not allow deleting Stage Direction scene."""
        from reos.play_fs import create_act, delete_scene, _get_stage_direction_scene_id

        _, act_id = create_act(title="Act")
        stage_dir_id = _get_stage_direction_scene_id(act_id)

        with pytest.raises(ValueError, match="protected"):
            delete_scene(act_id=act_id, scene_id=stage_dir_id)


# =============================================================================
# Your Story Act Tests
# =============================================================================


class TestYourStoryAct:
    """Test Your Story act functionality."""

    def test_ensure_your_story_creates_act(self, initialized_fs: Path) -> None:
        """Should create Your Story act if missing."""
        from reos.play_fs import ensure_your_story_act, YOUR_STORY_ACT_ID

        acts, your_story_id = ensure_your_story_act()

        assert your_story_id == YOUR_STORY_ACT_ID
        found = next((a for a in acts if a.act_id == YOUR_STORY_ACT_ID), None)
        assert found is not None
        assert found.title == "Your Story"
