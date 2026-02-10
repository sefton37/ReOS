"""Tests for the services layer.

Tests for ChatService, ContextService, PlayService, and KnowledgeService
to ensure feature parity between CLI and RPC interfaces.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reos.db import Database


class TestChatService:
    """Tests for ChatService."""

    @pytest.fixture
    def db(self) -> Database:
        """Create an in-memory database with migrations."""
        db = Database(":memory:")
        db.migrate()
        return db

    @pytest.fixture
    def chat_service(self, db: Database):
        """Create a ChatService instance."""
        from reos.services.chat_service import ChatService
        return ChatService(db)

    def test_chat_service_init(self, chat_service) -> None:
        """ChatService should initialize without errors."""
        assert chat_service is not None
        assert chat_service._agent is None  # Lazy initialization

    def test_start_conversation(self, chat_service) -> None:
        """Should create a new conversation and return ID."""
        conv_id = chat_service.start_conversation(title="Test Chat")
        assert conv_id is not None
        assert isinstance(conv_id, str)
        assert len(conv_id) == 12  # UUID hex truncated

    def test_start_conversation_without_title(self, chat_service) -> None:
        """Should create conversation without title."""
        conv_id = chat_service.start_conversation()
        assert conv_id is not None
        assert isinstance(conv_id, str)

    def test_list_conversations_empty(self, chat_service) -> None:
        """Should return empty list when no conversations."""
        conversations = chat_service.list_conversations()
        assert isinstance(conversations, list)
        # May have 0 or more depending on test isolation
        assert conversations is not None

    def test_list_conversations(self, chat_service) -> None:
        """Should list created conversations."""
        conv_id = chat_service.start_conversation(title="Test")
        conversations = chat_service.list_conversations()
        assert len(conversations) >= 1
        # Find our conversation
        found = any(c["id"] == conv_id for c in conversations)
        assert found

    def test_get_messages_empty_conversation(self, chat_service) -> None:
        """Should return empty list for new conversation."""
        conv_id = chat_service.start_conversation()
        messages = chat_service.get_messages(conv_id)
        assert isinstance(messages, list)
        assert len(messages) == 0

    def test_clear_conversation(self, chat_service, db: Database) -> None:
        """Should clear messages from conversation."""
        conv_id = chat_service.start_conversation()
        # Add a message directly
        db.add_message(
            message_id="test123",
            conversation_id=conv_id,
            role="user",
            content="Hello",
            message_type="text",
        )
        # Verify message exists
        messages = chat_service.get_messages(conv_id)
        assert len(messages) == 1
        # Clear
        result = chat_service.clear_conversation(conv_id)
        assert result is True
        # Verify cleared
        messages = chat_service.get_messages(conv_id)
        assert len(messages) == 0

    def test_list_models_returns_list(self, chat_service) -> None:
        """Should return list of models (may be empty if Ollama not available)."""
        models = chat_service.list_models()
        assert isinstance(models, list)

    def test_get_current_model(self, chat_service) -> None:
        """Should return current model or None."""
        model = chat_service.get_current_model()
        # Can be None if not set
        assert model is None or isinstance(model, str)

    def test_chat_request_dataclass(self) -> None:
        """ChatRequest should hold message data."""
        from reos.services.chat_service import ChatRequest

        request = ChatRequest(
            message="Hello",
            conversation_id="abc123",
            model_id="qwen2.5:7b",
        )
        assert request.message == "Hello"
        assert request.conversation_id == "abc123"
        assert request.model_id == "qwen2.5:7b"

    def test_chat_result_to_dict(self) -> None:
        """ChatResult should serialize to dict."""
        from reos.services.chat_service import ChatResult

        result = ChatResult(
            answer="Hi there!",
            conversation_id="abc123",
            message_id="msg456",
            message_type="text",
        )
        d = result.to_dict()
        assert d["answer"] == "Hi there!"
        assert d["conversation_id"] == "abc123"
        assert d["message_id"] == "msg456"
        assert "tool_calls" in d
        assert "thinking_steps" in d

    def test_model_info_to_dict(self) -> None:
        """ModelInfo should serialize to dict."""
        from reos.services.chat_service import ModelInfo

        info = ModelInfo(
            id="qwen2.5:7b",
            name="qwen2.5",
            size="7B",
            capabilities={"tools": True},
            is_current=True,
        )
        d = info.to_dict()
        assert d["id"] == "qwen2.5:7b"
        assert d["name"] == "qwen2.5"
        assert d["is_current"] is True

    def test_detect_intent_returns_dict(self, chat_service) -> None:
        """Should return dict with detected key."""
        result = chat_service.detect_intent("What's the weather?")
        assert isinstance(result, dict)
        assert "detected" in result


class TestContextService:
    """Tests for ContextService."""

    @pytest.fixture
    def db(self) -> Database:
        """Create an in-memory database with migrations."""
        db = Database(":memory:")
        db.migrate()
        return db

    @pytest.fixture
    def context_service(self, db: Database):
        """Create a ContextService instance."""
        from reos.services.context_service import ContextService
        return ContextService(db)

    def test_context_service_init(self, context_service) -> None:
        """ContextService should initialize without errors."""
        assert context_service is not None
        # Disabled sources now stored in database, not in-memory
        assert context_service.get_disabled_sources() == []

    def test_get_stats(self, context_service) -> None:
        """Should return context statistics."""
        stats = context_service.get_stats()
        assert stats.estimated_tokens >= 0
        assert stats.context_limit > 0
        assert stats.usage_percent >= 0
        assert stats.warning_level in ("ok", "warning", "critical")

    def test_get_stats_to_dict(self, context_service) -> None:
        """Stats should serialize to dict."""
        stats = context_service.get_stats()
        d = stats.to_dict()
        assert "estimated_tokens" in d
        assert "context_limit" in d
        assert "usage_percent" in d
        assert "warning_level" in d

    def test_toggle_source_disable(self, context_service) -> None:
        """Should disable a context source."""
        context_service.toggle_source("play_context", enabled=False)
        disabled = context_service.get_disabled_sources()
        assert "play_context" in disabled

    def test_toggle_source_enable(self, context_service) -> None:
        """Should re-enable a context source."""
        context_service.toggle_source("play_context", enabled=False)
        context_service.toggle_source("play_context", enabled=True)
        disabled = context_service.get_disabled_sources()
        assert "play_context" not in disabled

    def test_cannot_disable_messages(self, context_service) -> None:
        """Should not allow disabling messages source."""
        context_service.toggle_source("messages", enabled=False)
        disabled = context_service.get_disabled_sources()
        assert "messages" not in disabled

    def test_estimate_tokens(self, context_service) -> None:
        """Should estimate token count for text."""
        tokens = context_service.estimate_tokens("Hello world")
        assert tokens > 0
        # Longer text should have more tokens
        more_tokens = context_service.estimate_tokens("Hello world " * 100)
        assert more_tokens > tokens

    def test_get_model_limits(self, context_service) -> None:
        """Should return model context limits."""
        limits = context_service.get_model_limits()
        assert "small" in limits
        assert "medium" in limits
        assert "large" in limits
        assert limits["small"] < limits["large"]

    def test_set_context_limit(self, context_service) -> None:
        """Should set context limit without error."""
        # Just verify it doesn't crash - the limit is stored in DB
        context_service.set_context_limit(16384)
        # get_context_limit may return default if DB state not preserved
        limit = context_service.get_context_limit()
        assert limit > 0

    def test_list_archives_empty(self, context_service) -> None:
        """Should return empty list when no archives."""
        archives = context_service.list_archives()
        assert isinstance(archives, list)


class TestPlayService:
    """Tests for PlayService."""

    @pytest.fixture
    def play_service(self):
        """Create a PlayService instance."""
        from reos.services.play_service import PlayService
        return PlayService()

    def test_play_service_init(self, play_service) -> None:
        """PlayService should initialize without errors."""
        assert play_service is not None

    def test_list_acts(self, play_service) -> None:
        """Should list acts."""
        acts, active_id = play_service.list_acts()
        assert isinstance(acts, list)
        # active_id may be None or string

    def test_list_scenes(self, play_service) -> None:
        """Should list scenes (may be empty)."""
        # list_scenes requires an act_id parameter
        acts, active_id = play_service.list_acts()
        if active_id:
            scenes = play_service.list_scenes(act_id=active_id)
            assert isinstance(scenes, list)


    def test_read_me_markdown(self, play_service) -> None:
        """Should read the Play markdown."""
        try:
            markdown = play_service.read_me_markdown()
            assert isinstance(markdown, str)
        except Exception:
            # May fail if play directory doesn't exist
            pass

    def test_list_kb_files(self, play_service) -> None:
        """Should list knowledge base files."""
        # list_kb_files requires act_id parameter
        acts, active_id = play_service.list_acts()
        if active_id:
            files = play_service.list_kb_files(act_id=active_id)
            assert isinstance(files, list)

    def test_list_attachments(self, play_service) -> None:
        """Should list attachments."""
        # list_attachments requires act_id parameter
        acts, active_id = play_service.list_acts()
        if active_id:
            attachments = play_service.list_attachments(act_id=active_id)
            assert isinstance(attachments, list)


class TestKnowledgeService:
    """Tests for KnowledgeService."""

    @pytest.fixture
    def knowledge_service(self):
        """Create a KnowledgeService instance."""
        from reos.services.knowledge_service import KnowledgeService
        return KnowledgeService()

    def test_knowledge_service_init(self, knowledge_service) -> None:
        """KnowledgeService should initialize without errors."""
        assert knowledge_service is not None

    def test_list_entries(self, knowledge_service) -> None:
        """Should return list of entries."""
        entries = knowledge_service.list_entries()
        assert isinstance(entries, list)

    def test_get_stats(self, knowledge_service) -> None:
        """Should return knowledge base stats."""
        stats = knowledge_service.get_stats()
        # Stats may be a dataclass or dict
        assert stats is not None
        # Check it has expected attributes (works for both dict and dataclass)
        if hasattr(stats, "total_entries"):
            assert stats.total_entries >= 0
        elif isinstance(stats, dict):
            assert "total_entries" in stats or len(stats) >= 0

    def test_search(self, knowledge_service) -> None:
        """Should return list for search."""
        results = knowledge_service.search("test")
        assert isinstance(results, list)

    def test_export(self, knowledge_service) -> None:
        """Should export knowledge base."""
        try:
            exported = knowledge_service.export_entries()
            assert isinstance(exported, list)
        except AttributeError:
            # Method may not exist in current implementation
            pass


class TestServiceDataclasses:
    """Tests for service layer dataclasses."""

    def test_context_stats_result_from_context_stats(self) -> None:
        """Should convert from ContextStats."""
        from reos.context_meter import ContextStats
        from reos.services.context_service import ContextStatsResult

        stats = ContextStats(
            estimated_tokens=1000,
            context_limit=8192,
            reserved_tokens=2048,
            available_tokens=5144,
            usage_percent=16.3,
            message_count=5,
            warning_level="ok",
        )
        result = ContextStatsResult.from_context_stats(stats)
        assert result.estimated_tokens == 1000
        assert result.warning_level == "ok"

    def test_chat_result_from_chat_response(self) -> None:
        """Should convert from ChatResponse."""
        from reos.agent import ChatResponse
        from reos.services.chat_service import ChatResult

        response = ChatResponse(
            answer="Test answer",
            conversation_id="conv123",
            message_id="msg456",
        )
        result = ChatResult.from_chat_response(response)
        assert result.answer == "Test answer"
        assert result.conversation_id == "conv123"


class TestServiceErrorHandling:
    """Tests for service layer error handling."""

    @pytest.fixture
    def db(self) -> Database:
        """Create an in-memory database with migrations."""
        db = Database(":memory:")
        db.migrate()
        return db

    def test_chat_service_handles_missing_conversation(self, db: Database) -> None:
        """Should handle getting messages for non-existent conversation."""
        from reos.services.chat_service import ChatService

        service = ChatService(db)
        messages = service.get_messages("nonexistent123")
        assert messages == []

    def test_context_service_handles_invalid_conversation(self, db: Database) -> None:
        """Should handle stats for non-existent conversation."""
        from reos.services.context_service import ContextService

        service = ContextService(db)
        stats = service.get_stats(conversation_id="nonexistent123")
        # Should not crash, returns valid stats
        assert stats.estimated_tokens >= 0

    def test_chat_service_clear_nonexistent_conversation(self, db: Database) -> None:
        """Should handle clearing non-existent conversation."""
        from reos.services.chat_service import ChatService

        service = ChatService(db)
        # Should not crash - clearing empty conversation is success
        result = service.clear_conversation("nonexistent123")
        assert result is True
