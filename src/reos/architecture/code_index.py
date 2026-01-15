"""Code Index and RAG System for ReOS Self-Knowledge.

This module provides:
1. Code indexing - Extracts functions, classes, and docstrings from the codebase
2. Semantic search - Finds relevant code based on natural language queries
3. Context retrieval - Returns appropriate code snippets for AI context

The index is lightweight and regenerated on demand, avoiding the need for
vector embeddings while still providing useful code retrieval.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

# Root of the ReOS codebase
REOS_ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class CodeEntity:
    """A searchable code entity (function, class, or module)."""

    entity_type: str          # "function", "class", "module"
    name: str                 # Entity name
    qualified_name: str       # Full path (module.class.function)
    file_path: str            # Relative path from REOS_ROOT
    line_number: int          # Starting line
    signature: str            # Function signature or class definition
    docstring: str            # Extracted docstring
    keywords: list[str]       # Extracted keywords for search

    def matches(self, query: str) -> float:
        """Score how well this entity matches a search query.

        Returns a score from 0-1, higher = better match.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        score = 0.0

        # Exact name match (highest priority)
        if query_lower == self.name.lower():
            score += 1.0
        elif query_lower in self.name.lower():
            score += 0.7

        # Qualified name match
        if query_lower in self.qualified_name.lower():
            score += 0.5

        # Keyword matches
        keyword_matches = sum(1 for kw in self.keywords if kw in query_lower)
        if self.keywords:
            score += 0.3 * (keyword_matches / len(self.keywords))

        # Docstring word matches
        if self.docstring:
            doc_lower = self.docstring.lower()
            doc_word_matches = sum(1 for w in query_words if w in doc_lower)
            score += 0.2 * (doc_word_matches / max(len(query_words), 1))

        # File path context
        if any(w in self.file_path.lower() for w in query_words):
            score += 0.1

        return min(score, 1.0)


