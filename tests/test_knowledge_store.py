"""Tests for KnowledgeStore - Persistent AI memory from conversations."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from reos.knowledge_store import (
    Archive,
    LearnedEntry,
    LearnedKnowledge,
    KnowledgeStore,
)


class TestArchiveDataclass:
    """Test Archive dataclass."""

    def test_to_dict(self) -> None:
        """Archive should serialize to dict."""
        archive = Archive(
            archive_id="arc123",
            act_id="act_456",
            title="Test Archive",
            created_at="2024-01-15T10:00:00",
            archived_at="2024-01-15T11:00:00",
            message_count=5,
            messages=[{"role": "user", "content": "Hello"}],
            summary="A test conversation",
        )
        d = archive.to_dict()
        assert d["archive_id"] == "arc123"
        assert d["act_id"] == "act_456"
        assert d["title"] == "Test Archive"
        assert d["message_count"] == 5
        assert d["summary"] == "A test conversation"

    def test_from_dict(self) -> None:
        """Archive should deserialize from dict."""
        data = {
            "archive_id": "arc123",
            "act_id": None,
            "title": "Test",
            "created_at": "2024-01-15T10:00:00",
            "archived_at": "2024-01-15T11:00:00",
            "message_count": 2,
            "messages": [],
        }
        archive = Archive.from_dict(data)
        assert archive.archive_id == "arc123"
        assert archive.act_id is None
        assert archive.summary == ""  # default

    def test_from_dict_with_summary(self) -> None:
        """Archive should deserialize summary if present."""
        data = {
            "archive_id": "arc123",
            "title": "Test",
            "created_at": "2024-01-15T10:00:00",
            "archived_at": "2024-01-15T11:00:00",
            "message_count": 2,
            "messages": [],
            "summary": "Test summary",
        }
        archive = Archive.from_dict(data)
        assert archive.summary == "Test summary"


class TestLearnedEntryDataclass:
    """Test LearnedEntry dataclass."""

    def test_to_dict(self) -> None:
        """LearnedEntry should serialize to dict."""
        entry = LearnedEntry(
            entry_id="entry123",
            category="fact",
            content="Python is a programming language",
            learned_at="2024-01-15T10:00:00",
            source_archive_id="arc456",
        )
        d = entry.to_dict()
        assert d["entry_id"] == "entry123"
        assert d["category"] == "fact"
        assert d["content"] == "Python is a programming language"
        assert d["source_archive_id"] == "arc456"

    def test_from_dict(self) -> None:
        """LearnedEntry should deserialize from dict."""
        data = {
            "entry_id": "entry123",
            "category": "lesson",
            "content": "Always test your code",
            "learned_at": "2024-01-15T10:00:00",
        }
        entry = LearnedEntry.from_dict(data)
        assert entry.entry_id == "entry123"
        assert entry.category == "lesson"
        assert entry.source_archive_id is None  # default


class TestLearnedKnowledgeDataclass:
    """Test LearnedKnowledge dataclass."""

    def test_to_dict(self) -> None:
        """LearnedKnowledge should serialize to dict."""
        kb = LearnedKnowledge(
            act_id="act_123",
            entries=[
                LearnedEntry(
                    entry_id="e1",
                    category="fact",
                    content="Test fact",
                    learned_at="2024-01-15T10:00:00",
                )
            ],
            last_updated="2024-01-15T11:00:00",
        )
        d = kb.to_dict()
        assert d["act_id"] == "act_123"
        assert len(d["entries"]) == 1
        assert d["last_updated"] == "2024-01-15T11:00:00"

    def test_from_dict(self) -> None:
        """LearnedKnowledge should deserialize from dict."""
        data = {
            "act_id": None,
            "entries": [
                {
                    "entry_id": "e1",
                    "category": "fact",
                    "content": "Test fact",
                    "learned_at": "2024-01-15T10:00:00",
                }
            ],
        }
        kb = LearnedKnowledge.from_dict(data)
        assert kb.act_id is None
        assert len(kb.entries) == 1
        assert kb.last_updated == ""  # default

    def test_to_markdown_empty(self) -> None:
        """Empty KB should return empty markdown."""
        kb = LearnedKnowledge(act_id=None)
        assert kb.to_markdown() == ""

    def test_to_markdown_with_entries(self) -> None:
        """KB with entries should render markdown."""
        kb = LearnedKnowledge(
            act_id=None,
            entries=[
                LearnedEntry(
                    entry_id="e1",
                    category="fact",
                    content="Python is great",
                    learned_at="2024-01-15T10:00:00",
                ),
                LearnedEntry(
                    entry_id="e2",
                    category="lesson",
                    content="Test early",
                    learned_at="2024-01-16T10:00:00",
                ),
            ],
        )
        md = kb.to_markdown()
        assert "# Learned Knowledge" in md
        assert "## Facts" in md
        assert "## Lessons" in md
        assert "Python is great" in md
        assert "Test early" in md
        assert "[2024-01-15]" in md

    def test_to_markdown_with_unknown_category(self) -> None:
        """KB should handle unknown categories."""
        kb = LearnedKnowledge(
            act_id=None,
            entries=[
                LearnedEntry(
                    entry_id="e1",
                    category="custom",
                    content="Custom entry",
                    learned_at="2024-01-15T10:00:00",
                ),
            ],
        )
        md = kb.to_markdown()
        # Should still include the entry under its category
        assert "# Learned Knowledge" in md


class TestKnowledgeStoreInit:
    """Test KnowledgeStore initialization."""

    def test_init_with_custom_root(self) -> None:
        """Should use provided data root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = KnowledgeStore(data_root=root)
            assert store._root == root


