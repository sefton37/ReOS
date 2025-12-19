from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reos.models import Event
from reos.storage import append_event


def _count_kind(rows: list[dict[str, object]], kind: str) -> int:
    return sum(1 for r in rows if r.get("kind") == kind)


def test_review_trigger_cooldown_boundary_is_deterministic(
    temp_git_repo: Path,
    isolated_db_singleton: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = temp_git_repo

    # Make a big change so context budget trips easily.
    p = repo / "src" / "reos" / "example.py"
    p.write_text(p.read_text(encoding="utf-8") + ("\n".join(["x = 1"] * 200) + "\n"), encoding="utf-8")

    import reos.storage as storage_mod
    import reos.alignment as alignment_mod
    import reos.settings as settings_mod

    monkeypatch.setattr(storage_mod, "get_default_repo_path", lambda: repo)

    # Make budget highly sensitive and cooldown = 1 minute.
    sensitive = replace(
        settings_mod.settings,
        llm_context_tokens=200,
        review_trigger_ratio=0.2,
        review_overhead_tokens=0,
        tokens_per_changed_line=20,
        tokens_per_changed_file=0,
        review_trigger_cooldown_minutes=1,
    )
    monkeypatch.setattr(alignment_mod, "settings", sensitive)
    monkeypatch.setattr(storage_mod, "settings", sensitive)

    t0 = datetime(2025, 12, 19, 0, 0, 0, tzinfo=UTC)

    # First append at t0 => should trigger once.
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t0)
    append_event(Event(source="test", ts=t0, payload_metadata={"kind": "evt"}))

    from reos.db import get_db

    db = get_db()
    rows1 = db.iter_events_recent(limit=50)
    assert _count_kind(rows1, "review_trigger") == 1

    # Still within cooldown (t0 + 59s) => no new trigger.
    t1 = t0 + timedelta(seconds=59)
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t1)
    append_event(Event(source="test", ts=t1, payload_metadata={"kind": "evt2"}))

    rows2 = db.iter_events_recent(limit=50)
    assert _count_kind(rows2, "review_trigger") == 1

    # Past cooldown (t0 + 61s) => second trigger.
    t2 = t0 + timedelta(seconds=61)
    monkeypatch.setattr(storage_mod, "_utcnow", lambda: t2)
    append_event(Event(source="test", ts=t2, payload_metadata={"kind": "evt3"}))

    rows3 = db.iter_events_recent(limit=50)
    assert _count_kind(rows3, "review_trigger") == 2
