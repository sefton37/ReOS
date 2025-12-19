from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from reos.db import Database
from reos.models import Event


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


def test_db_migrate(temp_db: Database) -> None:
    """Verify database tables are created."""
    conn = temp_db.connect()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [row[0] for row in tables]
    assert "events" in names
    assert "sessions" in names
    assert "classifications" in names
    assert "audit_log" in names
    assert "repos" in names
    assert "projects" in names
    assert "project_charter" in names
    assert "app_state" in names
    assert "agent_personas" in names


def test_db_repos_and_projects(temp_db: Database) -> None:
    temp_db.upsert_repo(repo_id="repo-1", path="/tmp/example")
    repos = temp_db.iter_repos()
    assert len(repos) == 1
    assert repos[0]["path"] == "/tmp/example"

    # Upsert again should not create a duplicate row.
    temp_db.upsert_repo(repo_id="repo-2", path="/tmp/example")
    repos2 = temp_db.iter_repos()
    assert len(repos2) == 1

    repo_id = str(repos2[0]["id"])
    base_now = "2025-12-19T00:00:00+00:00"

    temp_db.insert_project_charter(
        record={
            "project_id": "proj-1",
            "repo_id": repo_id,
            "project_name": "Example",
            "project_owner": "kellogg",
            "created_at": base_now,
            "last_reaffirmed_at": base_now,
            "core_intent": "Why it exists.",
            "problem_statement": "What problem it addresses.",
            "non_goals": "What it is not trying to do.",
            "definition_of_done": "When it is done.",
            "success_signals": "Signals it is going well.",
            "failure_conditions": "When to stop.",
            "sunset_criteria": "How to pause/abandon.",
            "time_horizon": "6 months",
            "energy_profile": "deep focus",
            "allowed_scope": "Allowed work boundaries.",
            "forbidden_scope": "Forbidden boundaries.",
            "primary_values": "privacy over convenience",
            "acceptable_tradeoffs": "polish",
            "unacceptable_tradeoffs": "surveillance",
            "attention_budget": "default focus",
            "distraction_tolerance": "low",
            "intervention_style": "gentle nudge",
            "origin_story": "Why now.",
            "current_state_summary": "Where things stand.",
            "updated_at": base_now,
            "ingested_at": base_now,
        }
    )

    charters = temp_db.iter_project_charters()
    assert len(charters) == 1
    assert charters[0]["project_name"] == "Example"
    assert charters[0]["repo_id"] == repo_id

    temp_db.update_project_charter(
        project_id="proj-1",
        updates={"project_name": "Example 2", "core_intent": "Updated intent."},
    )
    charter2 = temp_db.get_project_charter(project_id="proj-1")
    assert charter2 is not None
    assert charter2["project_name"] == "Example 2"
    assert charter2["core_intent"] == "Updated intent."

    # Reaffirmation is explicit (separate call).
    last_reaffirmed_before = str(charter2["last_reaffirmed_at"])
    temp_db.reaffirm_project_charter(project_id="proj-1")
    charter3 = temp_db.get_project_charter(project_id="proj-1")
    assert charter3 is not None
    assert str(charter3["last_reaffirmed_at"]) != last_reaffirmed_before


def test_db_agent_personas(temp_db: Database) -> None:
    temp_db.set_active_persona_id(persona_id=None)
    assert temp_db.get_active_persona_id() is None

    temp_db.upsert_agent_persona(
        persona_id="p1",
        name="Default",
        system_prompt="System prompt",
        default_context="Default context",
        temperature=0.2,
        top_p=0.9,
        tool_call_limit=3,
    )

    rows = temp_db.iter_agent_personas()
    assert len(rows) == 1
    assert rows[0]["name"] == "Default"

    temp_db.set_active_persona_id(persona_id="p1")
    assert temp_db.get_active_persona_id() == "p1"

    p = temp_db.get_agent_persona(persona_id="p1")
    assert p is not None
    assert p["tool_call_limit"] == 3

    # Update
    temp_db.upsert_agent_persona(
        persona_id="p1",
        name="Default",
        system_prompt="System prompt 2",
        default_context="Default context 2",
        temperature=0.3,
        top_p=0.8,
        tool_call_limit=2,
    )
    p2 = temp_db.get_agent_persona(persona_id="p1")
    assert p2 is not None
    assert p2["system_prompt"] == "System prompt 2"
    assert p2["tool_call_limit"] == 2


def test_db_insert_event(temp_db: Database) -> None:
    """Verify event insertion."""
    temp_db.insert_event(
        event_id="test-1",
        source="git",
        kind="active_editor",
        ts="2025-12-17T10:00:00Z",
        payload_metadata='{"uri": "file://test.py"}',
        note=None,
    )
    rows = temp_db.iter_events_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["source"] == "git"
    assert rows[0]["kind"] == "active_editor"


def test_storage_append_and_iter() -> None:
    """Integration test: append events and iterate."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create a fresh database for this test
        from reos.db import Database

        db = Database(db_path=data_dir / "test.db")
        db.migrate()

        # Directly test append/iter without module reloading
        evt = Event(source="test", payload_metadata={"kind": "test"})
        import uuid

        event_id = str(uuid.uuid4())
        db.insert_event(
            event_id=event_id,
            source=evt.source,
            kind=evt.payload_metadata.get("kind") if evt.payload_metadata else None,
            ts=evt.ts.isoformat(),
            payload_metadata=(
                json.dumps(evt.payload_metadata) if evt.payload_metadata else None
            ),
            note=evt.note,
        )

        retrieved = db.iter_events_recent(limit=10)
        assert len(retrieved) > 0
        assert retrieved[0]["source"] == "test"

        db.close()