class TestKnowledgeStoreArchives:
    """Test archive operations."""

    @pytest.fixture
    def store(self) -> KnowledgeStore:
        """Create a store with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield KnowledgeStore(data_root=Path(tmpdir))

    def test_save_archive(self, store: KnowledgeStore) -> None:
        """Should save archive to disk."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        archive = store.save_archive(messages=messages, title="Test")

        assert archive.archive_id
        assert archive.title == "Test"
        assert archive.message_count == 2

    def test_save_archive_auto_title(self, store: KnowledgeStore) -> None:
        """Should auto-generate title from first user message."""
        messages = [
            {"role": "user", "content": "What is the weather today?"},
            {"role": "assistant", "content": "I don't have weather data."},
        ]
        archive = store.save_archive(messages=messages)

        assert "What is the weather today?" in archive.title

    def test_save_archive_auto_title_truncates(self, store: KnowledgeStore) -> None:
        """Should truncate long auto-titles."""
        messages = [
            {"role": "user", "content": "A" * 100},  # Very long message
        ]
        archive = store.save_archive(messages=messages)

        assert len(archive.title) <= 53  # 50 chars + "..."
        assert archive.title.endswith("...")

    def test_save_archive_no_user_message(self, store: KnowledgeStore) -> None:
        """Should use default title if no user messages."""
        messages = [
            {"role": "assistant", "content": "Hello!"},
        ]
        archive = store.save_archive(messages=messages)

        assert "Conversation" in archive.title

    def test_save_archive_with_act_id(self, store: KnowledgeStore) -> None:
        """Should save archive under act directory."""
        messages = [{"role": "user", "content": "Test"}]
        archive = store.save_archive(messages=messages, act_id="act_123")

        assert archive.act_id == "act_123"
        # Verify file exists in act directory
        path = store._archives_dir("act_123") / f"{archive.archive_id}.json"
        assert path.exists()

    def test_save_archive_with_summary(self, store: KnowledgeStore) -> None:
        """Should store summary."""
        messages = [{"role": "user", "content": "Test"}]
        archive = store.save_archive(
            messages=messages,
            title="Test",
            summary="This is a test conversation"
        )

        assert archive.summary == "This is a test conversation"

    def test_save_archive_uses_message_timestamp(self, store: KnowledgeStore) -> None:
        """Should use first message timestamp as created_at."""
        messages = [
            {"role": "user", "content": "Test", "created_at": "2024-01-01T12:00:00"}
        ]
        archive = store.save_archive(messages=messages)

        assert archive.created_at == "2024-01-01T12:00:00"

    def test_list_archives_empty(self, store: KnowledgeStore) -> None:
        """Should return empty list when no archives."""
        archives = store.list_archives()
        assert archives == []

    def test_list_archives(self, store: KnowledgeStore) -> None:
        """Should list all archives."""
        store.save_archive(messages=[{"role": "user", "content": "First"}], title="First")
        store.save_archive(messages=[{"role": "user", "content": "Second"}], title="Second")

        archives = store.list_archives()
        assert len(archives) == 2

    def test_list_archives_sorted_by_date(self, store: KnowledgeStore) -> None:
        """Should sort archives by archived_at descending."""
        store.save_archive(messages=[{"role": "user", "content": "1"}], title="First")
        store.save_archive(messages=[{"role": "user", "content": "2"}], title="Second")

        archives = store.list_archives()
        # Newest first
        assert archives[0].title == "Second"

    def test_list_archives_for_act(self, store: KnowledgeStore) -> None:
        """Should list archives only for specific act."""
        store.save_archive(messages=[{"role": "user", "content": "1"}], act_id="act_1")
        store.save_archive(messages=[{"role": "user", "content": "2"}], act_id="act_2")

        archives_act1 = store.list_archives(act_id="act_1")
        assert len(archives_act1) == 1

    def test_get_archive(self, store: KnowledgeStore) -> None:
        """Should retrieve archive by ID."""
        archive = store.save_archive(
            messages=[{"role": "user", "content": "Test"}],
            title="Get Test"
        )

        retrieved = store.get_archive(archive.archive_id)
        assert retrieved is not None
        assert retrieved.title == "Get Test"

    def test_get_archive_not_found(self, store: KnowledgeStore) -> None:
        """Should return None for non-existent archive."""
        retrieved = store.get_archive("nonexistent")
        assert retrieved is None

    def test_get_archive_with_act_id(self, store: KnowledgeStore) -> None:
        """Should get archive from specific act directory."""
        archive = store.save_archive(
            messages=[{"role": "user", "content": "Test"}],
            act_id="act_123"
        )

        retrieved = store.get_archive(archive.archive_id, act_id="act_123")
        assert retrieved is not None

    def test_delete_archive(self, store: KnowledgeStore) -> None:
        """Should delete archive."""
        archive = store.save_archive(messages=[{"role": "user", "content": "Test"}])

        result = store.delete_archive(archive.archive_id)
        assert result is True

        # Verify deleted
        assert store.get_archive(archive.archive_id) is None

    def test_delete_archive_not_found(self, store: KnowledgeStore) -> None:
        """Should return False when archive doesn't exist."""
        result = store.delete_archive("nonexistent")
        assert result is False

    def test_search_archives_by_title(self, store: KnowledgeStore) -> None:
        """Should find archives by title match."""
        store.save_archive(messages=[{"role": "user", "content": "x"}], title="Python Tutorial")
        store.save_archive(messages=[{"role": "user", "content": "y"}], title="JavaScript Guide")

        results = store.search_archives("python")
        assert len(results) == 1
        assert results[0].title == "Python Tutorial"

    def test_search_archives_by_content(self, store: KnowledgeStore) -> None:
        """Should find archives by message content."""
        store.save_archive(
            messages=[{"role": "user", "content": "How do I use pytest?"}],
            title="Question"
        )

        results = store.search_archives("pytest")
        assert len(results) == 1

    def test_search_archives_limit(self, store: KnowledgeStore) -> None:
        """Should respect limit parameter for content matches."""
        # Create archives where query matches in content but not title
        for i in range(5):
            store.save_archive(
                messages=[{"role": "user", "content": f"test python code {i}"}],
                title=f"Example {i}"
            )

        results = store.search_archives("python", limit=3)
        assert len(results) == 3

    def test_search_archives_case_insensitive(self, store: KnowledgeStore) -> None:
        """Search should be case insensitive."""
        store.save_archive(messages=[{"role": "user", "content": "x"}], title="PYTHON")

        results = store.search_archives("python")
        assert len(results) == 1


