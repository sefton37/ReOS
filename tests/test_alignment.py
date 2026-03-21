"""Tests for roadmap/charter alignment analysis helpers."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from reos.alignment import extract_file_mentions, infer_active_repo_path
from trcore.db import Database


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository in a temporary directory."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            "HOME": str(tmp_path),
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "PATH": __import__("os").environ["PATH"],
        },
    )
    return tmp_path


def test_extract_file_mentions_basic() -> None:
    text = """
    See src/reos/db.py and src/reos/gui/main_window.py.
    Also check docs/tech-roadmap.md.
    """
    mentions = extract_file_mentions(text)
    assert "src/reos/db.py" in mentions
    assert "src/reos/gui/main_window.py" in mentions
    assert "docs/tech-roadmap.md" in mentions


def test_infer_active_repo_path_from_event(
    temp_db: Database, temp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_db.insert_event(
        event_id="evt-1",
        source="git",
        kind="active_editor",
        ts="2025-12-17T00:00:00+00:00",
        payload_metadata=json.dumps({"workspaceFolder": "/tmp/myrepo", "uri": "file:///tmp/x.py"}),
        note=None,
    )

    # Git-first: repo path comes from settings/workspace, not event payloads.
    # Patch get_default_repo_path to return a real git repo so this test is
    # self-contained and does not depend on the CI working directory being a repo.
    import reos.alignment as _alignment

    monkeypatch.setattr(_alignment, "get_default_repo_path", lambda: temp_git_repo)

    inferred = infer_active_repo_path(temp_db)
    assert inferred is not None
    assert inferred == temp_git_repo
