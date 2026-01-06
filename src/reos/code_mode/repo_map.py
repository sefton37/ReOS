"""Repository Map - Semantic code understanding for Code Mode.

Provides a searchable index of code symbols, dependencies, and embeddings
for intelligent context selection and code navigation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reos.code_mode.dependency_graph import DependencyGraphBuilder
from reos.code_mode.symbol_extractor import (
    FileNode,
    Location,
    Symbol,
    SymbolExtractor,
    SymbolKind,
    compute_file_hash,
)

if TYPE_CHECKING:
    from reos.code_mode.sandbox import CodeSandbox
    from reos.db import Database


@dataclass
class IndexResult:
    """Result of indexing operation."""

    total_files: int
    indexed: int
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_files": self.total_files,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "errors": self.errors,
        }


@dataclass
class FileContext:
    """Context information for a file."""

    file_path: str
    symbols: list[Symbol]
    imports: list[str]
    imported_by: list[str]
    dependencies: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "file_path": self.file_path,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": self.imports,
            "imported_by": self.imported_by,
            "dependencies": self.dependencies,
        }


class RepoMap:
    """Repository semantic map for Code Mode.

    Provides:
    - Symbol extraction and indexing
    - Dependency graph building
    - Symbol search and navigation
    - Smart context selection for LLM prompts
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        db: Database,
    ):
        """Initialize RepoMap.

        Args:
            sandbox: Code sandbox for file access
            db: Database for persistence
        """
        self.sandbox = sandbox
        self.db = db
        self.repo_path = str(sandbox.repo_path)
        self.symbol_extractor = SymbolExtractor()
        self.dep_builder = DependencyGraphBuilder(sandbox.repo_path)

    def index_repo(self, force: bool = False) -> IndexResult:
        """Index or re-index the repository.

        Args:
            force: If True, re-index all files regardless of hash

        Returns:
            IndexResult with statistics
        """
        files = self.sandbox.find_files("**/*.py")
        result = IndexResult(total_files=len(files), indexed=0)

        for file_path in files:
            try:
                if force or self._needs_reindex(file_path):
                    self._index_file(file_path)
                    result.indexed += 1
                else:
                    result.skipped += 1
            except Exception as e:
                result.errors.append(f"{file_path}: {e!s}")

        # After indexing all files, build dependency edges
        self._build_dependencies()

        return result

    def _needs_reindex(self, file_path: str) -> bool:
        """Check if a file needs re-indexing.

        Args:
            file_path: Relative file path

        Returns:
            True if file is new or changed
        """
        try:
            content = self.sandbox.read_file(file_path)
        except Exception:
            return False

        current_hash = compute_file_hash(content)

        # Check database for existing hash
        conn = self.db.connect()
        row = conn.execute(
            """
            SELECT sha256 FROM repo_map_files
            WHERE repo_path = ? AND file_path = ?
            """,
            (self.repo_path, file_path),
        ).fetchone()

        if row is None:
            return True

        stored_hash = row["sha256"] if hasattr(row, "__getitem__") else row[0]
        return stored_hash != current_hash

    def _index_file(self, file_path: str) -> None:
        """Index a single file.

        Args:
            file_path: Relative file path
        """
        content = self.sandbox.read_file(file_path)
        file_node = self.symbol_extractor.extract_file_node(file_path, content)
        now = datetime.now(UTC).isoformat()

        conn = self.db.connect()

        # Upsert file record
        conn.execute(
            """
            INSERT INTO repo_map_files (repo_path, file_path, language, sha256, indexed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo_path, file_path) DO UPDATE SET
                language = excluded.language,
                sha256 = excluded.sha256,
                indexed_at = excluded.indexed_at
            """,
            (self.repo_path, file_path, file_node.language, file_node.sha256, now),
        )

        # Get file ID
        file_row = conn.execute(
            "SELECT id FROM repo_map_files WHERE repo_path = ? AND file_path = ?",
            (self.repo_path, file_path),
        ).fetchone()
        file_id = file_row["id"] if hasattr(file_row, "__getitem__") else file_row[0]

        # Delete existing symbols for this file
        conn.execute("DELETE FROM repo_symbols WHERE file_id = ?", (file_id,))

        # Insert symbols
        for symbol in file_node.symbols:
            decorators_json = json.dumps(symbol.decorators) if symbol.decorators else None
            conn.execute(
                """
                INSERT INTO repo_symbols
                (file_id, name, kind, line_start, line_end, column_start, column_end,
                 parent, signature, docstring, decorators)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    symbol.name,
                    symbol.kind.value,
                    symbol.location.line_start,
                    symbol.location.line_end,
                    symbol.location.column_start,
                    symbol.location.column_end,
                    symbol.parent,
                    symbol.signature,
                    symbol.docstring,
                    decorators_json,
                ),
            )

        conn.commit()

    def _build_dependencies(self) -> None:
        """Build dependency edges between indexed files."""
        conn = self.db.connect()

        # Get all indexed files for this repo
        files = conn.execute(
            "SELECT id, file_path FROM repo_map_files WHERE repo_path = ?",
            (self.repo_path,),
        ).fetchall()

        file_id_map = {row["file_path"]: row["id"] for row in files}

        # Clear existing dependencies for this repo
        file_ids = list(file_id_map.values())
        if file_ids:
            placeholders = ",".join("?" * len(file_ids))
            conn.execute(
                f"DELETE FROM repo_dependencies WHERE from_file_id IN ({placeholders})",
                file_ids,
            )

        # Build new dependencies
        for file_path, file_id in file_id_map.items():
            try:
                content = self.sandbox.read_file(file_path)
                deps = self.dep_builder.get_dependencies(file_path, content)

                for target_file, symbols in deps:
                    if target_file in file_id_map:
                        symbols_json = json.dumps(symbols) if symbols else None
                        conn.execute(
                            """
                            INSERT INTO repo_dependencies
                            (from_file_id, to_file_id, import_type, symbols)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                file_id,
                                file_id_map[target_file],
                                "import",
                                symbols_json,
                            ),
                        )
            except Exception:
                # Skip files that can't be read
                pass

        conn.commit()

    def find_symbol(self, name: str, kind: str | None = None) -> list[Symbol]:
        """Find all symbols matching name.

        Args:
            name: Symbol name to search for
            kind: Optional kind filter (function, class, method, etc.)

        Returns:
            List of matching symbols
        """
        conn = self.db.connect()

        query = """
            SELECT s.*, f.file_path
            FROM repo_symbols s
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ? AND s.name LIKE ?
        """
        params: list[Any] = [self.repo_path, f"%{name}%"]

        if kind:
            query += " AND s.kind = ?"
            params.append(kind)

        query += " ORDER BY s.name"

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_symbol(row) for row in rows]

    def find_symbol_exact(self, name: str) -> list[Symbol]:
        """Find symbols with exact name match.

        Args:
            name: Exact symbol name

        Returns:
            List of matching symbols
        """
        conn = self.db.connect()

        rows = conn.execute(
            """
            SELECT s.*, f.file_path
            FROM repo_symbols s
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ? AND s.name = ?
            ORDER BY s.name
            """,
            (self.repo_path, name),
        ).fetchall()

        return [self._row_to_symbol(row) for row in rows]

    def find_callers(self, symbol_name: str, file_path: str) -> list[Location]:
        """Find all locations that import/call a symbol.

        This uses the dependency graph to find files that import the target,
        then searches for usage of the symbol name in those files.

        Args:
            symbol_name: Name of the symbol to find callers for
            file_path: File containing the symbol

        Returns:
            List of locations where the symbol is used
        """
        conn = self.db.connect()

        # Get file ID
        file_row = conn.execute(
            "SELECT id FROM repo_map_files WHERE repo_path = ? AND file_path = ?",
            (self.repo_path, file_path),
        ).fetchone()

        if not file_row:
            return []

        file_id = file_row["id"] if hasattr(file_row, "__getitem__") else file_row[0]

        # Find files that depend on this file
        rows = conn.execute(
            """
            SELECT f.file_path
            FROM repo_dependencies d
            JOIN repo_map_files f ON d.from_file_id = f.id
            WHERE d.to_file_id = ?
            """,
            (file_id,),
        ).fetchall()

        callers: list[Location] = []
        for row in rows:
            dependent_path = row["file_path"]
            try:
                content = self.sandbox.read_file(dependent_path)
                # Simple text search for the symbol name
                for i, line in enumerate(content.splitlines(), 1):
                    if symbol_name in line:
                        callers.append(
                            Location(
                                file_path=dependent_path,
                                line_start=i,
                                line_end=i,
                            )
                        )
            except Exception:
                pass

        return callers

    def get_file_context(self, file_path: str) -> FileContext | None:
        """Get context information for a file.

        Args:
            file_path: Relative file path

        Returns:
            FileContext with symbols and dependencies, or None if not indexed
        """
        conn = self.db.connect()

        # Get file info
        file_row = conn.execute(
            "SELECT id FROM repo_map_files WHERE repo_path = ? AND file_path = ?",
            (self.repo_path, file_path),
        ).fetchone()

        if not file_row:
            return None

        file_id = file_row["id"] if hasattr(file_row, "__getitem__") else file_row[0]

        # Get symbols
        symbol_rows = conn.execute(
            """
            SELECT s.*, f.file_path
            FROM repo_symbols s
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE s.file_id = ?
            """,
            (file_id,),
        ).fetchall()
        symbols = [self._row_to_symbol(row) for row in symbol_rows]

        # Get dependencies (what this file imports)
        dep_rows = conn.execute(
            """
            SELECT f.file_path
            FROM repo_dependencies d
            JOIN repo_map_files f ON d.to_file_id = f.id
            WHERE d.from_file_id = ?
            """,
            (file_id,),
        ).fetchall()
        dependencies = [row["file_path"] for row in dep_rows]

        # Get reverse dependencies (what imports this file)
        imported_by_rows = conn.execute(
            """
            SELECT f.file_path
            FROM repo_dependencies d
            JOIN repo_map_files f ON d.from_file_id = f.id
            WHERE d.to_file_id = ?
            """,
            (file_id,),
        ).fetchall()
        imported_by = [row["file_path"] for row in imported_by_rows]

        # Get imports from source
        try:
            content = self.sandbox.read_file(file_path)
            imports = self.dep_builder.analyze_imports(content)
            import_modules = [i.module for i in imports if i.module]
        except Exception:
            import_modules = []

        return FileContext(
            file_path=file_path,
            symbols=symbols,
            imports=import_modules,
            imported_by=imported_by,
            dependencies=dependencies,
        )

    def get_relevant_context(
        self,
        query: str,
        token_budget: int = 800,
    ) -> str:
        """Build relevant context for an LLM prompt within token budget.

        Args:
            query: The user's query/request
            token_budget: Maximum tokens to use for context

        Returns:
            Formatted context string
        """
        # For now, use keyword matching to find relevant symbols
        # This will be enhanced with embeddings in the next phase
        keywords = self._extract_keywords(query)

        relevant_symbols: list[Symbol] = []
        for keyword in keywords:
            symbols = self.find_symbol(keyword)
            relevant_symbols.extend(symbols[:3])  # Limit per keyword

        # Remove duplicates while preserving order
        seen = set()
        unique_symbols = []
        for sym in relevant_symbols:
            key = (sym.name, sym.location.file_path)
            if key not in seen:
                seen.add(key)
                unique_symbols.append(sym)

        # Build context string
        context_parts = []
        estimated_tokens = 0

        for sym in unique_symbols[:10]:  # Max 10 symbols
            snippet = self._format_symbol_snippet(sym)
            tokens = len(snippet) // 4  # Rough token estimate

            if estimated_tokens + tokens > token_budget:
                break

            context_parts.append(snippet)
            estimated_tokens += tokens

        if not context_parts:
            return "No relevant code context found."

        return "\n\n".join(context_parts)

    def clear_index(self) -> None:
        """Clear all index data for this repository."""
        conn = self.db.connect()

        # Get file IDs
        rows = conn.execute(
            "SELECT id FROM repo_map_files WHERE repo_path = ?",
            (self.repo_path,),
        ).fetchall()
        file_ids = [row["id"] for row in rows]

        if file_ids:
            placeholders = ",".join("?" * len(file_ids))
            # Delete in order: embeddings, dependencies, symbols, files
            conn.execute(
                f"""
                DELETE FROM repo_embeddings
                WHERE symbol_id IN (
                    SELECT id FROM repo_symbols WHERE file_id IN ({placeholders})
                )
                """,
                file_ids,
            )
            conn.execute(
                f"DELETE FROM repo_dependencies WHERE from_file_id IN ({placeholders})",
                file_ids,
            )
            conn.execute(
                f"DELETE FROM repo_symbols WHERE file_id IN ({placeholders})",
                file_ids,
            )
            conn.execute(
                f"DELETE FROM repo_map_files WHERE id IN ({placeholders})",
                file_ids,
            )

        conn.commit()
        self.dep_builder.clear_cache()

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the index.

        Returns:
            Dict with counts of files, symbols, dependencies, embeddings
        """
        conn = self.db.connect()

        # Count files
        file_count = conn.execute(
            "SELECT COUNT(*) FROM repo_map_files WHERE repo_path = ?",
            (self.repo_path,),
        ).fetchone()[0]

        # Count symbols
        symbol_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM repo_symbols s
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ?
            """,
            (self.repo_path,),
        ).fetchone()[0]

        # Count dependencies
        dep_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM repo_dependencies d
            JOIN repo_map_files f ON d.from_file_id = f.id
            WHERE f.repo_path = ?
            """,
            (self.repo_path,),
        ).fetchone()[0]

        # Count embeddings
        embed_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM repo_embeddings e
            JOIN repo_symbols s ON e.symbol_id = s.id
            JOIN repo_map_files f ON s.file_id = f.id
            WHERE f.repo_path = ?
            """,
            (self.repo_path,),
        ).fetchone()[0]

        return {
            "files": file_count,
            "symbols": symbol_count,
            "dependencies": dep_count,
            "embeddings": embed_count,
        }

    def _row_to_symbol(self, row: Any) -> Symbol:
        """Convert a database row to a Symbol object."""
        decorators = []
        if row["decorators"]:
            try:
                decorators = json.loads(row["decorators"])
            except json.JSONDecodeError:
                pass

        return Symbol(
            name=row["name"],
            kind=SymbolKind(row["kind"]),
            location=Location(
                file_path=row["file_path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                column_start=row["column_start"] or 0,
                column_end=row["column_end"] or 0,
            ),
            parent=row["parent"],
            signature=row["signature"],
            docstring=row["docstring"],
            decorators=decorators,
        )

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract potential symbol names from a query.

        Args:
            query: User's query text

        Returns:
            List of potential keywords
        """
        # Simple tokenization - split on spaces and punctuation
        import re

        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", query)

        # Filter out common words
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "but",
            "and",
            "or",
            "if",
            "because",
            "until",
            "while",
            "although",
            "though",
            "this",
            "that",
            "these",
            "those",
            "what",
            "which",
            "who",
            "whom",
            "whose",
            "i",
            "me",
            "my",
            "myself",
            "we",
            "our",
            "ours",
            "ourselves",
            "you",
            "your",
            "yours",
            "yourself",
            "he",
            "him",
            "his",
            "himself",
            "she",
            "her",
            "hers",
            "herself",
            "it",
            "its",
            "itself",
            "they",
            "them",
            "their",
            "theirs",
            "themselves",
            "find",
            "show",
            "get",
            "make",
            "add",
            "create",
            "update",
            "delete",
            "remove",
            "fix",
            "change",
            "modify",
            "implement",
            "code",
            "function",
            "class",
            "method",
            "file",
        }

        return [w for w in words if w.lower() not in stopwords and len(w) > 2]

    def _format_symbol_snippet(self, symbol: Symbol) -> str:
        """Format a symbol as a context snippet.

        Args:
            symbol: Symbol to format

        Returns:
            Formatted string
        """
        lines = [f"# {symbol.location.file_path}:{symbol.location.line_start}"]

        if symbol.signature:
            lines.append(symbol.signature)
        else:
            lines.append(f"{symbol.kind.value} {symbol.name}")

        if symbol.docstring:
            # Truncate long docstrings
            doc = symbol.docstring[:200]
            if len(symbol.docstring) > 200:
                doc += "..."
            lines.append(f'    """{doc}"""')

        return "\n".join(lines)
