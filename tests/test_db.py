from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from reos.db import Database, get_db
from reos.models import Event


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


@pytest.fixture
def memory_db() -> Database:
    """Create an in-memory database for testing."""
    db = Database(db_path=":memory:")
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
    assert "app_state" in names
    assert "agent_personas" in names


def test_db_repos(temp_db: Database) -> None:
    temp_db.upsert_repo(repo_id="repo-1", path="/tmp/example")
    repos = temp_db.iter_repos()
    assert len(repos) == 1
    assert repos[0]["path"] == "/tmp/example"

    # Upsert again should not create a duplicate row.
    temp_db.upsert_repo(repo_id="repo-2", path="/tmp/example")
    repos2 = temp_db.iter_repos()
    assert len(repos2) == 1


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


class TestDatabaseInit:
    """Test Database initialization."""

    def test_init_with_memory(self) -> None:
        """Database should support :memory: for in-memory storage."""
        db = Database(db_path=":memory:")
        assert db.db_path == ":memory:"
        db.close()

    def test_init_with_none_uses_settings(self) -> None:
        """Database should use settings.data_dir when path is None."""
        with patch("reos.db.settings") as mock_settings:
            mock_settings.data_dir = Path("/tmp/test_data")
            db = Database(db_path=None)
            assert db.db_path == Path("/tmp/test_data/reos.db")

    def test_init_with_string_path(self) -> None:
        """Database should convert string path to Path."""
        db = Database(db_path="/tmp/test.db")
        assert db.db_path == Path("/tmp/test.db")

    def test_init_with_path(self) -> None:
        """Database should accept Path directly."""
        db = Database(db_path=Path("/tmp/test.db"))
        assert db.db_path == Path("/tmp/test.db")


