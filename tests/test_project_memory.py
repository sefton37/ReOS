"""Tests for Project Memory - Long-term learning for Code Mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from reos.code_mode.project_memory import (
    CodeChange,
    CodingSession,
    ProjectDecision,
    ProjectMemoryContext,
    ProjectMemoryStore,
    ProjectPattern,
    UserCorrection,
)
from reos.db import Database


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_memory.db"
    db = Database(str(db_path))
    db.migrate()  # Create all tables including project memory tables
    return db


@pytest.fixture
def memory_store(temp_db: Database) -> ProjectMemoryStore:
    """Create a ProjectMemoryStore with temp database."""
    return ProjectMemoryStore(temp_db)


@pytest.fixture
def sample_repo_path() -> str:
    """Sample repository path for tests."""
    return "/home/user/projects/myapp"


# =============================================================================
# ProjectDecision Tests
# =============================================================================


class TestProjectDecision:
    """Tests for ProjectDecision dataclass."""

    def test_create_decision(self) -> None:
        """Should create a project decision."""
        decision = ProjectDecision(
            id="decision-abc123",
            repo_path="/path/to/repo",
            decision="Use dataclasses, not TypedDict",
            rationale="Better IDE support and runtime checks",
            scope="global",
            keywords=["dataclass", "typeddict", "data"],
            source="user_explicit",
            confidence=1.0,
            created_at=datetime.now(timezone.utc),
        )

        assert decision.id == "decision-abc123"
        assert decision.decision == "Use dataclasses, not TypedDict"
        assert "dataclass" in decision.keywords
        assert decision.superseded_by is None

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        now = datetime.now(timezone.utc)
        decision = ProjectDecision(
            id="decision-123",
            repo_path="/repo",
            decision="Test decision",
            rationale="Test rationale",
            scope="global",
            keywords=["test"],
            source="inferred",
            confidence=0.8,
            created_at=now,
        )

        d = decision.to_dict()

        assert d["id"] == "decision-123"
        assert d["decision"] == "Test decision"
        assert d["keywords"] == ["test"]
        assert d["created_at"] == now.isoformat()

    def test_from_dict(self) -> None:
        """Should deserialize from dictionary."""
        data = {
            "id": "decision-456",
            "repo_path": "/repo",
            "decision": "Another decision",
            "rationale": "Reasons",
            "scope": "module:foo",
            "keywords": '["foo", "bar"]',  # JSON string
            "source": "correction",
            "confidence": 0.9,
            "created_at": "2024-01-15T10:30:00+00:00",
        }

        decision = ProjectDecision.from_dict(data)

        assert decision.id == "decision-456"
        assert decision.scope == "module:foo"
        assert decision.keywords == ["foo", "bar"]


# =============================================================================
# ProjectPattern Tests
# =============================================================================


class TestProjectPattern:
    """Tests for ProjectPattern dataclass."""

    def test_create_pattern(self) -> None:
        """Should create a project pattern."""
        now = datetime.now(timezone.utc)
        pattern = ProjectPattern(
            id="pattern-abc",
            repo_path="/repo",
            pattern_type="testing",
            description="Tests go in tests/, named test_*.py",
            applies_to="tests/*.py",
            example_code="def test_foo(): pass",
            source="detected",
            occurrence_count=10,
            created_at=now,
            last_seen_at=now,
        )

        assert pattern.pattern_type == "testing"
        assert pattern.applies_to == "tests/*.py"
        assert pattern.occurrence_count == 10

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """Should roundtrip through serialization."""
        now = datetime.now(timezone.utc)
        original = ProjectPattern(
            id="pattern-xyz",
            repo_path="/repo",
            pattern_type="naming",
            description="Use snake_case",
            applies_to="*.py",
            example_code=None,
            source="user_explicit",
            occurrence_count=5,
            created_at=now,
            last_seen_at=now,
        )

        d = original.to_dict()
        restored = ProjectPattern.from_dict(d)

        assert restored.id == original.id
        assert restored.pattern_type == original.pattern_type
        assert restored.occurrence_count == original.occurrence_count


# =============================================================================
# UserCorrection Tests
# =============================================================================


class TestUserCorrection:
    """Tests for UserCorrection dataclass."""

    def test_create_correction(self) -> None:
        """Should create a user correction."""
        correction = UserCorrection(
            id="correction-123",
            repo_path="/repo",
            session_id="session-abc",
            original_code="class Foo(TypedDict):",
            corrected_code="@dataclass\nclass Foo:",
            file_path="src/models.py",
            correction_type="style",
            inferred_rule="Use dataclasses instead of TypedDict",
            created_at=datetime.now(timezone.utc),
        )

        assert correction.correction_type == "style"
        assert "dataclass" in correction.inferred_rule
        assert correction.promoted_to_decision is None


# =============================================================================
# CodingSession Tests
# =============================================================================


class TestCodingSession:
    """Tests for CodingSession dataclass."""

    def test_create_session(self) -> None:
        """Should create a coding session."""
        now = datetime.now(timezone.utc)
        session = CodingSession(
            id="session-abc",
            repo_path="/repo",
            started_at=now,
            ended_at=now + timedelta(minutes=30),
            prompt_summary="Add fibonacci function",
            outcome="completed",
            files_changed=["src/math.py"],
            intent_summary="Create fibonacci function in math module",
            lessons_learned=["Use memoization for performance"],
            contract_fulfilled=True,
            iteration_count=3,
        )

        assert session.contract_fulfilled is True
        assert session.iteration_count == 3
        assert len(session.files_changed) == 1


# =============================================================================
# ProjectMemoryContext Tests
# =============================================================================


class TestProjectMemoryContext:
    """Tests for ProjectMemoryContext aggregation."""

    def test_empty_context(self) -> None:
        """Should detect empty context."""
        ctx = ProjectMemoryContext()
        assert ctx.is_empty() is True

    def test_non_empty_context(self) -> None:
        """Should detect non-empty context."""
        decision = ProjectDecision(
            id="d1",
            repo_path="/repo",
            decision="Test",
            rationale="",
            scope="global",
            keywords=[],
            source="inferred",
            confidence=1.0,
            created_at=datetime.now(timezone.utc),
        )
        ctx = ProjectMemoryContext(relevant_decisions=[decision])
        assert ctx.is_empty() is False

    def test_to_markdown(self) -> None:
        """Should render to markdown."""
        now = datetime.now(timezone.utc)
        decision = ProjectDecision(
            id="d1",
            repo_path="/repo",
            decision="Use dataclasses",
            rationale="Better IDE support",
            scope="global",
            keywords=[],
            source="user_explicit",
            confidence=1.0,
            created_at=now,
        )
        pattern = ProjectPattern(
            id="p1",
            repo_path="/repo",
            pattern_type="testing",
            description="Tests in tests/",
            applies_to="tests/*",
            example_code=None,
            source="detected",
            occurrence_count=1,
            created_at=now,
            last_seen_at=now,
        )
        ctx = ProjectMemoryContext(
            relevant_decisions=[decision],
            applicable_patterns=[pattern],
        )

        md = ctx.to_markdown()

        assert "## Project Decisions" in md
        assert "Use dataclasses" in md
        assert "## Code Patterns" in md
        assert "Tests in tests/" in md


# =============================================================================
# ProjectMemoryStore Tests
# =============================================================================


class TestProjectMemoryStoreDecisions:
    """Tests for decision operations."""

    def test_add_decision(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should add a decision."""
        decision = memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Use pytest fixtures",
            rationale="Cleaner test setup",
            scope="global",
            keywords=["pytest", "fixtures", "testing"],
            source="user_explicit",
        )

        assert decision.id.startswith("decision-")
        assert decision.decision == "Use pytest fixtures"
        assert decision.confidence == 1.0

    def test_add_decision_auto_keywords(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should auto-extract keywords if not provided."""
        decision = memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Always use type hints for function parameters",
        )

        # Should have extracted some keywords
        assert len(decision.keywords) > 0
        assert "type" in decision.keywords or "hints" in decision.keywords

    def test_get_decision(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should retrieve a decision by ID."""
        added = memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Test decision",
        )

        retrieved = memory_store.get_decision(added.id)

        assert retrieved is not None
        assert retrieved.decision == "Test decision"

    def test_list_decisions(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should list all decisions for a repo."""
        memory_store.add_decision(repo_path=sample_repo_path, decision="Decision 1")
        memory_store.add_decision(repo_path=sample_repo_path, decision="Decision 2")
        memory_store.add_decision(repo_path="/other/repo", decision="Other decision")

        decisions = memory_store.list_decisions(sample_repo_path)

        assert len(decisions) == 2

    def test_supersede_decision(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should mark decision as superseded."""
        old = memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Old approach",
        )
        new = memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="New approach",
        )

        memory_store.supersede_decision(old.id, new.id)

        # Old should be superseded
        old_retrieved = memory_store.get_decision(old.id)
        assert old_retrieved is not None
        assert old_retrieved.superseded_by == new.id

        # List should exclude superseded by default
        active = memory_store.list_decisions(sample_repo_path)
        assert len(active) == 1
        assert active[0].id == new.id


