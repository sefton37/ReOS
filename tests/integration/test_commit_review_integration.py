"""Integration tests for commit review workflow.

These tests verify the commit watch → review → event flow:
1. Commit detection
2. Review generation (with mock)
3. Event storage
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from .conftest import MockCommitReviewer, run_git


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    """Create a new settings object with overrides and patch the module.

    We need to patch both the settings module AND the commit_watch module
    since commit_watch imports settings at the top level.
    """
    from reos import settings as settings_mod
    from reos import commit_watch as commit_watch_mod

    new_settings = replace(settings_mod.settings, **overrides)
    monkeypatch.setattr(settings_mod, "settings", new_settings)
    monkeypatch.setattr(commit_watch_mod, "settings", new_settings)


class TestCommitDetection:
    """Test commit detection logic."""

    def test_poll_initializes_state_without_review(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """First poll should initialize state without reviewing."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        # Enable auto review
        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
        )

        db = get_db()
        events = poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # First call should initialize, not review
        assert events == []
        assert len(mock_reviewer.calls) == 0

    def test_poll_detects_new_commit(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poll should detect and review new commits."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
        )

        db = get_db()
        repo = configured_integration_repo

        # First poll to initialize
        poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Make a new commit
        (repo / "new_feature.py").write_text("# New feature\n", encoding="utf-8")
        run_git(repo, ["add", "new_feature.py"])
        run_git(repo, ["commit", "-m", "Add new feature"])

        # Second poll should detect and review
        events = poll_commits_and_review(db=db, reviewer=mock_reviewer)

        assert len(events) == 1
        assert events[0].subject == "Add new feature"
        assert events[0].review_text == "LGTM. No issues found."
        assert len(mock_reviewer.calls) == 1

    def test_poll_respects_cooldown(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poll should respect cooldown between reviews."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
            auto_review_commits_cooldown_seconds=60,
        )

        db = get_db()
        repo = configured_integration_repo

        # Initialize
        poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # First commit
        (repo / "file1.py").write_text("# File 1\n", encoding="utf-8")
        run_git(repo, ["add", "file1.py"])
        run_git(repo, ["commit", "-m", "First commit"])

        events1 = poll_commits_and_review(db=db, reviewer=mock_reviewer)
        assert len(events1) == 1

        # Second commit immediately after
        (repo / "file2.py").write_text("# File 2\n", encoding="utf-8")
        run_git(repo, ["add", "file2.py"])
        run_git(repo, ["commit", "-m", "Second commit"])

        events2 = poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Should be blocked by cooldown
        assert len(events2) == 0


class TestReviewEventStorage:
    """Test that reviews are stored as events."""

    def test_review_creates_event(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Review should create an event in the database."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
        )

        db = get_db()
        repo = configured_integration_repo

        # Initialize
        poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Make commit
        (repo / "reviewed.py").write_text("# Reviewed\n", encoding="utf-8")
        run_git(repo, ["add", "reviewed.py"])
        run_git(repo, ["commit", "-m", "Add reviewed file"])

        poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Check event was stored
        events = list(db.iter_events_recent(limit=10))
        review_events = [e for e in events if e.get("kind") == "commit_review"]

        assert len(review_events) >= 1
        event = review_events[0]
        assert "commit_review" in event.get("kind", "")


class TestDisabledReview:
    """Test that review is disabled by default."""

    def test_poll_does_nothing_when_disabled(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poll should do nothing when auto review is disabled."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(monkeypatch, auto_review_commits=False)

        db = get_db()
        repo = configured_integration_repo

        # Make commit
        (repo / "ignored.py").write_text("# Ignored\n", encoding="utf-8")
        run_git(repo, ["add", "ignored.py"])
        run_git(repo, ["commit", "-m", "Add ignored file"])

        events = poll_commits_and_review(db=db, reviewer=mock_reviewer)

        assert events == []
        assert len(mock_reviewer.calls) == 0

    def test_poll_requires_diff_optin(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poll should require explicit diff opt-in."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=False,
        )

        db = get_db()
        repo = configured_integration_repo

        # Make commit
        (repo / "no_diff.py").write_text("# No diff\n", encoding="utf-8")
        run_git(repo, ["add", "no_diff.py"])
        run_git(repo, ["commit", "-m", "Add no diff file"])

        events = poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Should not review without diff opt-in
        assert events == []


class TestCommitReviewContent:
    """Test the review content itself."""

    def test_review_receives_commit_info(
        self,
        configured_integration_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reviewer should receive commit information."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
        )

        captured_inputs = []

        class CapturingReviewer:
            def review(self, input_data):
                captured_inputs.append(input_data)
                return "Captured review."

        db = get_db()
        repo = configured_integration_repo

        # Initialize
        poll_commits_and_review(db=db, reviewer=CapturingReviewer())

        # Make commit
        (repo / "captured.py").write_text("# Captured\n", encoding="utf-8")
        run_git(repo, ["add", "captured.py"])
        run_git(repo, ["commit", "-m", "Add captured file"])

        poll_commits_and_review(db=db, reviewer=CapturingReviewer())

        assert len(captured_inputs) == 1
        review_input = captured_inputs[0]
        assert review_input.repo_path == repo
        assert len(review_input.commit_sha) == 40  # Full SHA


class TestMultipleCommits:
    """Test handling of multiple commits."""

    def test_poll_tracks_head_across_commits(
        self,
        configured_integration_repo: Path,
        mock_reviewer: MockCommitReviewer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poll should track HEAD and detect first new commit."""
        from reos.commit_watch import poll_commits_and_review
        from reos.db import get_db

        _patch_settings(
            monkeypatch,
            auto_review_commits=True,
            auto_review_commits_include_diff=True,
            auto_review_commits_cooldown_seconds=0,
        )

        db = get_db()
        repo = configured_integration_repo

        # Initialize
        poll_commits_and_review(db=db, reviewer=mock_reviewer)

        # Make first commit
        (repo / "commit1.py").write_text("# 1\n", encoding="utf-8")
        run_git(repo, ["add", "commit1.py"])
        run_git(repo, ["commit", "-m", "Commit 1"])

        events1 = poll_commits_and_review(db=db, reviewer=mock_reviewer)
        assert len(events1) == 1
        sha1 = events1[0].commit_sha

        # Polling again without new commits should return empty
        events2 = poll_commits_and_review(db=db, reviewer=mock_reviewer)
        assert len(events2) == 0

        # The SHA should be a 40-char hex string
        assert len(sha1) == 40
        assert all(c in "0123456789abcdef" for c in sha1)