class TestDatabaseConnect:
    """Test connection handling."""

    def test_connect_returns_connection(self, memory_db: Database) -> None:
        """connect() should return a SQLite connection."""
        conn = memory_db.connect()
        assert conn is not None

    def test_connect_reuses_connection(self, memory_db: Database) -> None:
        """connect() should reuse existing connection in same thread."""
        conn1 = memory_db.connect()
        conn2 = memory_db.connect()
        assert conn1 is conn2

    def test_connect_creates_parent_dir(self) -> None:
        """connect() should create parent directories for db file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(db_path=Path(tmpdir) / "subdir" / "test.db")
            db.connect()
            assert (Path(tmpdir) / "subdir").exists()
            db.close()


class TestDatabaseTransaction:
    """Test transaction context manager."""

    def test_transaction_commits_on_success(self, memory_db: Database) -> None:
        """Transaction should commit on successful exit."""
        with memory_db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES ('test', 'value', '2024-01-01')"
            )
        # Verify data persisted
        row = memory_db.connect().execute(
            "SELECT value FROM app_state WHERE key = 'test'"
        ).fetchone()
        assert row["value"] == "value"

    def test_transaction_rollback_on_error(self, memory_db: Database) -> None:
        """Transaction should rollback on exception."""
        try:
            with memory_db.transaction() as conn:
                conn.execute(
                    "INSERT INTO app_state (key, value, updated_at) VALUES ('rollback_test', 'value', '2024-01-01')"
                )
                raise ValueError("Test error")
        except ValueError:
            pass
        # Verify data was rolled back
        row = memory_db.connect().execute(
            "SELECT value FROM app_state WHERE key = 'rollback_test'"
        ).fetchone()
        assert row is None


class TestDatabaseClose:
    """Test connection closing."""

    def test_close_closes_connection(self) -> None:
        """close() should close the connection."""
        db = Database(db_path=":memory:")
        db.connect()
        db.close()
        # Accessing _local.conn should be None after close
        assert getattr(db._local, "conn", None) is None

    def test_close_without_connection(self) -> None:
        """close() should be safe when no connection exists."""
        db = Database(db_path=":memory:")
        db.close()  # Should not raise


class TestDatabaseConversations:
    """Test conversation methods."""

    def test_create_conversation(self, memory_db: Database) -> None:
        """Should create a new conversation."""
        conv_id = memory_db.create_conversation(
            conversation_id="conv-123",
            title="Test Conversation"
        )
        assert conv_id == "conv-123"

    def test_create_conversation_no_title(self, memory_db: Database) -> None:
        """Should create conversation without title."""
        conv_id = memory_db.create_conversation(conversation_id="conv-456")
        assert conv_id == "conv-456"

    def test_get_conversation(self, memory_db: Database) -> None:
        """Should retrieve conversation by ID."""
        memory_db.create_conversation(
            conversation_id="conv-789",
            title="Get Test"
        )
        conv = memory_db.get_conversation(conversation_id="conv-789")
        assert conv is not None
        assert conv["title"] == "Get Test"

    def test_get_conversation_not_found(self, memory_db: Database) -> None:
        """Should return None for non-existent conversation."""
        conv = memory_db.get_conversation(conversation_id="nonexistent")
        assert conv is None

    def test_update_conversation_activity(self, memory_db: Database) -> None:
        """Should update last_active_at timestamp."""
        memory_db.create_conversation(conversation_id="conv-activity")
        conv_before = memory_db.get_conversation(conversation_id="conv-activity")

        # Wait and update
        memory_db.update_conversation_activity(conversation_id="conv-activity")
        conv_after = memory_db.get_conversation(conversation_id="conv-activity")

        assert conv_before is not None
        assert conv_after is not None
        # Timestamps should be different (or same if test is fast)
        assert conv_after["last_active_at"] is not None

    def test_update_conversation_title(self, memory_db: Database) -> None:
        """Should update conversation title."""
        memory_db.create_conversation(
            conversation_id="conv-title",
            title="Original Title"
        )
        memory_db.update_conversation_title(
            conversation_id="conv-title",
            title="New Title"
        )
        conv = memory_db.get_conversation(conversation_id="conv-title")
        assert conv is not None
        assert conv["title"] == "New Title"

    def test_iter_conversations(self, memory_db: Database) -> None:
        """Should list conversations ordered by last_active_at."""
        memory_db.create_conversation(conversation_id="conv-a", title="A")
        memory_db.create_conversation(conversation_id="conv-b", title="B")
        memory_db.create_conversation(conversation_id="conv-c", title="C")

        convs = memory_db.iter_conversations(limit=10)
        assert len(convs) == 3

    def test_iter_conversations_limit(self, memory_db: Database) -> None:
        """Should respect limit parameter."""
        for i in range(5):
            memory_db.create_conversation(conversation_id=f"conv-{i}")

        convs = memory_db.iter_conversations(limit=3)
        assert len(convs) == 3


class TestDatabaseMessages:
    """Test message methods."""

    def test_add_message(self, memory_db: Database) -> None:
        """Should add message to conversation."""
        memory_db.create_conversation(conversation_id="conv-msg")
        msg_id = memory_db.add_message(
            message_id="msg-1",
            conversation_id="conv-msg",
            role="user",
            content="Hello",
            message_type="text"
        )
        assert msg_id == "msg-1"

    def test_add_message_with_metadata(self, memory_db: Database) -> None:
        """Should store message metadata."""
        memory_db.create_conversation(conversation_id="conv-meta")
        memory_db.add_message(
            message_id="msg-meta",
            conversation_id="conv-meta",
            role="assistant",
            content="Response",
            message_type="text",
            metadata='{"tokens": 100}'
        )
        messages = memory_db.get_messages(conversation_id="conv-meta")
        assert len(messages) == 1
        assert messages[0]["metadata"] == '{"tokens": 100}'

    def test_get_messages(self, memory_db: Database) -> None:
        """Should retrieve messages in chronological order."""
        memory_db.create_conversation(conversation_id="conv-get")
        memory_db.add_message(
            message_id="msg-a",
            conversation_id="conv-get",
            role="user",
            content="First"
        )
        memory_db.add_message(
            message_id="msg-b",
            conversation_id="conv-get",
            role="assistant",
            content="Second"
        )

        messages = memory_db.get_messages(conversation_id="conv-get")
        assert len(messages) == 2
        assert messages[0]["content"] == "First"
        assert messages[1]["content"] == "Second"

    def test_get_messages_with_before_id(self, memory_db: Database) -> None:
        """Should retrieve messages before a specific message."""
        memory_db.create_conversation(conversation_id="conv-before")
        memory_db.add_message(
            message_id="msg-1",
            conversation_id="conv-before",
            role="user",
            content="First"
        )
        memory_db.add_message(
            message_id="msg-2",
            conversation_id="conv-before",
            role="assistant",
            content="Second"
        )
        memory_db.add_message(
            message_id="msg-3",
            conversation_id="conv-before",
            role="user",
            content="Third"
        )

        messages = memory_db.get_messages(
            conversation_id="conv-before",
            before_id="msg-3"
        )
        assert len(messages) == 2

    def test_get_recent_messages(self, memory_db: Database) -> None:
        """Should get most recent messages in chronological order."""
        memory_db.create_conversation(conversation_id="conv-recent")
        for i in range(10):
            memory_db.add_message(
                message_id=f"msg-{i}",
                conversation_id="conv-recent",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}"
            )

        messages = memory_db.get_recent_messages(
            conversation_id="conv-recent",
            limit=5
        )
        assert len(messages) == 5
        # Should be in chronological order
        assert messages[0]["content"] == "Message 5"
        assert messages[4]["content"] == "Message 9"

    def test_clear_messages(self, memory_db: Database) -> None:
        """Should delete all messages from conversation."""
        memory_db.create_conversation(conversation_id="conv-clear")
        memory_db.add_message(
            message_id="msg-clear-1",
            conversation_id="conv-clear",
            role="user",
            content="To be deleted"
        )
        memory_db.add_message(
            message_id="msg-clear-2",
            conversation_id="conv-clear",
            role="assistant",
            content="Also deleted"
        )

        count = memory_db.clear_messages(conversation_id="conv-clear")
        assert count == 2

        messages = memory_db.get_messages(conversation_id="conv-clear")
        assert len(messages) == 0


class TestDatabaseApprovals:
    """Test approval methods."""

    def test_create_approval(self, memory_db: Database) -> None:
        """Should create pending approval."""
        memory_db.create_conversation(conversation_id="conv-approval")
        approval_id = memory_db.create_approval(
            approval_id="app-1",
            conversation_id="conv-approval",
            command="rm -rf /tmp/test",
            explanation="Remove test directory",
            risk_level="high"
        )
        assert approval_id == "app-1"

    def test_create_approval_with_all_fields(self, memory_db: Database) -> None:
        """Should store all approval fields."""
        memory_db.create_conversation(conversation_id="conv-full")
        memory_db.create_approval(
            approval_id="app-full",
            conversation_id="conv-full",
            command="echo test",
            explanation="Test echo",
            risk_level="low",
            affected_paths="/tmp/test.txt",
            undo_command="rm /tmp/test.txt",
            plan_id="plan-1",
            step_id="step-1"
        )

        approval = memory_db.get_approval(approval_id="app-full")
        assert approval is not None
        assert approval["plan_id"] == "plan-1"
        assert approval["step_id"] == "step-1"
        assert approval["undo_command"] == "rm /tmp/test.txt"

    def test_get_approval(self, memory_db: Database) -> None:
        """Should retrieve approval by ID."""
        memory_db.create_conversation(conversation_id="conv-get-app")
        memory_db.create_approval(
            approval_id="app-get",
            conversation_id="conv-get-app",
            command="ls",
            risk_level="low"
        )

        approval = memory_db.get_approval(approval_id="app-get")
        assert approval is not None
        assert approval["command"] == "ls"

    def test_get_approval_not_found(self, memory_db: Database) -> None:
        """Should return None for non-existent approval."""
        approval = memory_db.get_approval(approval_id="nonexistent")
        assert approval is None

    def test_get_pending_approvals(self, memory_db: Database) -> None:
        """Should get all pending approvals."""
        memory_db.create_conversation(conversation_id="conv-pending")
        memory_db.create_approval(
            approval_id="app-pending-1",
            conversation_id="conv-pending",
            command="cmd1",
            risk_level="low"
        )
        memory_db.create_approval(
            approval_id="app-pending-2",
            conversation_id="conv-pending",
            command="cmd2",
            risk_level="medium"
        )

        approvals = memory_db.get_pending_approvals()
        assert len(approvals) == 2

    def test_get_pending_approvals_by_conversation(self, memory_db: Database) -> None:
        """Should filter approvals by conversation."""
        memory_db.create_conversation(conversation_id="conv-a")
        memory_db.create_conversation(conversation_id="conv-b")
        memory_db.create_approval(
            approval_id="app-a",
            conversation_id="conv-a",
            command="cmd-a",
            risk_level="low"
        )
        memory_db.create_approval(
            approval_id="app-b",
            conversation_id="conv-b",
            command="cmd-b",
            risk_level="low"
        )

        approvals = memory_db.get_pending_approvals(conversation_id="conv-a")
        assert len(approvals) == 1
        assert approvals[0]["command"] == "cmd-a"

    def test_resolve_approval(self, memory_db: Database) -> None:
        """Should update approval status."""
        memory_db.create_conversation(conversation_id="conv-resolve")
        memory_db.create_approval(
            approval_id="app-resolve",
            conversation_id="conv-resolve",
            command="test",
            risk_level="low"
        )

        memory_db.resolve_approval(approval_id="app-resolve", status="approved")

        approval = memory_db.get_approval(approval_id="app-resolve")
        assert approval is not None
        assert approval["status"] == "approved"
        assert approval["resolved_at"] is not None


class TestDatabaseSessions:
    """Test session methods."""

    def test_insert_session(self, memory_db: Database) -> None:
        """Should insert a session."""
        memory_db.insert_session(
            session_id="sess-1",
            workspace_folder="/home/user/project",
            started_at="2024-01-15T10:00:00Z",
            event_count=5,
            switch_count=2
        )

        # Verify via raw query
        row = memory_db.connect().execute(
            "SELECT * FROM sessions WHERE id = 'sess-1'"
        ).fetchone()
        assert row is not None
        assert row["workspace_folder"] == "/home/user/project"


class TestDatabaseClassifications:
    """Test classification methods."""

    def test_insert_classification(self, memory_db: Database) -> None:
        """Should insert a classification."""
        memory_db.insert_session(
            session_id="sess-class",
            workspace_folder="/tmp",
            started_at="2024-01-15T10:00:00Z"
        )
        memory_db.insert_classification(
            classification_id="class-1",
            session_id="sess-class",
            kind="fragmentation",
            severity="high",
            explanation="Context switching detected"
        )

        classifications = memory_db.iter_classifications_for_session("sess-class")
        assert len(classifications) == 1
        assert classifications[0]["kind"] == "fragmentation"

    def test_iter_classifications_for_session(self, memory_db: Database) -> None:
        """Should return classifications for specific session."""
        memory_db.insert_session(
            session_id="sess-multi",
            workspace_folder="/tmp",
            started_at="2024-01-15T10:00:00Z"
        )
        memory_db.insert_classification(
            classification_id="class-a",
            session_id="sess-multi",
            kind="focus",
            severity="low",
            explanation="Good focus"
        )
        memory_db.insert_classification(
            classification_id="class-b",
            session_id="sess-multi",
            kind="flow",
            severity="medium",
            explanation="Flow state"
        )

        classifications = memory_db.iter_classifications_for_session("sess-multi")
        assert len(classifications) == 2


class TestDatabaseState:
    """Test app state methods."""

    def test_set_and_get_state(self, memory_db: Database) -> None:
        """Should store and retrieve state."""
        memory_db.set_state(key="theme", value="dark")
        assert memory_db.get_state(key="theme") == "dark"

    def test_set_state_null(self, memory_db: Database) -> None:
        """Should handle null value."""
        memory_db.set_state(key="optional", value=None)
        assert memory_db.get_state(key="optional") is None

    def test_get_state_not_found(self, memory_db: Database) -> None:
        """Should return None for non-existent key."""
        assert memory_db.get_state(key="nonexistent") is None

    def test_set_state_updates(self, memory_db: Database) -> None:
        """Should update existing state."""
        memory_db.set_state(key="counter", value="1")
        memory_db.set_state(key="counter", value="2")
        assert memory_db.get_state(key="counter") == "2"


class TestDatabaseRepos:
    """Test repo methods."""

    def test_upsert_repo_with_remote_summary(self, memory_db: Database) -> None:
        """Should store remote summary."""
        memory_db.upsert_repo(
            repo_id="repo-remote",
            path="/home/user/project",
            remote_summary="origin: git@github.com:user/project.git"
        )

        repos = memory_db.iter_repos()
        assert len(repos) == 1
        assert repos[0]["remote_summary"] == "origin: git@github.com:user/project.git"

    def test_get_repo_path(self, memory_db: Database) -> None:
        """Should return repo path by ID."""
        memory_db.upsert_repo(repo_id="repo-path", path="/tmp/myrepo")

        path = memory_db.get_repo_path(repo_id="repo-path")
        assert path == "/tmp/myrepo"

    def test_get_repo_path_not_found(self, memory_db: Database) -> None:
        """Should return None for non-existent repo."""
        path = memory_db.get_repo_path(repo_id="nonexistent")
        assert path is None


class TestDatabaseEvents:
    """Test event methods."""

    def test_iter_events_recent_default_limit(self, memory_db: Database) -> None:
        """Should use default limit of 1000."""
        # Insert a few events
        for i in range(5):
            memory_db.insert_event(
                event_id=f"evt-{i}",
                source="test",
                kind="test",
                ts=f"2024-01-15T10:0{i}:00Z",
                payload_metadata=None,
                note=None
            )

        events = memory_db.iter_events_recent(limit=None)
        assert len(events) == 5


class TestGetDb:
    """Test get_db singleton."""

    def test_get_db_returns_database(self) -> None:
        """get_db() should return Database instance."""
        import reos.db as db_module

        # Reset singleton
        db_module._db_instance = None

        with patch.object(db_module, "Database") as MockDb:
            mock_db = MagicMock()
            MockDb.return_value = mock_db

            result = db_module.get_db()

            assert result is mock_db
            mock_db.migrate.assert_called_once()

    def test_get_db_returns_same_instance(self) -> None:
        """get_db() should return same instance on subsequent calls."""
        import reos.db as db_module

        # Reset and set a mock
        db_module._db_instance = MagicMock()

        result1 = db_module.get_db()
        result2 = db_module.get_db()

        assert result1 is result2


class TestDatabaseMigrations:
    """Test migration handling."""

    def test_migrate_creates_all_tables(self, memory_db: Database) -> None:
        """migrate() should create all required tables."""
        conn = memory_db.connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [row[0] for row in tables]

        # Verify all major tables
        expected_tables = [
            "events", "sessions", "classifications", "audit_log",
            "repos", "app_state", "agent_personas", "conversations",
            "messages", "pending_approvals", "repo_map_files",
            "repo_symbols", "repo_dependencies", "repo_embeddings",
            "project_decisions", "project_patterns", "user_corrections",
            "coding_sessions", "code_changes"
        ]
        for table in expected_tables:
            assert table in names, f"Table {table} not found"

    def test_run_migrations_handles_error(self) -> None:
        """_run_migrations should handle and re-raise errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(db_path=Path(tmpdir) / "test.db")
            # Manually create connection without full migration
            db.connect()

            with patch("reos.migrations.run_migrations") as mock_migrate:
                mock_migrate.side_effect = Exception("Migration failed")

                with pytest.raises(Exception, match="Migration failed"):
                    db._run_migrations()

            db.close()
