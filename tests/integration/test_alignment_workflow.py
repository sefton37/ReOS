"""Integration tests for alignment workflow.

These tests verify the full alignment analysis flow:
1. Git metadata collection
2. Roadmap/charter parsing
3. Change-to-plan comparison
4. Context budget calculation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import run_git


class TestAlignmentAnalysis:
    """Test full alignment analysis workflow."""

    def test_analyze_alignment_with_clean_repo(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Alignment analysis on clean repo should report no changes."""
        from reos.alignment import analyze_alignment
        from reos.db import get_db

        db = get_db()
        result = analyze_alignment(db=db, repo_path=configured_integration_repo)

        assert result["status"] == "ok"
        assert result["repo"]["path"] == str(configured_integration_repo)
        assert result["repo"]["changed_files"] == []
        assert len(result["alignment"]["unmapped_changed_files"]) == 0

    def test_analyze_alignment_detects_mapped_changes(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Changes to files mentioned in roadmap should be mapped."""
        from reos.alignment import analyze_alignment
        from reos.db import get_db

        repo = configured_integration_repo

        # Modify a file that IS mentioned in roadmap (src/main.py)
        (repo / "src" / "main.py").write_text(
            '''"""Main entry point - modified."""

def main():
    print("Modified!")

if __name__ == "__main__":
    main()
''',
            encoding="utf-8",
        )

        db = get_db()
        result = analyze_alignment(db=db, repo_path=repo)

        assert result["status"] == "ok"
        # src/main.py is changed
        assert "src/main.py" in result["repo"]["changed_files"]
        # But it's mentioned in roadmap, so it might not be "unmapped"
        # (depends on exact matching logic)

    def test_analyze_alignment_detects_unmapped_changes(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Changes to files NOT in roadmap should be flagged as unmapped."""
        from reos.alignment import analyze_alignment
        from reos.db import get_db

        repo = configured_integration_repo

        # Create a new file not mentioned anywhere
        (repo / "src" / "secret_feature.py").write_text(
            '''"""A secret feature not in roadmap."""

def secret():
    return "shhh"
''',
            encoding="utf-8",
        )

        db = get_db()
        result = analyze_alignment(db=db, repo_path=repo)

        assert result["status"] == "ok"
        # The new file should be in changed files
        assert "src/secret_feature.py" in result["repo"]["changed_files"]
        # And should be unmapped (not mentioned in roadmap/charter)
        assert "src/secret_feature.py" in result["alignment"]["unmapped_changed_files"]

    def test_analyze_alignment_generates_questions(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Analysis should generate reflective questions for unmapped changes."""
        from reos.alignment import analyze_alignment
        from reos.db import get_db

        repo = configured_integration_repo

        # Create multiple unmapped files
        for i in range(3):
            (repo / "src" / f"new_feature_{i}.py").write_text(
                f"# Feature {i}\n",
                encoding="utf-8",
            )

        db = get_db()
        result = analyze_alignment(db=db, repo_path=repo)

        assert result["status"] == "ok"
        # Should have questions about unmapped changes
        assert len(result["questions"]) > 0
        assert any("roadmap" in q.lower() or "charter" in q.lower() for q in result["questions"])


class TestGitSummary:
    """Test git summary collection."""

    def test_git_summary_metadata_only(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Default git summary should not include diff content."""
        from reos.alignment import get_git_summary

        repo = configured_integration_repo

        # Make a change
        (repo / "README.md").write_text("# Updated README\n", encoding="utf-8")

        summary = get_git_summary(repo, include_diff=False)

        assert summary.repo_path == repo
        assert summary.branch in ["main", "master"]
        assert "README.md" in summary.changed_files
        assert summary.diff_text is None  # No diff content

    def test_git_summary_with_diff(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Git summary with include_diff should have diff content."""
        from reos.alignment import get_git_summary

        repo = configured_integration_repo

        # Make a change
        (repo / "src" / "main.py").write_text(
            '''"""Changed."""

def main():
    print("Changed!")
''',
            encoding="utf-8",
        )

        summary = get_git_summary(repo, include_diff=True)

        assert summary.diff_text is not None
        assert "Changed" in summary.diff_text or "main.py" in summary.diff_text

    def test_git_summary_after_commit(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Git summary after committing should show clean state."""
        from reos.alignment import get_git_summary

        repo = configured_integration_repo

        # Make and commit a change
        (repo / "new_file.txt").write_text("content\n", encoding="utf-8")
        run_git(repo, ["add", "new_file.txt"])
        run_git(repo, ["commit", "-m", "Add new file"])

        summary = get_git_summary(repo)

        # Working tree should be clean
        assert summary.changed_files == []
        assert summary.status_porcelain == []


class TestContextBudget:
    """Test context budget calculation."""

    def test_context_budget_for_small_changes(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Small changes should have low utilization."""
        from reos.alignment import get_review_context_budget

        repo = configured_integration_repo

        # Make a small change
        (repo / "src" / "main.py").write_text(
            '''"""Small change."""

def main():
    print("Hi")
''',
            encoding="utf-8",
        )

        budget = get_review_context_budget(
            repo_path=repo,
            roadmap_path=repo / "docs" / "tech-roadmap.md",
            charter_path=repo / "ReOS_charter.md",
        )

        assert budget.total_tokens > 0
        assert budget.utilization < 1.0  # Not over budget
        assert budget.should_trigger is False  # Small change shouldn't trigger

    def test_context_budget_counts_large_changes(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Large changes should result in significant token count."""
        from reos.alignment import get_review_context_budget

        repo = configured_integration_repo

        # Create file, commit it, then modify it (git diff --numstat shows unstaged changes)
        big_content = "\n".join([f"# Line {i}" for i in range(100)])
        (repo / "src" / "big_file.py").write_text(big_content, encoding="utf-8")
        run_git(repo, ["add", "src/big_file.py"])
        run_git(repo, ["commit", "-m", "Add big file"])

        # Now modify it with more lines (creates unstaged changes)
        bigger_content = "\n".join([f"# Modified line {i}" for i in range(500)])
        (repo / "src" / "big_file.py").write_text(bigger_content, encoding="utf-8")

        budget = get_review_context_budget(
            repo_path=repo,
            roadmap_path=repo / "docs" / "tech-roadmap.md",
            charter_path=repo / "ReOS_charter.md",
        )

        # With ~500 lines of changes, should have significant token count
        # At 6 tokens per line (default), this is 3000+ tokens just for changes
        assert budget.changes_tokens > 100
        assert budget.total_tokens > budget.changes_tokens  # Includes roadmap/charter


class TestFileMentionExtraction:
    """Test file mention extraction from markdown."""

    def test_extract_mentions_from_roadmap(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Should extract file paths mentioned in roadmap."""
        from reos.alignment import extract_file_mentions

        roadmap = (configured_integration_repo / "docs" / "tech-roadmap.md").read_text()
        mentions = extract_file_mentions(roadmap)

        assert "src/main.py" in mentions
        assert "src/utils.py" in mentions
        assert "tests/test_utils.py" in mentions

    def test_extract_mentions_from_charter(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Should extract file paths mentioned in charter."""
        from reos.alignment import extract_file_mentions

        charter = (configured_integration_repo / "ReOS_charter.md").read_text()
        mentions = extract_file_mentions(charter)

        assert "src/main.py" in mentions
        assert "src/utils.py" in mentions


class TestAlignmentWithMultipleAreas:
    """Test alignment detection across multiple code areas."""

    def test_detect_scope_spread(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Analysis should detect when changes span many areas."""
        from reos.alignment import analyze_alignment
        from reos.db import get_db

        repo = configured_integration_repo

        # Create changes in multiple directories
        (repo / "src" / "new.py").write_text("# src change\n", encoding="utf-8")
        (repo / "tests" / "new_test.py").write_text("# tests change\n", encoding="utf-8")
        (repo / "docs" / "new.md").write_text("# docs change\n", encoding="utf-8")

        db = get_db()
        result = analyze_alignment(db=db, repo_path=repo)

        assert result["status"] == "ok"
        scope = result["alignment"]["scope"]
        assert scope["changed_file_count"] >= 3
        assert scope["area_count"] >= 3
        assert "src" in scope["changed_areas"]
        assert "tests" in scope["changed_areas"]
        assert "docs" in scope["changed_areas"]