class CodeIndexer:
    """Indexes Python code for searchable retrieval."""

    def __init__(self, root: Path | None = None):
        self.root = root or REOS_ROOT
        self._index: list[CodeEntity] = []
        self._indexed = False

    def build_index(self, force: bool = False) -> None:
        """Build or rebuild the code index."""
        if self._indexed and not force:
            return

        self._index = []

        # Index Python files in src/reos
        python_root = self.root / "src" / "reos"
        if python_root.exists():
            for py_file in python_root.rglob("*.py"):
                self._index_python_file(py_file)

        # Index TypeScript files in apps/reos-tauri/src
        ts_root = self.root / "apps" / "reos-tauri" / "src"
        if ts_root.exists():
            for ts_file in ts_root.rglob("*.ts"):
                self._index_typescript_file(ts_file)

        self._indexed = True

    def _index_python_file(self, file_path: Path) -> None:
        """Index a single Python file."""
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            return

        rel_path = str(file_path.relative_to(self.root))
        module_name = rel_path.replace("/", ".").replace(".py", "")

        # Module-level docstring
        module_doc = ast.get_docstring(tree) or ""
        if module_doc:
            self._index.append(CodeEntity(
                entity_type="module",
                name=file_path.stem,
                qualified_name=module_name,
                file_path=rel_path,
                line_number=1,
                signature=f"# {file_path.name}",
                docstring=module_doc[:500],  # Truncate long docstrings
                keywords=self._extract_keywords(module_doc),
            ))

        # Functions and classes
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self._index_function(node, module_name, rel_path, content)
            elif isinstance(node, ast.ClassDef):
                self._index_class(node, module_name, rel_path, content)

    def _index_function(
        self,
        node: ast.FunctionDef,
        module_name: str,
        file_path: str,
        content: str,
    ) -> None:
        """Index a function definition."""
        docstring = ast.get_docstring(node) or ""

        # Build signature
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)

        returns = ""
        if node.returns:
            returns = f" -> {ast.unparse(node.returns)}"

        signature = f"def {node.name}({', '.join(args)}){returns}"

        self._index.append(CodeEntity(
            entity_type="function",
            name=node.name,
            qualified_name=f"{module_name}.{node.name}",
            file_path=file_path,
            line_number=node.lineno,
            signature=signature,
            docstring=docstring[:500],
            keywords=self._extract_keywords(f"{node.name} {docstring}"),
        ))

    def _index_class(
        self,
        node: ast.ClassDef,
        module_name: str,
        file_path: str,
        content: str,
    ) -> None:
        """Index a class definition."""
        docstring = ast.get_docstring(node) or ""

        # Build signature with bases
        bases = [ast.unparse(b) for b in node.bases]
        bases_str = f"({', '.join(bases)})" if bases else ""
        signature = f"class {node.name}{bases_str}"

        self._index.append(CodeEntity(
            entity_type="class",
            name=node.name,
            qualified_name=f"{module_name}.{node.name}",
            file_path=file_path,
            line_number=node.lineno,
            signature=signature,
            docstring=docstring[:500],
            keywords=self._extract_keywords(f"{node.name} {docstring}"),
        ))

        # Index methods
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_doc = ast.get_docstring(item) or ""
                args = [a.arg for a in item.args.args]
                signature = f"def {item.name}({', '.join(args)})"

                self._index.append(CodeEntity(
                    entity_type="method",
                    name=item.name,
                    qualified_name=f"{module_name}.{node.name}.{item.name}",
                    file_path=file_path,
                    line_number=item.lineno,
                    signature=signature,
                    docstring=method_doc[:300],
                    keywords=self._extract_keywords(f"{item.name} {method_doc}"),
                ))

    def _index_typescript_file(self, file_path: Path) -> None:
        """Index a TypeScript file using regex (lightweight, no full parser)."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return

        rel_path = str(file_path.relative_to(self.root))
        module_name = rel_path.replace("/", ".").replace(".ts", "")

        # Extract functions
        func_pattern = r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)[^{]*'
        for match in re.finditer(func_pattern, content):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1

            self._index.append(CodeEntity(
                entity_type="function",
                name=name,
                qualified_name=f"{module_name}.{name}",
                file_path=rel_path,
                line_number=line_num,
                signature=match.group(0).strip(),
                docstring="",
                keywords=[name.lower()],
            ))

        # Extract interfaces/types
        type_pattern = r'(?:export\s+)?(?:interface|type)\s+(\w+)'
        for match in re.finditer(type_pattern, content):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1

            self._index.append(CodeEntity(
                entity_type="type",
                name=name,
                qualified_name=f"{module_name}.{name}",
                file_path=rel_path,
                line_number=line_num,
                signature=match.group(0).strip(),
                docstring="",
                keywords=[name.lower()],
            ))

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract searchable keywords from text."""
        # Common words to exclude
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once",
            "and", "but", "or", "nor", "so", "yet", "both", "either",
            "neither", "not", "only", "own", "same", "than", "too",
            "very", "just", "also", "now", "here", "there", "when",
            "where", "why", "how", "all", "each", "every", "both",
            "few", "more", "most", "other", "some", "such", "no",
            "any", "self", "none", "true", "false", "return", "returns",
            "args", "kwargs", "param", "params", "this", "that",
        }

        # Extract words
        words = re.findall(r'\b[a-z][a-z_]+\b', text.lower())

        # Filter and dedupe
        keywords = []
        seen = set()
        for word in words:
            if word not in stopwords and word not in seen and len(word) > 2:
                keywords.append(word)
                seen.add(word)

        return keywords[:20]  # Limit keywords per entity

    def search(
        self,
        query: str,
        limit: int = 10,
        entity_types: list[str] | None = None,
    ) -> list[CodeEntity]:
        """Search the index for entities matching the query.

        Args:
            query: Natural language search query
            limit: Maximum results to return
            entity_types: Filter by type (function, class, module, etc.)

        Returns:
            List of matching CodeEntity objects, sorted by relevance
        """
        self.build_index()

        results = []
        for entity in self._index:
            if entity_types and entity.entity_type not in entity_types:
                continue

            score = entity.matches(query)
            if score > 0.1:  # Minimum relevance threshold
                results.append((score, entity))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        return [entity for _, entity in results[:limit]]

    def get_context(
        self,
        query: str,
        max_tokens: int = 2000,
    ) -> str:
        """Get context-appropriate code snippets for a query.

        Returns formatted text suitable for inclusion in AI context.
        """
        results = self.search(query, limit=10)

        if not results:
            return f"No code found matching: {query}"

        lines = [f"## Code relevant to: {query}\n"]
        token_estimate = 20  # Header tokens

        for entity in results:
            # Estimate tokens (rough: 4 chars per token)
            entry_tokens = (len(entity.signature) + len(entity.docstring)) // 4 + 20

            if token_estimate + entry_tokens > max_tokens:
                break

            lines.append(f"### {entity.entity_type}: `{entity.qualified_name}`")
            lines.append(f"File: `{entity.file_path}:{entity.line_number}`")
            lines.append(f"```python\n{entity.signature}\n```")
            if entity.docstring:
                lines.append(f"> {entity.docstring[:200]}...")
            lines.append("")

            token_estimate += entry_tokens

        return "\n".join(lines)

    def get_file_summary(self, file_path: str) -> str:
        """Get a summary of a specific file's contents."""
        self.build_index()

        entities = [e for e in self._index if e.file_path == file_path]

        if not entities:
            return f"No index entries for: {file_path}"

        lines = [f"## Summary of `{file_path}`\n"]

        # Group by type
        by_type: dict[str, list[CodeEntity]] = {}
        for e in entities:
            by_type.setdefault(e.entity_type, []).append(e)

        for etype, ents in sorted(by_type.items()):
            lines.append(f"### {etype.title()}s ({len(ents)})")
            for e in ents[:10]:  # Limit per type
                lines.append(f"- `{e.name}` (line {e.line_number})")
                if e.docstring:
                    first_line = e.docstring.split('\n')[0][:80]
                    lines.append(f"  {first_line}")
            if len(ents) > 10:
                lines.append(f"  ... and {len(ents) - 10} more")
            lines.append("")

        return "\n".join(lines)

    def export_index(self, output_path: Path | None = None) -> Path:
        """Export the index to a JSON file for caching."""
        self.build_index()

        if output_path is None:
            output_path = self.root / "src" / "reos" / "architecture" / "code_index.json"

        data = [asdict(e) for e in self._index]
        output_path.write_text(json.dumps(data, indent=2))

        return output_path

    def import_index(self, input_path: Path) -> None:
        """Import index from a JSON file."""
        if not input_path.exists():
            return

        data = json.loads(input_path.read_text())
        self._index = [CodeEntity(**d) for d in data]
        self._indexed = True


# Singleton indexer instance
_indexer: CodeIndexer | None = None


def get_indexer() -> CodeIndexer:
    """Get or create the singleton code indexer."""
    global _indexer
    if _indexer is None:
        _indexer = CodeIndexer()
    return _indexer


def search_codebase(query: str, limit: int = 10) -> list[CodeEntity]:
    """Search the ReOS codebase for relevant code.

    Args:
        query: Natural language search query
        limit: Maximum results

    Returns:
        List of matching code entities
    """
    return get_indexer().search(query, limit)


def get_code_context(query: str, max_tokens: int = 2000) -> str:
    """Get code context for an AI query.

    Returns formatted text with relevant code snippets.
    """
    return get_indexer().get_context(query, max_tokens)
