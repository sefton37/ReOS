from __future__ import annotations

from reos.db import get_db


def test_projects_list_clears_unknown_active_project(isolated_db_singleton: object) -> None:
    db = get_db()
    db.set_active_project_id(project_id="ghost-project")

    import reos.ui_rpc_server as ui

    resp = ui._handle_jsonrpc_request(db, {"jsonrpc": "2.0", "id": 1, "method": "projects/list"})
    assert resp is not None
    assert "result" in resp

    result = resp["result"]
    assert isinstance(result, dict)
    assert result.get("projects") == []
    assert result.get("active_project_id") is None

    # Ensure it was actually cleared in DB.
    assert db.get_active_project_id() is None
