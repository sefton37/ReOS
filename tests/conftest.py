from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def isolated_db_singleton(tmp_path: Path) -> Iterator[Path]:
    """Ensure tests do not write to `.reos-data/`.

    This fixture swaps the global DB singleton in `reos.db` to a temp file DB.
    It yields the db path for convenience.
    """

    import reos.db as db_mod

    db_path = tmp_path / "reos-test.db"
    db_mod._db_instance = db_mod.Database(db_path=db_path)
    db_mod._db_instance.migrate()
    try:
        yield db_path
    finally:
        if db_mod._db_instance is not None:
            db_mod._db_instance.close()
        db_mod._db_instance = None


def run_git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with minimal charter/roadmap committed."""

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    run_git(repo, ["init"])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "ReOS Test"])

    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tech-roadmap.md").write_text(
        """# Roadmap\n\nMention: src/reos/example.py\n""",
        encoding="utf-8",
    )
    (repo / "ReOS_charter.md").write_text(
        """# Charter\n\nMention: src/reos/example.py\n""",
        encoding="utf-8",
    )
    (repo / "src" / "reos").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "reos" / "example.py").write_text(
        """def hello() -> str:\n    return \"hello\"\n""",
        encoding="utf-8",
    )

    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "initial"])
    return repo


@pytest.fixture
def active_project_repo(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
) -> Path:
    """Create an active project charter linked to the temp git repo."""

    from reos.db import get_db

    db = get_db()
    repo_id = "repo-test-1"
    db.upsert_repo(repo_id=repo_id, path=str(temp_git_repo))

    base_now = "2025-12-19T00:00:00+00:00"
    project_id = "proj-test-1"
    db.insert_project_charter(
        record={
            "project_id": project_id,
            "repo_id": repo_id,
            "project_name": "Test Project",
            "project_owner": "test",
            "created_at": base_now,
            "last_reaffirmed_at": base_now,
            "core_intent": "Test intent.",
            "problem_statement": "Test problem.",
            "non_goals": "None.",
            "definition_of_done": "Done.",
            "success_signals": "Green.",
            "failure_conditions": "Red.",
            "sunset_criteria": "Stop.",
            "time_horizon": "short",
            "energy_profile": "steady",
            "allowed_scope": "repo-scoped",
            "forbidden_scope": "escape",
            "primary_values": "local-first",
            "acceptable_tradeoffs": "speed",
            "unacceptable_tradeoffs": "surveillance",
            "attention_budget": "default",
            "distraction_tolerance": "low",
            "intervention_style": "gentle",
            "origin_story": "fixture",
            "current_state_summary": "fixture",
            "updated_at": base_now,
            "ingested_at": base_now,
        }
    )
    db.set_active_project_id(project_id=project_id)
    return temp_git_repo
