"""Tests for KB write conflict detection in play_fs module."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_play_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up an isolated play root for testing."""
    play_dir = tmp_path / "play"
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path))
    return play_dir


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_kb_write_conflict_detection(isolated_play_root: Path) -> None:
    """Test that SHA256 mismatch blocks apply."""
    from reos.play_fs import create_act, kb_read, kb_write_apply, kb_write_preview

    # Create an act
    acts, act_id = create_act(title="Test Act")
    assert act_id is not None

    # Read the default kb.md
    initial_text = kb_read(act_id=act_id, path="kb.md")
    initial_sha = _sha256(initial_text)

    # Preview a write
    preview = kb_write_preview(act_id=act_id, path="kb.md", text="# Updated KB\n\nNew content.\n")
    assert preview["sha256_current"] == initial_sha
    assert preview["sha256_new"] != initial_sha
    assert "diff" in preview

    # Simulate conflict: apply with wrong sha256
    wrong_sha = "0" * 64
    with pytest.raises(ValueError, match="conflict"):
        kb_write_apply(
            act_id=act_id,
            path="kb.md",
            text="# Conflicting\n",
            expected_sha256_current=wrong_sha,
        )

    # Apply with correct sha256 should work
    result = kb_write_apply(
        act_id=act_id,
        path="kb.md",
        text="# Updated KB\n\nNew content.\n",
        expected_sha256_current=initial_sha,
    )
    assert result["ok"] is True


def test_kb_write_apply_after_external_modification(isolated_play_root: Path) -> None:
    """Test that external modifications are detected."""
    from reos.play_fs import create_act, kb_read, kb_write_apply, kb_write_preview, play_root

    # Create an act
    acts, act_id = create_act(title="External Mod Test")

    # Get preview
    preview = kb_write_preview(act_id=act_id, path="kb.md", text="# My changes\n")
    expected_sha = preview["sha256_current"]

    # Simulate external modification (another process writes to the file)
    kb_path = play_root() / "kb" / "acts" / act_id / "kb.md"
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    kb_path.write_text("# External changes\n", encoding="utf-8")

    # Now apply should fail because file changed
    with pytest.raises(ValueError, match="conflict"):
        kb_write_apply(
            act_id=act_id,
            path="kb.md",
            text="# My changes\n",
            expected_sha256_current=expected_sha,
        )


def test_kb_write_new_file(isolated_play_root: Path) -> None:
    """Test creating a new KB file."""
    from reos.play_fs import create_act, kb_write_apply, kb_write_preview

    acts, act_id = create_act(title="New File Test")

    # Preview writing a new file
    preview = kb_write_preview(act_id=act_id, path="notes.md", text="# Notes\n")
    assert preview["exists"] is False
    # Empty file sha256
    empty_sha = _sha256("")
    assert preview["sha256_current"] == empty_sha

    # Apply
    result = kb_write_apply(
        act_id=act_id,
        path="notes.md",
        text="# Notes\n",
        expected_sha256_current=empty_sha,
    )
    assert result["ok"] is True


def test_kb_path_traversal_blocked(isolated_play_root: Path) -> None:
    """Test that path traversal attempts are blocked."""
    from reos.play_fs import create_act, kb_read, kb_write_preview

    acts, act_id = create_act(title="Security Test")

    # Attempt path traversal in read
    with pytest.raises(ValueError, match="escapes"):
        kb_read(act_id=act_id, path="../../../etc/passwd")

    # Attempt path traversal in write preview
    with pytest.raises(ValueError, match="escapes"):
        kb_write_preview(act_id=act_id, path="../secrets.md", text="bad")

    # Attempt absolute path
    with pytest.raises(ValueError, match="relative"):
        kb_read(act_id=act_id, path="/etc/passwd")


def test_kb_scene_level_isolation(isolated_play_root: Path) -> None:
    """Test that scene-level KB is isolated from act-level."""
    from reos.play_fs import (
        create_act,
        create_scene,
        kb_read,
        kb_write_apply,
        kb_write_preview,
    )

    acts, act_id = create_act(title="Isolation Test")
    scenes = create_scene(act_id=act_id, title="Scene One")
    scene_id = scenes[0].scene_id

    # Write to act-level KB
    act_preview = kb_write_preview(act_id=act_id, path="kb.md", text="# Act KB\n")
    kb_write_apply(
        act_id=act_id,
        path="kb.md",
        text="# Act KB\n",
        expected_sha256_current=act_preview["sha256_current"],
    )

    # Write to scene-level KB
    scene_preview = kb_write_preview(
        act_id=act_id, scene_id=scene_id, path="kb.md", text="# Scene KB\n"
    )
    kb_write_apply(
        act_id=act_id,
        scene_id=scene_id,
        path="kb.md",
        text="# Scene KB\n",
        expected_sha256_current=scene_preview["sha256_current"],
    )

    # Verify they are independent
    act_content = kb_read(act_id=act_id, path="kb.md")
    scene_content = kb_read(act_id=act_id, scene_id=scene_id, path="kb.md")

    assert act_content == "# Act KB\n"
    assert scene_content == "# Scene KB\n"
