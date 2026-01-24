"""Tests for ArchiveService - LLM-driven conversation archival."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestArchiveServiceDataclasses:
    """Test the dataclass serialization."""

    def test_archive_result_to_dict(self) -> None:
        """ArchiveResult should serialize to dict."""
        from reos.services.archive_service import ArchiveResult

        result = ArchiveResult(
            archive_id="arc123",
            title="Test Archive",
            summary="A test conversation",
            message_count=10,
            linked_act_id="act_456",
            linking_reason="Related to project",
            knowledge_entries_added=3,
            topics=["python", "testing"],
            archived_at="2024-01-15T10:00:00Z",
        )
        d = result.to_dict()
        assert d["archive_id"] == "arc123"
        assert d["title"] == "Test Archive"
        assert d["knowledge_entries_added"] == 3
        assert d["topics"] == ["python", "testing"]

    def test_archive_preview_to_dict(self) -> None:
        """ArchivePreview should serialize to dict."""
        from reos.services.archive_service import ArchivePreview

        preview = ArchivePreview(
            title="Preview Title",
            summary="Preview summary",
            linked_act_id="act_789",
            linking_reason="Test linking",
            knowledge_entries=[
                {"category": "fact", "content": "Test fact"},
                {"category": "lesson", "content": "Test lesson"},
            ],
            topics=["topic1"],
            message_count=5,
        )
        d = preview.to_dict()
        assert d["title"] == "Preview Title"
        assert d["linked_act_id"] == "act_789"
        assert len(d["knowledge_entries"]) == 2
        assert d["message_count"] == 5

    def test_archive_quality_assessment_to_dict(self) -> None:
        """ArchiveQualityAssessment should serialize to dict."""
        from reos.services.archive_service import ArchiveQualityAssessment

        assessment = ArchiveQualityAssessment(
            assessment_id="assess123",
            archive_id="arc123",
            title_quality=4,
            summary_quality=5,
            act_linking=3,
            knowledge_relevance=4,
            knowledge_coverage=4,
            deduplication=5,
            overall_score=4,
            suggestions=["Add more context"],
            user_feedback=None,
            user_rating=None,
            assessed_at="2024-01-15T10:00:00Z",
        )
        d = assessment.to_dict()
        assert d["overall_score"] == 4
        assert d["suggestions"] == ["Add more context"]
        assert d["user_feedback"] is None


class TestArchiveServiceInit:
    """Test ArchiveService initialization."""

    def test_init_creates_knowledge_store(self) -> None:
        """ArchiveService should create a KnowledgeStore."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            assert service._db == mock_db
            assert service._knowledge_store is not None


