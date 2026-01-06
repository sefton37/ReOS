"""Tests for API Documentation Lookup - prevent hallucination by fetching real docs."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from reos.code_mode.api_docs import (
    APIDocumentation,
    APIDocumentationLookup,
)


class TestAPIDocumentation:
    """Tests for APIDocumentation dataclass."""

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        doc = APIDocumentation(
            name="json.loads",
            symbol_type="function",
            language="python",
            signature="json.loads(s, ...)",
            summary="Deserialize JSON string to Python object.",
            parameters=[{"name": "s", "type": "str"}],
            returns="Any",
            source="stdlib",
        )

        result = doc.to_dict()

        assert result["name"] == "json.loads"
        assert result["symbol_type"] == "function"
        assert result["language"] == "python"
        assert result["signature"] == "json.loads(s, ...)"
        assert result["summary"] == "Deserialize JSON string to Python object."
        assert result["parameters"] == [{"name": "s", "type": "str"}]
        assert result["returns"] == "Any"
        assert result["source"] == "stdlib"
        assert "cached_at" in result

    def test_from_dict(self) -> None:
        """Should deserialize from dictionary."""
        data = {
            "name": "pathlib.Path",
            "symbol_type": "class",
            "language": "python",
            "signature": "Path(*args)",
            "summary": "PurePath subclass for filesystem paths.",
            "parameters": [{"name": "args", "type": "str"}],
            "returns": None,
            "source": "stdlib",
            "cached_at": "2024-01-01T00:00:00+00:00",
        }

        doc = APIDocumentation.from_dict(data)

        assert doc.name == "pathlib.Path"
        assert doc.symbol_type == "class"
        assert doc.language == "python"
        assert doc.signature == "Path(*args)"
        assert doc.cached_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_format_for_context(self) -> None:
        """Should format documentation for LLM context."""
        doc = APIDocumentation(
            name="json.loads",
            symbol_type="function",
            language="python",
            signature="json.loads(s, cls, ...)",
            summary="Parse JSON string.",
            parameters=[{"name": "s", "type": "str"}, {"name": "cls", "type": "type"}],
            returns="Any",
            source="stdlib",
        )

        result = doc.format_for_context()

        assert "json.loads" in result
        assert "json.loads(s, cls, ...)" in result
        assert "Parse JSON string." in result
        assert "Parameters:" in result
        assert "Returns: Any" in result


class TestAPIDocumentationLookup:
    """Tests for APIDocumentationLookup class."""

    @pytest.fixture
    def temp_db(self) -> Path:
        """Create a temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return Path(f.name)

    def test_init_creates_schema(self, temp_db: Path) -> None:
        """Should create database schema on init."""
        lookup = APIDocumentationLookup(temp_db)

        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='api_documentation'"
            )
            assert cursor.fetchone() is not None

    def test_cache_and_retrieve(self, temp_db: Path) -> None:
        """Should cache and retrieve documentation."""
        lookup = APIDocumentationLookup(temp_db)

        doc = APIDocumentation(
            name="test.func",
            symbol_type="function",
            language="python",
            signature="func(x)",
            summary="Test function.",
            source="local",
        )
        lookup._cache_documentation(doc)

        result = lookup._fetch_from_cache("test.func", "python")

        assert result is not None
        assert result.name == "test.func"
        assert result.summary == "Test function."

    def test_stdlib_lookup_json(self, temp_db: Path) -> None:
        """Should look up stdlib documentation for json module."""
        lookup = APIDocumentationLookup(temp_db)

        doc = lookup.get_documentation("json")

        assert doc is not None
        assert doc.name == "json"
        assert doc.source == "stdlib"
        assert doc.symbol_type == "module"

    def test_stdlib_lookup_json_loads(self, temp_db: Path) -> None:
        """Should look up stdlib documentation for json.loads."""
        lookup = APIDocumentationLookup(temp_db)

        doc = lookup.get_documentation("json.loads")

        assert doc is not None
        assert doc.name == "json.loads"
        assert doc.source == "stdlib"
        assert doc.symbol_type == "function"
        assert doc.signature is not None

    def test_stdlib_lookup_pathlib_path(self, temp_db: Path) -> None:
        """Should look up stdlib documentation for pathlib.Path."""
        lookup = APIDocumentationLookup(temp_db)

        doc = lookup.get_documentation("pathlib.Path")

        assert doc is not None
        assert doc.name == "pathlib.Path"
        assert doc.source == "stdlib"
        assert doc.symbol_type == "class"

    def test_batch_lookup(self, temp_db: Path) -> None:
        """Should batch lookup multiple symbols."""
        lookup = APIDocumentationLookup(temp_db)

        docs = lookup.get_documentation_batch(["json", "pathlib", "os"])

        assert len(docs) >= 2  # At least json and pathlib should work
        names = [d.name for d in docs]
        assert "json" in names

    def test_extract_symbols_from_code(self, temp_db: Path) -> None:
        """Should extract symbols from Python code."""
        lookup = APIDocumentationLookup(temp_db)

        code = """
import json
from pathlib import Path
from collections import defaultdict
"""

        symbols = lookup.extract_symbols_from_code(code)

        assert "json" in symbols
        assert "pathlib.Path" in symbols
        assert "collections.defaultdict" in symbols

    def test_extract_symbols_from_prompt(self, temp_db: Path) -> None:
        """Should extract symbols from natural language prompt."""
        lookup = APIDocumentationLookup(temp_db)

        prompt = "Use pandas to read a CSV file and json to parse the config"

        symbols = lookup.extract_symbols_from_prompt(prompt)

        assert "pandas" in symbols
        assert "json" in symbols

    def test_cache_ttl_expired(self, temp_db: Path) -> None:
        """Should expire cached entries after TTL."""
        lookup = APIDocumentationLookup(temp_db, ttl_days=0)  # Immediate expiry

        doc = APIDocumentation(
            name="old.func",
            symbol_type="function",
            language="python",
            signature="func()",
            summary="Old function.",
            source="local",
            cached_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Very old
        )

        # Manually insert with old timestamp
        with sqlite3.connect(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO api_documentation
                (name, symbol_type, language, signature, summary, source, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.name,
                    doc.symbol_type,
                    doc.language,
                    doc.signature,
                    doc.summary,
                    doc.source,
                    doc.cached_at.isoformat(),
                ),
            )
            conn.commit()

        # Should return None due to TTL expiry
        result = lookup._fetch_from_cache("old.func", "python")

        assert result is None

    def test_clear_cache(self, temp_db: Path) -> None:
        """Should clear all cached documentation."""
        lookup = APIDocumentationLookup(temp_db)

        # Cache some docs
        lookup.get_documentation("json")
        lookup.get_documentation("os")

        stats_before = lookup.get_cache_stats()
        assert stats_before["total"] > 0

        deleted = lookup.clear_cache()

        stats_after = lookup.get_cache_stats()
        assert stats_after["total"] == 0
        assert deleted > 0

    def test_cache_stats(self, temp_db: Path) -> None:
        """Should return cache statistics."""
        lookup = APIDocumentationLookup(temp_db)

        # Cache some stdlib docs
        lookup.get_documentation("json")
        lookup.get_documentation("os")

        stats = lookup.get_cache_stats()

        assert stats["total"] >= 2
        assert "stdlib" in stats["by_source"]

    def test_unknown_symbol_returns_none(self, temp_db: Path) -> None:
        """Should return None for unknown symbols."""
        lookup = APIDocumentationLookup(temp_db)

        doc = lookup.get_documentation("nonexistent_module.fake_function")

        assert doc is None

    def test_extract_symbols_regex_fallback(self, temp_db: Path) -> None:
        """Should fall back to regex for invalid Python code."""
        lookup = APIDocumentationLookup(temp_db)

        # Invalid Python but has import-like patterns
        code = """
import json
from pathlib import Path
this is not valid python {{{
"""

        symbols = lookup._extract_imports_regex(code)

        assert "json" in symbols
        assert "pathlib.Path" in symbols
