from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reos.models import Event
from reos.storage import append_event


def test_alignment_trigger_is_never_emitted(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Create enough unmapped changed files that would have previously produced an alignment_trigger.
    # Make them tracked so we don't depend on untracked visibility.
    paths: list[Path] = []
    for i in range(6):
        p = repo / "src" / "reos" / f"unmapped_{i}.py"
        p.write_text(f"# unmapped {i}\n", encoding="utf-8")
        paths.append(p)

    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-m", "add unmapped files"],
        check=True,
        capture_output=True,
        text=True,
    )

    for p in paths:
        p.write_text(p.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    import reos.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_default_repo_path", lambda: repo)

    append_event(Event(source="test", ts=datetime.now(UTC), payload_metadata={"kind": "evt"}))

    from reos.db import get_db

    rows = get_db().iter_events_recent(limit=50)
    assert sum(1 for r in rows if r.get("kind") == "alignment_trigger") == 0