class TestArchiveServicePreview:
    """Test preview_archive functionality."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock database."""
        db = MagicMock()
        db.get_messages.return_value = [
            {"role": "user", "content": "Hello, how are you?", "created_at": "2024-01-15T10:00:00Z"},
            {"role": "assistant", "content": "I'm doing well!", "created_at": "2024-01-15T10:01:00Z"},
        ]
        return db

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Create a mock LLM provider."""
        provider = MagicMock()
        provider.chat_text.return_value = json.dumps({
            "title": "Greeting Conversation",
            "summary": "A friendly greeting exchange.",
            "linked_act_id": None,
            "linking_reason": None,
            "knowledge_entries": [],
            "topics": ["greeting"],
            "sentiment": "positive",
        })
        return provider

    def test_preview_archive_no_messages_raises(self, mock_db: MagicMock) -> None:
        """Should raise ValueError if no messages."""
        from reos.services.archive_service import ArchiveService

        mock_db.get_messages.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            with pytest.raises(ValueError, match="No messages"):
                service.preview_archive("conv123")

    def test_preview_archive_returns_preview(
        self, mock_db: MagicMock, mock_provider: MagicMock
    ) -> None:
        """Should return ArchivePreview with LLM analysis."""
        from reos.services.archive_service import ArchiveService, ArchivePreview

        with patch("reos.services.archive_service.KnowledgeStore"), \
             patch("reos.services.archive_service.get_provider", return_value=mock_provider):
            service = ArchiveService(mock_db)
            # Mock _get_acts_context
            service._get_acts_context = MagicMock(return_value="No acts available")

            preview = service.preview_archive("conv123")

            assert isinstance(preview, ArchivePreview)
            assert preview.title == "Greeting Conversation"
            assert preview.message_count == 2


class TestArchiveServiceArchiveWithReview:
    """Test archive_with_review functionality."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock database."""
        db = MagicMock()
        db.get_messages.return_value = [
            {"role": "user", "content": "Test message", "created_at": "2024-01-15T10:00:00Z"},
        ]
        return db

    @pytest.fixture
    def mock_archive(self) -> MagicMock:
        """Create a mock Archive object."""
        archive = MagicMock()
        archive.archive_id = "arc123"
        archive.title = "User Title"
        archive.summary = "User summary"
        archive.message_count = 1
        archive.archived_at = "2024-01-15T10:00:00Z"
        return archive

    def test_archive_with_review_saves_archive(
        self, mock_db: MagicMock, mock_archive: MagicMock
    ) -> None:
        """Should save archive with user-provided data."""
        from reos.services.archive_service import ArchiveService

        mock_knowledge_store = MagicMock()
        mock_knowledge_store.save_archive.return_value = mock_archive
        mock_knowledge_store.add_learned_entries.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            service._store_archive_metadata = MagicMock()

            result = service.archive_with_review(
                conversation_id="conv123",
                title="User Title",
                summary="User summary",
                act_id="act_456",
                knowledge_entries=[{"category": "fact", "content": "Test fact"}],
            )

            assert result.archive_id == "arc123"
            assert result.title == "User Title"
            mock_knowledge_store.save_archive.assert_called_once()

    def test_archive_with_review_adds_knowledge_entries(
        self, mock_db: MagicMock, mock_archive: MagicMock
    ) -> None:
        """Should add knowledge entries from user review."""
        from reos.services.archive_service import ArchiveService

        mock_knowledge_store = MagicMock()
        mock_knowledge_store.save_archive.return_value = mock_archive
        mock_knowledge_store.add_learned_entries.return_value = ["entry1", "entry2"]

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            service._store_archive_metadata = MagicMock()

            result = service.archive_with_review(
                conversation_id="conv123",
                title="Title",
                summary="Summary",
                knowledge_entries=[
                    {"category": "fact", "content": "Fact 1"},
                    {"category": "lesson", "content": "Lesson 1"},
                ],
            )

            assert result.knowledge_entries_added == 2

    def test_archive_with_review_adds_additional_notes(
        self, mock_db: MagicMock, mock_archive: MagicMock
    ) -> None:
        """Should add additional notes as observation."""
        from reos.services.archive_service import ArchiveService

        mock_knowledge_store = MagicMock()
        mock_knowledge_store.save_archive.return_value = mock_archive
        mock_knowledge_store.add_learned_entries.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            service._store_archive_metadata = MagicMock()

            result = service.archive_with_review(
                conversation_id="conv123",
                title="Title",
                summary="Summary",
                knowledge_entries=[],
                additional_notes="User's additional note",
            )

            # Empty knowledge_entries means only notes call happens
            assert mock_knowledge_store.add_learned_entries.call_count == 1
            # Check the notes call
            notes_call = mock_knowledge_store.add_learned_entries.call_args
            assert notes_call[1]["entries"][0]["category"] == "observation"
            assert notes_call[1]["entries"][0]["content"] == "User's additional note"

    def test_archive_with_review_submits_rating(
        self, mock_db: MagicMock, mock_archive: MagicMock
    ) -> None:
        """Should submit user rating for learning."""
        from reos.services.archive_service import ArchiveService

        mock_knowledge_store = MagicMock()
        mock_knowledge_store.save_archive.return_value = mock_archive
        mock_knowledge_store.add_learned_entries.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            service._store_archive_metadata = MagicMock()
            service.submit_user_feedback = MagicMock()

            service.archive_with_review(
                conversation_id="conv123",
                title="Title",
                summary="Summary",
                knowledge_entries=[],
                rating=5,
            )

            service.submit_user_feedback.assert_called_once_with("arc123", 5)


