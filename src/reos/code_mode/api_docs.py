"""API Documentation Lookup - Prevent hallucination by fetching real docs.

When Code Mode generates code, it should use real APIs correctly.
This module fetches and caches API documentation from multiple sources:
- Local: Project docstrings via RepoMap
- Stdlib: Python built-in modules via pydoc
- Third-party: PyPI package metadata (optional)

Documentation is cached in SQLite with TTL for fast repeated lookups.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import pydoc
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.repo_map import RepoMap

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class APIDocumentation:
    """Documentation for an API symbol.

    Stores essential information about a function, class, method, or module
    to help the LLM generate correct code.
    """

    name: str  # Fully qualified name, e.g., "pandas.read_csv"
    symbol_type: str  # "function", "class", "method", "module"
    language: str  # "python", "javascript", "typescript"
    signature: str | None  # Function signature if applicable
    summary: str  # One-line description
    parameters: list[dict[str, Any]] = field(default_factory=list)  # [{name, type, description}]
    returns: str | None = None  # Return type/description
    source: str = "unknown"  # "stdlib", "pypi", "local", "npm"
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "name": self.name,
            "symbol_type": self.symbol_type,
            "language": self.language,
            "signature": self.signature,
            "summary": self.summary,
            "parameters": self.parameters,
            "returns": self.returns,
            "source": self.source,
            "cached_at": self.cached_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APIDocumentation:
        """Create from dictionary."""
        cached_at = data.get("cached_at")
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at)
        elif cached_at is None:
            cached_at = datetime.now(timezone.utc)

        return cls(
            name=data["name"],
            symbol_type=data.get("symbol_type", "unknown"),
            language=data.get("language", "python"),
            signature=data.get("signature"),
            summary=data.get("summary", ""),
            parameters=data.get("parameters", []),
            returns=data.get("returns"),
            source=data.get("source", "unknown"),
            cached_at=cached_at,
        )

    def format_for_context(self) -> str:
        """Format documentation for LLM context."""
        parts = [f"**{self.name}**"]
        if self.signature:
            parts.append(f"`{self.signature}`")
        if self.summary:
            parts.append(self.summary)
        if self.parameters:
            params = ", ".join(
                f"{p.get('name', '?')}: {p.get('type', 'Any')}"
                for p in self.parameters[:5]
            )
            if params:
                parts.append(f"Parameters: {params}")
        if self.returns:
            parts.append(f"Returns: {self.returns}")
        return " - ".join(parts)


# =============================================================================
# API Documentation Lookup
# =============================================================================


class APIDocumentationLookup:
    """Fetch and cache API documentation to prevent hallucination.

    Checks multiple sources in order:
    1. SQLite cache (fastest)
    2. Local project symbols via RepoMap
    3. Python stdlib via pydoc
    4. Third-party packages via PyPI (optional, requires network)
    """

    def __init__(
        self,
        db_path: Path,
        repo_map: RepoMap | None = None,
        ttl_days: int = 30,
    ) -> None:
        """Initialize the documentation lookup.

        Args:
            db_path: Path to SQLite database for caching.
            repo_map: Optional RepoMap for local symbol lookup.
            ttl_days: Cache time-to-live in days.
        """
        self._db_path = db_path
        self._repo_map = repo_map
        self._ttl_days = ttl_days
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure the api_documentation table exists."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_documentation (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    symbol_type TEXT NOT NULL,
                    language TEXT NOT NULL,
                    signature TEXT,
                    summary TEXT NOT NULL,
                    parameters TEXT,
                    returns TEXT,
                    source TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    UNIQUE(name, language)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_doc_name
                ON api_documentation(name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_doc_language
                ON api_documentation(language)
            """)
            conn.commit()

    def get_documentation(
        self,
        symbol: str,
        language: str = "python",
    ) -> APIDocumentation | None:
        """Get documentation for a symbol, checking cache first.

        Args:
            symbol: Symbol name (e.g., "json.loads", "Path.exists")
            language: Programming language

        Returns:
            APIDocumentation if found, None otherwise.
        """
        # 1. Check cache first
        cached = self._fetch_from_cache(symbol, language)
        if cached:
            logger.debug("Cache hit for %s", symbol)
            return cached

        # 2. Try local project symbols
        if self._repo_map and language == "python":
            local_doc = self._fetch_from_local(symbol)
            if local_doc:
                self._cache_documentation(local_doc)
                return local_doc

        # 3. Try Python stdlib
        if language == "python":
            stdlib_doc = self._fetch_from_stdlib(symbol)
            if stdlib_doc:
                self._cache_documentation(stdlib_doc)
                return stdlib_doc

        logger.debug("No documentation found for %s", symbol)
        return None

    def get_documentation_batch(
        self,
        symbols: list[str],
        language: str = "python",
    ) -> list[APIDocumentation]:
        """Batch lookup for multiple symbols.

        Args:
            symbols: List of symbol names
            language: Programming language

        Returns:
            List of found APIDocumentation objects.
        """
        results = []
        for symbol in symbols[:20]:  # Limit to prevent overload
            doc = self.get_documentation(symbol, language)
            if doc:
                results.append(doc)
        return results

    def extract_symbols_from_code(self, code: str, language: str = "python") -> list[str]:
        """Extract API symbols from import statements.

        Args:
            code: Source code to analyze
            language: Programming language

        Returns:
            List of symbol names found in imports.
        """
        if language != "python":
            return []

        symbols = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        symbols.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        if module:
                            symbols.append(f"{module}.{alias.name}")
                        else:
                            symbols.append(alias.name)
        except SyntaxError:
            # Fall back to regex for partial/broken code
            symbols = self._extract_imports_regex(code)

        return list(set(symbols))

    def _extract_imports_regex(self, code: str) -> list[str]:
        """Extract imports using regex for broken code."""
        symbols = []

        # Match: import x, from x import y
        import_re = re.compile(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', re.MULTILINE)
        for match in import_re.finditer(code):
            from_module = match.group(1)
            imports = match.group(2)
            for imp in imports.split(','):
                imp = imp.strip().split(' as ')[0].strip()
                if from_module:
                    symbols.append(f"{from_module}.{imp}")
                else:
                    symbols.append(imp)

        return symbols

    def extract_symbols_from_prompt(self, prompt: str) -> list[str]:
        """Extract likely API references from natural language.

        Args:
            prompt: User's natural language prompt

        Returns:
            List of potential symbol names.
        """
        symbols = []

        # Common patterns: "use pandas", "with the json library", "pathlib.Path"
        patterns = [
            r'\b(pandas|numpy|requests|flask|django|fastapi|pytest|json|os|sys|pathlib|datetime|re|collections|itertools|functools|typing)\b',
            r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b',  # CamelCase class names
            r'`([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+)`',  # `module.function`
            r'(?:use|import|with)\s+(?:the\s+)?(\w+)\s+(?:library|module|package)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, prompt, re.IGNORECASE):
                symbol = match.group(1) if match.lastindex else match.group(0)
                if symbol and len(symbol) > 1:
                    symbols.append(symbol.lower())

        return list(set(symbols))

    # -------------------------------------------------------------------------
    # Private Fetchers
    # -------------------------------------------------------------------------

    def _fetch_from_cache(
        self,
        name: str,
        language: str,
    ) -> APIDocumentation | None:
        """Fetch documentation from SQLite cache."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT * FROM api_documentation
                    WHERE name = ? AND language = ?
                    """,
                    (name, language),
                )
                row = cursor.fetchone()
                if row:
                    # Check TTL
                    cached_at = datetime.fromisoformat(row["cached_at"])
                    age_days = (datetime.now(timezone.utc) - cached_at).days
                    if age_days > self._ttl_days:
                        # Expired, delete and return None
                        conn.execute(
                            "DELETE FROM api_documentation WHERE id = ?",
                            (row["id"],),
                        )
                        conn.commit()
                        return None

                    # Parse parameters JSON
                    params = []
                    if row["parameters"]:
                        try:
                            params = json.loads(row["parameters"])
                        except json.JSONDecodeError:
                            pass

                    return APIDocumentation(
                        name=row["name"],
                        symbol_type=row["symbol_type"],
                        language=row["language"],
                        signature=row["signature"],
                        summary=row["summary"],
                        parameters=params,
                        returns=row["returns"],
                        source=row["source"],
                        cached_at=cached_at,
                    )
        except sqlite3.Error as e:
            logger.warning("Cache lookup failed: %s", e)
        return None

    def _fetch_from_local(self, symbol: str) -> APIDocumentation | None:
        """Fetch documentation from local project via RepoMap."""
        if self._repo_map is None:
            return None

        try:
            # Search for symbol in repo map
            results = self._repo_map.find_symbols(symbol)
            if not results:
                return None

            # Get the first matching symbol
            sym = results[0]

            return APIDocumentation(
                name=sym.name,
                symbol_type=sym.kind.value if hasattr(sym.kind, 'value') else str(sym.kind),
                language="python",
                signature=sym.signature if hasattr(sym, 'signature') else None,
                summary=sym.docstring[:200] if hasattr(sym, 'docstring') and sym.docstring else "",
                source="local",
            )
        except Exception as e:
            logger.debug("Local lookup failed for %s: %s", symbol, e)
            return None

    def _fetch_from_stdlib(self, symbol: str) -> APIDocumentation | None:
        """Fetch documentation from Python stdlib using pydoc."""
        try:
            # Split symbol into module and attribute
            parts = symbol.split(".")
            module_name = parts[0]

            # Check if it's a stdlib module
            if module_name not in sys.stdlib_module_names:
                # Also check common third-party that might be installed
                if module_name not in ("json", "os", "sys", "re", "pathlib", "datetime",
                                       "collections", "itertools", "functools", "typing",
                                       "dataclasses", "enum", "abc", "contextlib"):
                    return None

            # Try to import and get the object
            try:
                obj = pydoc.locate(symbol)
                if obj is None:
                    # Try just the module
                    obj = pydoc.locate(module_name)
                    if obj is None:
                        return None
            except Exception:
                return None

            # Get documentation
            doc = inspect.getdoc(obj) or ""
            summary = doc.split("\n")[0] if doc else ""

            # Determine symbol type
            if inspect.ismodule(obj):
                symbol_type = "module"
                signature = None
            elif inspect.isclass(obj):
                symbol_type = "class"
                try:
                    signature = f"{symbol}{inspect.signature(obj.__init__)}"
                except (ValueError, TypeError):
                    signature = symbol
            elif inspect.isfunction(obj) or inspect.ismethod(obj):
                symbol_type = "function"
                try:
                    signature = f"{symbol}{inspect.signature(obj)}"
                except (ValueError, TypeError):
                    signature = f"{symbol}(...)"
            elif inspect.isbuiltin(obj):
                symbol_type = "function"
                signature = f"{symbol}(...)"
            else:
                symbol_type = "other"
                signature = None

            # Extract parameters for functions
            parameters = []
            if symbol_type in ("function", "class"):
                try:
                    sig = inspect.signature(obj if symbol_type == "function" else obj.__init__)
                    for name, param in sig.parameters.items():
                        if name == "self":
                            continue
                        param_info = {"name": name}
                        if param.annotation != inspect.Parameter.empty:
                            param_info["type"] = str(param.annotation)
                        if param.default != inspect.Parameter.empty:
                            param_info["default"] = repr(param.default)
                        parameters.append(param_info)
                except (ValueError, TypeError):
                    pass

            # Get return type
            returns = None
            if symbol_type == "function":
                try:
                    sig = inspect.signature(obj)
                    if sig.return_annotation != inspect.Signature.empty:
                        returns = str(sig.return_annotation)
                except (ValueError, TypeError):
                    pass

            return APIDocumentation(
                name=symbol,
                symbol_type=symbol_type,
                language="python",
                signature=signature,
                summary=summary[:500],
                parameters=parameters,
                returns=returns,
                source="stdlib",
            )

        except Exception as e:
            logger.debug("Stdlib lookup failed for %s: %s", symbol, e)
            return None

    def _cache_documentation(self, doc: APIDocumentation) -> None:
        """Cache documentation in SQLite."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_documentation
                    (name, symbol_type, language, signature, summary, parameters, returns, source, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.name,
                        doc.symbol_type,
                        doc.language,
                        doc.signature,
                        doc.summary,
                        json.dumps(doc.parameters) if doc.parameters else None,
                        doc.returns,
                        doc.source,
                        doc.cached_at.isoformat(),
                    ),
                )
                conn.commit()
                logger.debug("Cached documentation for %s", doc.name)
        except sqlite3.Error as e:
            logger.warning("Failed to cache documentation: %s", e)

    def clear_cache(self) -> int:
        """Clear all cached documentation.

        Returns:
            Number of entries deleted.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute("DELETE FROM api_documentation")
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error:
            return 0

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM api_documentation")
                total = cursor.fetchone()[0]

                cursor = conn.execute(
                    "SELECT source, COUNT(*) FROM api_documentation GROUP BY source"
                )
                by_source = dict(cursor.fetchall())

                return {"total": total, "by_source": by_source}
        except sqlite3.Error:
            return {"total": 0, "by_source": {}}
