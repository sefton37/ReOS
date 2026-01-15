# ADR-0003: MCP Tools Architecture

**Status:** Accepted
**Date:** 2026-01-14
**Decision Makers:** ReOS Core Team

## Context

We needed a standardized way for AI agents to interact with the system:
- Execute system commands safely
- Access calendar, contacts, knowledge
- Manage The Play hierarchy
- Search and understand the codebase

## Decision

We implemented an MCP (Model Context Protocol) compatible tool system:

### Tool Registration (`list_tools()`)

All tools registered in `mcp_tools.py:list_tools()`:

```python
def list_tools() -> list[Tool]:
    # Returns all available tools based on settings
    # Categories:
    # - Linux System Tools (always available)
    # - Git/Repo Tools (if git_integration_enabled)
    # - CAIRN Tools (knowledge, calendar, Play CRUD)
    # - Self-Knowledge Tools (codebase RAG)
```

### Tool Routing (`call_tool()`)

Prefix-based routing in `mcp_tools.py:call_tool()`:

| Prefix | Handler |
|--------|---------|
| `linux_*` | Direct handlers in mcp_tools.py |
| `reos_*` | Git/repo handlers OR self-knowledge handlers |
| `cairn_*` | `CairnToolHandler` in cairn/mcp_tools.py |

### Tool Schema

Each tool has:
- `name`: Unique identifier
- `description`: Human-readable description (for LLM)
- `input_schema`: JSON Schema for arguments

### CAIRN Tools (14 Play CRUD tools)

| Tool | Purpose |
|------|---------|
| cairn_list_acts | List Acts |
| cairn_create_act | Create Act |
| cairn_update_act | Rename Act |
| cairn_delete_act | Delete Act (protected: Your Story) |
| cairn_list_scenes | List Scenes in Act |
| cairn_create_scene | Create Scene |
| cairn_delete_scene | Delete Scene (protected: Stage Direction) |
| cairn_list_beats | List Beats |
| cairn_create_beat | Create Beat |
| cairn_update_beat | Update Beat |
| cairn_delete_beat | Delete Beat |
| cairn_move_beat_to_act | Move Beat between Acts |

## Consequences

### Positive
- Standardized interface for all tools
- LLM can understand tools from descriptions
- Prefix routing keeps handlers organized
- Settings can enable/disable tool categories

### Negative
- All tools must be registered in list_tools()
- Tool discovery requires code changes
- No dynamic tool loading

## Adding New Tools

1. Add Tool definition in `list_tools()`
2. Add handler in `call_tool()` (or appropriate handler file)
3. If CAIRN tool: Add to `CairnToolHandler.call_tool()`
4. Add intent pattern if natural language support needed