class TestProjectMemoryStorePatterns:
    """Tests for pattern operations."""

    def test_add_pattern(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should add a pattern."""
        pattern = memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="testing",
            description="Use pytest fixtures for test setup",
            applies_to="tests/*.py",
        )

        assert pattern.id.startswith("pattern-")
        assert pattern.occurrence_count == 1

    def test_increment_pattern_count(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should increment pattern occurrence count."""
        pattern = memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="style",
            description="Use snake_case",
        )

        memory_store.increment_pattern_count(pattern.id)
        memory_store.increment_pattern_count(pattern.id)

        retrieved = memory_store.get_pattern(pattern.id)
        assert retrieved is not None
        assert retrieved.occurrence_count == 3

    def test_list_patterns(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should list patterns for a repo."""
        memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="naming",
            description="Pattern 1",
        )
        memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="structure",
            description="Pattern 2",
        )

        patterns = memory_store.list_patterns(sample_repo_path)

        assert len(patterns) == 2


class TestProjectMemoryStoreCorrections:
    """Tests for correction operations."""

    def test_record_correction(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should record a correction."""
        correction = memory_store.record_correction(
            repo_path=sample_repo_path,
            session_id="session-123",
            file_path="src/models.py",
            original_code="x = TypedDict('X', {})",
            corrected_code="@dataclass\nclass X: pass",
            correction_type="style",
            inferred_rule="Use dataclasses instead of TypedDict",
        )

        assert correction.id.startswith("correction-")
        assert correction.inferred_rule == "Use dataclasses instead of TypedDict"

    def test_promote_correction_to_decision(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should promote correction to decision."""
        correction = memory_store.record_correction(
            repo_path=sample_repo_path,
            session_id="session-456",
            file_path="src/utils.py",
            original_code="old code",
            corrected_code="new code",
            correction_type="naming",
            inferred_rule="Use consistent naming",
        )

        decision = memory_store.promote_correction_to_decision(correction.id)

        assert decision.decision == "Use consistent naming"
        assert decision.source == "correction"
        assert decision.confidence == 0.8


class TestProjectMemoryStoreSessions:
    """Tests for session operations."""

    def test_record_session(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should record a coding session."""
        now = datetime.now(timezone.utc)
        session = memory_store.record_session(
            session_id="session-abc",
            repo_path=sample_repo_path,
            prompt_summary="Add fibonacci function",
            started_at=now,
            ended_at=now + timedelta(minutes=15),
            outcome="completed",
            files_changed=["src/math.py"],
            contract_fulfilled=True,
            iteration_count=2,
        )

        assert session.id == "session-abc"
        assert session.contract_fulfilled is True

    def test_list_sessions(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should list recent sessions."""
        now = datetime.now(timezone.utc)

        for i in range(5):
            memory_store.record_session(
                session_id=f"session-{i}",
                repo_path=sample_repo_path,
                prompt_summary=f"Task {i}",
                started_at=now + timedelta(minutes=i * 10),
            )

        sessions = memory_store.list_sessions(sample_repo_path, limit=3)

        assert len(sessions) == 3


class TestProjectMemoryStoreChanges:
    """Tests for change recording."""

    def test_record_change(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should record a code change."""
        change = memory_store.record_change(
            repo_path=sample_repo_path,
            session_id="session-xyz",
            file_path="src/new_file.py",
            change_type="create",
            diff_summary="Created new file",
            new_content_hash="abc123",
        )

        assert change.id.startswith("change-")
        assert change.change_type == "create"

    def test_get_file_history(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should retrieve file change history."""
        memory_store.record_change(
            repo_path=sample_repo_path,
            session_id="session-1",
            file_path="src/models.py",
            change_type="create",
            diff_summary="Created",
            new_content_hash="hash1",
        )
        memory_store.record_change(
            repo_path=sample_repo_path,
            session_id="session-2",
            file_path="src/models.py",
            change_type="edit",
            diff_summary="Edited",
            new_content_hash="hash2",
            old_content_hash="hash1",
        )

        history = memory_store.get_file_history(sample_repo_path, "src/models.py")

        assert len(history) == 2
        # Most recent first
        assert history[0].change_type == "edit"


class TestProjectMemoryStoreRetrieval:
    """Tests for context retrieval."""

    def test_get_relevant_context_empty(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should return empty context for new repo."""
        ctx = memory_store.get_relevant_context(
            repo_path=sample_repo_path,
            prompt="Add a new feature",
        )

        assert ctx.is_empty()

    def test_get_relevant_context_with_decisions(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should return relevant decisions."""
        memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Use dataclasses for data models",
            keywords=["dataclass", "model", "data"],
        )
        memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Always write tests first",
            keywords=["test", "tdd"],
        )

        ctx = memory_store.get_relevant_context(
            repo_path=sample_repo_path,
            prompt="Create a new User model",
        )

        assert len(ctx.relevant_decisions) >= 1
        # Should find the dataclass decision (model keyword)

    def test_get_relevant_context_with_patterns(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Should return applicable patterns."""
        memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="testing",
            description="Tests in tests/test_*.py",
            applies_to="tests/*.py",
        )

        ctx = memory_store.get_relevant_context(
            repo_path=sample_repo_path,
            prompt="Add tests",
            file_paths=["tests/test_user.py"],
        )

        assert len(ctx.applicable_patterns) >= 1

    def test_keyword_extraction(self, memory_store: ProjectMemoryStore) -> None:
        """Should extract meaningful keywords."""
        keywords = memory_store._extract_keywords(
            "Create a function that calculates fibonacci numbers"
        )

        assert "create" in keywords or "function" in keywords
        assert "fibonacci" in keywords
        # Should filter stopwords
        assert "a" not in keywords
        assert "that" not in keywords


# =============================================================================
# Integration Tests
# =============================================================================


class TestProjectMemoryIntegration:
    """Integration tests for the full workflow."""

    def test_learning_workflow(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Test the full learning workflow."""
        now = datetime.now(timezone.utc)

        # 1. Start a session
        session = memory_store.record_session(
            session_id="session-learn",
            repo_path=sample_repo_path,
            prompt_summary="Add user authentication",
            started_at=now,
            outcome="completed",
            contract_fulfilled=True,
            iteration_count=3,
        )

        # 2. Record a change
        memory_store.record_change(
            repo_path=sample_repo_path,
            session_id=session.id,
            file_path="src/auth.py",
            change_type="create",
            diff_summary="Created auth module",
            new_content_hash="abc123",
        )

        # 3. User makes a correction
        correction = memory_store.record_correction(
            repo_path=sample_repo_path,
            session_id=session.id,
            file_path="src/auth.py",
            original_code="class User(TypedDict):",
            corrected_code="@dataclass\nclass User:",
            correction_type="style",
            inferred_rule="Use dataclasses for data models",
        )

        # 4. Promote correction to decision
        decision = memory_store.promote_correction_to_decision(correction.id)

        # 5. Verify the decision was created
        retrieved = memory_store.get_decision(decision.id)
        assert retrieved is not None
        assert "dataclass" in retrieved.decision.lower()
        assert retrieved.source == "correction"

        # 6. Verify it shows up in list
        all_decisions = memory_store.list_decisions(sample_repo_path)
        assert len(all_decisions) >= 1
        assert any("dataclass" in d.decision.lower() for d in all_decisions)

    def test_markdown_context_rendering(
        self, memory_store: ProjectMemoryStore, sample_repo_path: str
    ) -> None:
        """Test rendering context to markdown for prompt injection."""
        now = datetime.now(timezone.utc)

        # Add some memories
        memory_store.add_decision(
            repo_path=sample_repo_path,
            decision="Use snake_case for variables",
            rationale="Python convention",
        )
        memory_store.add_pattern(
            repo_path=sample_repo_path,
            pattern_type="testing",
            description="Use pytest fixtures",
            applies_to="tests/*",
        )
        memory_store.record_session(
            session_id="prev-session",
            repo_path=sample_repo_path,
            prompt_summary="Previous work on authentication",
            started_at=now - timedelta(hours=1),
            ended_at=now - timedelta(minutes=30),
            outcome="completed",
            contract_fulfilled=True,
            iteration_count=2,
        )

        # Get context
        ctx = memory_store.get_relevant_context(
            repo_path=sample_repo_path,
            prompt="Continue work on user system",
        )

        # Render to markdown
        md = ctx.to_markdown()

        # Should be injectable into prompts
        assert isinstance(md, str)
        if ctx.relevant_decisions:
            assert "## Project Decisions" in md
        if ctx.applicable_patterns:
            assert "## Code Patterns" in md
        if ctx.recent_sessions:
            assert "## Recent Work" in md
