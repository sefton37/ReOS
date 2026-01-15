# ADR-0002: CAIRN Intent Engine 4-Stage Pipeline

**Status:** Accepted
**Date:** 2026-01-14
**Decision Makers:** ReOS Core Team

## Context

CAIRN needed to understand natural language queries and map them to appropriate tools. The challenge was:

1. Avoid hallucination - responses must be grounded in actual data
2. Support fuzzy matching for entity names
3. Provide structured reasoning that can be debugged
4. Handle multiple categories (calendar, play, system, etc.)

## Decision

We implemented a 4-stage pipeline in `intent_engine.py`:

### Stage 1: Intent Extraction
- Fast path: Pattern matching against `INTENT_PATTERNS` dict
- Slow path: LLM extraction for complex cases
- Output: `ExtractedIntent` with category, action, target, confidence

### Stage 2: Intent Verification
- Check if we have a tool for this category
- Build tool arguments from natural language
- Support fuzzy matching for names (acts, beats, etc.)
- Output: `VerifiedIntent` with tool_name and tool_args

### Stage 3: Tool Execution
- Call the MCP tool with extracted arguments
- Handle errors gracefully
- Capture tool results for response generation

### Stage 4: Response Generation
- Generate response STRICTLY from tool results
- Run hallucination verification
- Template-based fallback for empty/error cases

## Categories and Default Tools

| Category | Default Tool | Refinement |
|----------|-------------|------------|
| CALENDAR | cairn_get_calendar | - |
| PLAY | cairn_list_acts | _select_play_tool() |
| SYSTEM | linux_system_info | - |
| CONTACTS | cairn_search_contacts | - |
| PERSONAL | None (context-based) | - |

## Consequences

### Positive
- Structured pipeline is debuggable and testable
- Pattern matching provides fast path for common queries
- Hallucination prevention built into the pipeline
- Fuzzy matching improves natural language UX

### Negative
- Multiple stages add latency
- Pattern maintenance required for new categories
- LLM verification adds cost for complex queries

## Implementation Files

- `cairn/intent_engine.py` - Main pipeline implementation
- `INTENT_PATTERNS` dict - Pattern matching keywords
- `CATEGORY_TOOLS` dict - Category to tool mapping
- `_select_play_tool()` - Tool selection for PLAY category
