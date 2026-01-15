"""ReOS Architecture and Self-Knowledge System.

This module provides:
1. Architecture documentation loading
2. Code indexing and RAG search
3. ADR (Architecture Decision Record) access

Usage:
    from reos.architecture import get_architecture_context, search_codebase

    # Get compressed architecture for AI context
    context = get_architecture_context()

    # Search codebase for relevant code
    results = search_codebase("intent engine")
"""

from pathlib import Path
from typing import Optional

# Re-export from code_index
from .code_index import (
    CodeEntity,
    CodeIndexer,
    get_indexer,
    search_codebase,
    get_code_context,
)

ARCHITECTURE_DIR = Path(__file__).parent
ARCHITECTURE_FILE = ARCHITECTURE_DIR / "ARCHITECTURE.md"
ADR_DIR = ARCHITECTURE_DIR / "adrs"


def get_architecture_context(max_tokens: int = 8000) -> str:
    """Get the architecture blueprint for AI context.

    Returns the compressed architecture documentation suitable
    for inclusion in AI agent context.

    Args:
        max_tokens: Maximum estimated tokens (default 8000)

    Returns:
        Architecture documentation string
    """
    if not ARCHITECTURE_FILE.exists():
        return "Architecture documentation not found."

    content = ARCHITECTURE_FILE.read_text(encoding="utf-8")

    # Rough token estimate (4 chars per token)
    estimated_tokens = len(content) // 4

    if estimated_tokens > max_tokens:
        # Truncate to fit (leave room for truncation message)
        max_chars = (max_tokens - 100) * 4
        content = content[:max_chars] + "\n\n... (truncated for context limits)"

    return content


def get_adr_list() -> list[dict]:
    """Get list of all ADRs.

    Returns:
        List of dicts with 'id', 'title', 'status', 'file' keys
    """
    if not ADR_DIR.exists():
        return []

    adrs = []
    for adr_file in sorted(ADR_DIR.glob("*.md")):
        content = adr_file.read_text(encoding="utf-8")

        # Parse title from first heading
        title = "Unknown"
        status = "Unknown"

        for line in content.split("\n"):
            if line.startswith("# ADR-"):
                title = line[2:].strip()
            elif line.startswith("**Status:**"):
                status = line.replace("**Status:**", "").strip()
                break

        # Extract ID from filename
        adr_id = adr_file.stem.split("-")[0]

        adrs.append({
            "id": adr_id,
            "title": title,
            "status": status,
            "file": str(adr_file.relative_to(ARCHITECTURE_DIR.parent.parent)),
        })

    return adrs


def get_adr(adr_id: str) -> Optional[str]:
    """Get content of a specific ADR.

    Args:
        adr_id: ADR identifier (e.g., "0001")

    Returns:
        ADR content or None if not found
    """
    if not ADR_DIR.exists():
        return None

    for adr_file in ADR_DIR.glob(f"{adr_id}*.md"):
        return adr_file.read_text(encoding="utf-8")

    return None


def get_full_self_knowledge() -> str:
    """Get comprehensive self-knowledge for AI context.

    Combines:
    1. Architecture blueprint
    2. ADR summaries
    3. Recent code index stats

    Returns:
        Combined knowledge string
    """
    parts = []

    # Architecture
    arch = get_architecture_context(max_tokens=6000)
    parts.append(arch)

    # ADR summary
    adrs = get_adr_list()
    if adrs:
        parts.append("\n## Architecture Decision Records\n")
        for adr in adrs:
            parts.append(f"- **{adr['id']}**: {adr['title']} ({adr['status']})")
        parts.append("")

    # Index stats
    try:
        indexer = get_indexer()
        indexer.build_index()
        stats = {
            "functions": len([e for e in indexer._index if e.entity_type == "function"]),
            "classes": len([e for e in indexer._index if e.entity_type == "class"]),
            "modules": len([e for e in indexer._index if e.entity_type == "module"]),
        }
        parts.append(f"\n## Codebase Stats")
        parts.append(f"- Functions indexed: {stats['functions']}")
        parts.append(f"- Classes indexed: {stats['classes']}")
        parts.append(f"- Modules indexed: {stats['modules']}")
    except Exception:
        pass

    return "\n".join(parts)


__all__ = [
    "get_architecture_context",
    "get_adr_list",
    "get_adr",
    "get_full_self_knowledge",
    "search_codebase",
    "get_code_context",
    "CodeEntity",
    "CodeIndexer",
    "get_indexer",
]
