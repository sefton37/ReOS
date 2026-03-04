# ADR-0004: Self-Knowledge RAG System

**Status:** Accepted
**Date:** 2026-01-14
**Decision Makers:** ReOS Core Team

## Context

AI agents (CAIRN, RIVA) need to understand the ReOS codebase to:
- Answer questions about how features work
- Locate relevant code when implementing changes
- Understand architectural decisions

Full codebase in context is not feasible:
- ~85K lines of code
- ~737K tokens (exceeds context limits)

## Decision

We implemented a three-tier knowledge system:

### Tier 1: Architecture Blueprint (~8K tokens)

Always-available compressed documentation:
- `architecture/ARCHITECTURE.md`
- Contains: data models, component overview, tool index, file purposes
- Loaded into CAIRN context when needed

### Tier 2: RAG/Retrieval (~2-5K tokens per query)

On-demand code search:
- `architecture/code_index.py` - Indexer and search
- Extracts: functions, classes, methods, modules
- Keyword-based scoring (no vector embeddings needed)

### Tier 3: Full Source (retrieved on demand)

Direct file reading when specific code needed:
- Use existing Read tools
- Targeted retrieval after RAG identifies location

## Implementation

### Code Index

```python
class CodeEntity:
    entity_type: str      # function, class, module, method
    name: str             # Entity name
    qualified_name: str   # Full path
    file_path: str        # Location
    line_number: int
    signature: str        # Function/class signature
    docstring: str        # Extracted docstring
    keywords: list[str]   # For search matching
```

### Search Scoring

```python
def matches(self, query: str) -> float:
    # Exact name match: +1.0
    # Partial name match: +0.7
    # Qualified name match: +0.5
    # Keyword matches: +0.3 (proportional)
    # Docstring matches: +0.2
    # File path context: +0.1
```

### MCP Tools

| Tool | Purpose |
|------|---------|
| reos_search_codebase | Search for code by query |
| reos_get_architecture | Get full architecture doc |
| reos_file_summary | Get summary of a file |

## Consequences

### Positive
- Agents can understand codebase without huge context
- No vector DB or embeddings required
- Index rebuilds on demand (no stale data)
- Architecture doc provides consistent foundation

### Negative
- Keyword search less accurate than semantic search
- Index build time for large codebases
- Architecture doc requires manual updates

## Usage Pattern

```
1. User asks: "How does the intent engine work?"
2. CAIRN calls: reos_search_codebase(query="intent engine")
3. Results show: intent_engine.py functions and classes
4. CAIRN calls: reos_file_summary(file_path="src/reos/cairn/intent_engine.py")
5. Response generated from retrieved context
```
