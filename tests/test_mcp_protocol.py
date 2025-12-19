from __future__ import annotations

import pytest

from reos.db import get_db


def test_mcp_initialize_returns_capabilities(isolated_db_singleton) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(db, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert resp is not None
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_tools_list_returns_tools(isolated_db_singleton) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(db, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert resp is not None
    tools = resp["result"]["tools"]
    assert isinstance(tools, list)
    assert any(t["name"] == "reos_git_summary" for t in tools)


def test_mcp_tools_call_validates_params_object(isolated_db_singleton) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(
        db,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": "nope"},
    )

    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_tools_call_requires_name(isolated_db_singleton) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(
        db,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}},
    )

    assert resp is not None
    assert resp["error"]["code"] == -32602
    assert "name" in resp["error"]["message"].lower()


def test_mcp_tools_call_maps_tool_error(isolated_db_singleton, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()

    def boom(*_args, **_kwargs):
        from reos.mcp_tools import ToolError

        raise ToolError(code="invalid_args", message="bad args")

    monkeypatch.setattr(mcp, "call_tool", boom)

    resp = mcp._handle_jsonrpc_request(
        db,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "reos_repo_read_file", "arguments": {}},
        },
    )

    assert resp is not None
    assert resp["error"]["code"] == -32602
    assert "bad args" in resp["error"]["message"]


def test_mcp_unknown_method_returns_method_not_found(isolated_db_singleton) -> None:  # noqa: ANN001
    import reos.mcp_server as mcp

    db = get_db()
    resp = mcp._handle_jsonrpc_request(db, {"jsonrpc": "2.0", "id": 6, "method": "nope"})

    assert resp is not None
    assert resp["error"]["code"] == -32601