class TestKnowledgeStoreLearnedKnowledge:
    """Test learned knowledge operations."""

    @pytest.fixture
    def store(self) -> KnowledgeStore:
        """Create a store with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield KnowledgeStore(data_root=Path(tmpdir))

    def test_load_learned_empty(self, store: KnowledgeStore) -> None:
        """Should return empty KB when none exists."""
        kb = store.load_learned()
        assert kb.act_id is None
        assert len(kb.entries) == 0

    def test_save_and_load_learned(self, store: KnowledgeStore) -> None:
        """Should persist learned knowledge."""
        kb = LearnedKnowledge(
            act_id=None,
            entries=[
                LearnedEntry(
                    entry_id="e1",
                    category="fact",
                    content="Test fact",
                    learned_at="2024-01-15T10:00:00",
                )
            ],
        )
        store.save_learned(kb)

        loaded = store.load_learned()
        assert len(loaded.entries) == 1
        assert loaded.entries[0].content == "Test fact"

    def test_save_learned_updates_timestamp(self, store: KnowledgeStore) -> None:
        """Should update last_updated on save."""
        kb = LearnedKnowledge(act_id=None)
        store.save_learned(kb)

        loaded = store.load_learned()
        assert loaded.last_updated != ""

    def test_save_learned_for_act(self, store: KnowledgeStore) -> None:
        """Should save KB under act directory."""
        kb = LearnedKnowledge(act_id="act_123")
        store.save_learned(kb)

        # Verify file exists
        path = store._learned_path("act_123")
        assert path.exists()

    def test_add_learned_entries(self, store: KnowledgeStore) -> None:
        """Should add new entries to KB."""
        entries = [
            {"category": "fact", "content": "Python is great"},
            {"category": "lesson", "content": "Test early"},
        ]

        added = store.add_learned_entries(entries)
        assert len(added) == 2

        kb = store.load_learned()
        assert len(kb.entries) == 2

    def test_add_learned_entries_with_source(self, store: KnowledgeStore) -> None:
        """Should store source archive ID."""
        entries = [{"category": "fact", "content": "Test"}]

        added = store.add_learned_entries(entries, source_archive_id="arc123")
        assert added[0].source_archive_id == "arc123"

    def test_add_learned_entries_deduplication(self, store: KnowledgeStore) -> None:
        """Should skip duplicate entries."""
        entries = [{"category": "fact", "content": "Unique fact"}]

        store.add_learned_entries(entries)
        added = store.add_learned_entries(entries)  # Try to add again

        assert len(added) == 0  # Should be skipped
        kb = store.load_learned()
        assert len(kb.entries) == 1  # Only one entry

    def test_add_learned_entries_dedup_case_insensitive(self, store: KnowledgeStore) -> None:
        """Deduplication should be case insensitive."""
        store.add_learned_entries([{"category": "fact", "content": "Python"}])
        added = store.add_learned_entries([{"category": "fact", "content": "python"}])

        assert len(added) == 0

    def test_add_learned_entries_no_dedup(self, store: KnowledgeStore) -> None:
        """Should allow duplicates when dedup disabled."""
        entries = [{"category": "fact", "content": "Test"}]

        store.add_learned_entries(entries)
        added = store.add_learned_entries(entries, deduplicate=False)

        assert len(added) == 1
        kb = store.load_learned()
        assert len(kb.entries) == 2

    def test_add_learned_entries_empty_content(self, store: KnowledgeStore) -> None:
        """Should skip entries with empty content."""
        entries = [
            {"category": "fact", "content": ""},
            {"category": "fact", "content": "  "},
            {"category": "fact", "content": "Valid"},
        ]

        added = store.add_learned_entries(entries)
        assert len(added) == 1

    def test_add_learned_entries_default_category(self, store: KnowledgeStore) -> None:
        """Should use 'observation' as default category."""
        entries = [{"content": "No category specified"}]

        added = store.add_learned_entries(entries)
        assert added[0].category == "observation"

    def test_get_learned_markdown(self, store: KnowledgeStore) -> None:
        """Should return markdown representation."""
        store.add_learned_entries([
            {"category": "fact", "content": "Test fact"},
        ])

        md = store.get_learned_markdown()
        assert "# Learned Knowledge" in md
        assert "Test fact" in md

    def test_get_learned_entry_count(self, store: KnowledgeStore) -> None:
        """Should return entry count."""
        store.add_learned_entries([
            {"category": "fact", "content": "One"},
            {"category": "fact", "content": "Two"},
        ])

        count = store.get_learned_entry_count()
        assert count == 2

    def test_clear_learned(self, store: KnowledgeStore) -> None:
        """Should clear all learned entries."""
        store.add_learned_entries([
            {"category": "fact", "content": "To be cleared"},
        ])

        store.clear_learned()

        kb = store.load_learned()
        assert len(kb.entries) == 0

    def test_clear_learned_nonexistent(self, store: KnowledgeStore) -> None:
        """Should handle clearing non-existent KB."""
        store.clear_learned()  # Should not raise


class TestKnowledgeStoreErrorHandling:
    """Test error handling."""

    @pytest.fixture
    def store(self) -> KnowledgeStore:
        """Create a store with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield KnowledgeStore(data_root=Path(tmpdir))

    def test_list_archives_handles_corrupt_json(self, store: KnowledgeStore) -> None:
        """Should skip corrupt archive files."""
        # Save a valid archive
        store.save_archive(messages=[{"role": "user", "content": "Valid"}], title="Valid")

        # Create a corrupt archive file
        archives_dir = store._archives_dir(None)
        corrupt_path = archives_dir / "corrupt.json"
        corrupt_path.write_text("not valid json", encoding="utf-8")

        # Should still return valid archive
        archives = store.list_archives()
        assert len(archives) == 1
        assert archives[0].title == "Valid"

    def test_get_archive_handles_corrupt_json(self, store: KnowledgeStore) -> None:
        """Should return None for corrupt archive."""
        archives_dir = store._archives_dir(None)
        archives_dir.mkdir(parents=True, exist_ok=True)

        corrupt_path = archives_dir / "corrupt.json"
        corrupt_path.write_text("not valid json", encoding="utf-8")

        result = store.get_archive("corrupt")
        assert result is None

    def test_load_learned_handles_corrupt_json(self, store: KnowledgeStore) -> None:
        """Should return empty KB for corrupt learned.json."""
        path = store._learned_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json", encoding="utf-8")

        kb = store.load_learned()
        assert len(kb.entries) == 0
