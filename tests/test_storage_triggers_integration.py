from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reos.models import Event
from reos.storage import append_event


def _count_kind(db_rows: list[dict[str, object]], kind: str) -> int:
    return sum(1 for r in db_rows if r.get("kind") == kind)


def test_append_event_emits_review_trigger_and_throttles(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Create a big change in a single file so alignment_trigger won't fire (file_count=1),
    # but context budget can.
    big = repo / "src" / "reos" / "example.py"
    big.write_text(big.read_text(encoding="utf-8") + ("\n".join(["x = 1"] * 200) + "\n"), encoding="utf-8")

    # Ensure storage looks at our temp repo.
    import reos.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_default_repo_path", lambda: repo)

    # Make budgeting extremely sensitive for this test.
    import reos.alignment as alignment_mod
    import reos.settings as settings_mod

    sensitive = replace(
        settings_mod.settings,
        llm_context_tokens=200,
        review_trigger_ratio=0.2,
        review_overhead_tokens=0,
        tokens_per_changed_line=20,
        tokens_per_changed_file=0,
    )
    monkeypatch.setattr(alignment_mod, "settings", sensitive)

    # Reduce cooldown to minimum (storage enforces >= 1 minute).
    monkeypatch.setattr(storage_mod, "settings", replace(settings_mod.settings, review_trigger_cooldown_minutes=1))

    # Append an event; should emit a review_trigger.
    append_event(Event(source="test", ts=datetime.now(UTC), payload_metadata={"kind": "smoke"}))

    from reos.db import get_db

    db = get_db()
    rows = db.iter_events_recent(limit=50)

    assert _count_kind(rows, "review_trigger") == 1
    assert _count_kind(rows, "alignment_trigger") == 0

    # Append another event immediately; should be throttled by cooldown.
    append_event(Event(source="test", ts=datetime.now(UTC), payload_metadata={"kind": "smoke2"}))
    rows2 = db.iter_events_recent(limit=50)
    assert _count_kind(rows2, "review_trigger") == 1


def test_poll_git_repo_writes_git_poll_event(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Create an unstaged change so diffstat isn't empty.
    p = repo / "src" / "reos" / "example.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# poll\n", encoding="utf-8")

    import reos.git_poll as git_poll_mod

    monkeypatch.setattr(git_poll_mod, "get_default_repo_path", lambda: repo)

    res = git_poll_mod.poll_git_repo()
    assert res["status"] == "ok"

    from reos.db import get_db

    rows = get_db().iter_events_recent(limit=20)
    assert any(r.get("kind") == "git_poll" for r in rows)