class TestArchiveServiceFullArchive:
    """Test archive_conversation (auto mode)."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock database."""
        db = MagicMock()
        db.get_messages.return_value = [
            {"role": "user", "content": "Hello", "created_at": "2024-01-15T10:00:00Z"},
            {"role": "assistant", "content": "Hi there!", "created_at": "2024-01-15T10:01:00Z"},
        ]
        return db

    def test_archive_conversation_no_messages_raises(self, mock_db: MagicMock) -> None:
        """Should raise ValueError if no messages."""
        from reos.services.archive_service import ArchiveService

        mock_db.get_messages.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            with pytest.raises(ValueError, match="No messages"):
                service.archive_conversation("conv123")


class TestArchiveServiceMetadata:
    """Test metadata storage methods."""

    def test_store_archive_metadata(self) -> None:
        """Should store metadata in database."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.connect.return_value = mock_conn

        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            service._store_archive_metadata(
                archive_id="arc123",
                conversation_id="conv123",
                act_id="act_456",
                linking_reason="Test reason",
                topics=["topic1"],
                sentiment="positive",
            )

            mock_conn.execute.assert_called_once()


class TestArchiveServiceFeedback:
    """Test user feedback methods."""

    def test_submit_user_feedback(self) -> None:
        """Should store user feedback in database."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.connect.return_value = mock_conn

        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            service.submit_user_feedback("arc123", 5, "Great job!")

            mock_conn.execute.assert_called_once()

    def test_get_learning_stats(self) -> None:
        """Should return learning statistics."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.connect.return_value = mock_conn
        # Mock the execute calls to return cursor with fetchone
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            {"total_feedback": 10, "avg_rating": 4.2, "min_rating": 2, "max_rating": 5},
            {"total_assessments": 5, "avg_score": 3.8, "min_score": 2, "max_score": 5},
        ]
        mock_conn.execute.return_value = mock_cursor

        with patch("reos.services.archive_service.KnowledgeStore"):
            service = ArchiveService(mock_db)
            stats = service.get_learning_stats()

            assert stats["total_user_feedback"] == 10
            assert stats["avg_user_rating"] == 4.2


class TestArchiveServiceList:
    """Test archive listing methods."""

    def test_list_archives_returns_list(self) -> None:
        """Should return list of archives."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        mock_knowledge_store = MagicMock()
        mock_knowledge_store.list_archives.return_value = []

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            archives = service.list_archives()

            assert isinstance(archives, list)

    def test_get_archive_returns_archive(self) -> None:
        """Should return archive by ID."""
        from reos.services.archive_service import ArchiveService

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.connect.return_value = mock_conn
        # Mock metadata query - returns None (no metadata)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.execute.return_value = mock_cursor

        mock_archive = MagicMock()
        mock_archive.archive_id = "arc123"
        mock_archive.title = "Test"
        mock_archive.summary = "Test summary"
        mock_archive.message_count = 5
        mock_archive.archived_at = "2024-01-15T10:00:00Z"
        mock_archive.messages = []
        mock_knowledge_store = MagicMock()
        mock_knowledge_store.get_archive.return_value = mock_archive

        with patch("reos.services.archive_service.KnowledgeStore", return_value=mock_knowledge_store):
            service = ArchiveService(mock_db)
            archive = service.get_archive("arc123")

            # get_archive returns a dict
            assert archive is not None
            assert archive["archive_id"] == "arc123"
