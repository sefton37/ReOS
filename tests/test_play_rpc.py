from __future__ import annotations


def _rpc(db: object, *, req_id: int, method: str, params: dict | None = None) -> dict:
    import reos.ui_rpc_server as ui

    req: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    resp = ui._handle_jsonrpc_request(db, req)
    assert resp is not None
    return resp


def test_play_rpc_me_and_acts_defaults(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    # Keep test data out of the repo-local `.reos-data/`.
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    me_resp = _rpc(db, req_id=1, method="play/me/read")
    assert "result" in me_resp
    assert "markdown" in me_resp["result"]
    assert "Me" in str(me_resp["result"]["markdown"])

    acts_resp = _rpc(db, req_id=2, method="play/acts/list")
    result = acts_resp["result"]
    assert result["acts"] == []
    assert result["active_act_id"] is None


def test_play_rpc_set_active_unknown_act_silently_ignored(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Setting an unknown act_id is silently ignored (no error, no act becomes active)."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    resp = _rpc(db, req_id=1, method="play/acts/set_active", params={"act_id": "does-not-exist"})
    # No error - silently ignored
    assert "result" in resp
    assert resp["result"]["active_act_id"] is None


def test_play_rpc_create_scene_and_kb_write_flow(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Test the 2-tier structure: Acts → Scenes (Scenes are todo/calendar items)."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create an Act
    create_act = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1", "notes": "n"})
    assert "result" in create_act
    act_id = create_act["result"]["created_act_id"]
    assert isinstance(act_id, str)
    # Note: Acts are not auto-activated on creation

    # Create a Scene (the todo/calendar item level)
    create_scene = _rpc(
        db,
        req_id=2,
        method="play/scenes/create",
        params={
            "act_id": act_id,
            "title": "Scene 1",
        },
    )
    scenes = create_scene["result"]["scenes"]
    assert len(scenes) == 1
    scene_id = scenes[0]["scene_id"]
    assert isinstance(scene_id, str)
    # Scenes have stage, notes, link fields
    assert "stage" in scenes[0]
    assert scenes[0]["stage"] == "planning"  # Default stage

    # Write to KB at scene level
    preview = _rpc(
        db,
        req_id=3,
        method="play/kb/write_preview",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "path": "kb.md",
            "text": "hello\n",
        },
    )["result"]
    assert "expected_sha256_current" in preview
    assert "sha256_new" in preview
    assert "diff" in preview

    applied = _rpc(
        db,
        req_id=4,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "path": "kb.md",
            "text": "hello\n",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )["result"]
    assert applied["sha256_current"] == preview["sha256_new"]

    read_back = _rpc(
        db,
        req_id=5,
        method="play/kb/read",
        params={"act_id": act_id, "scene_id": scene_id, "path": "kb.md"},
    )["result"]
    assert read_back["text"] == "hello\n"


def test_play_rpc_kb_rejects_path_traversal(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    act_id = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1"})["result"][
        "created_act_id"
    ]

    resp = _rpc(
        db,
        req_id=2,
        method="play/kb/write_preview",
        params={"act_id": act_id, "path": "../escape.md", "text": "nope"},
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_play_rpc_kb_apply_conflict_is_error(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    act_id = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Act 1"})["result"][
        "created_act_id"
    ]

    preview = _rpc(
        db,
        req_id=2,
        method="play/kb/write_preview",
        params={"act_id": act_id, "path": "kb.md", "text": "one"},
    )["result"]
    _rpc(
        db,
        req_id=3,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "path": "kb.md",
            "text": "one",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )

    conflict = _rpc(
        db,
        req_id=4,
        method="play/kb/write_apply",
        params={
            "act_id": act_id,
            "path": "kb.md",
            "text": "two",
            "expected_sha256_current": preview["expected_sha256_current"],
        },
    )
    assert "error" in conflict
    assert conflict["error"]["code"] == -32009


# =============================================================================
# RPC Error Handling Tests
# =============================================================================


def test_rpc_invalid_scene_id_returns_error(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Getting a scene with invalid ID returns error or null."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Try to get nonexistent scene
    resp = _rpc(
        db,
        req_id=1,
        method="play/scenes/get",
        params={"scene_id": "nonexistent-scene-id"},
    )

    # Should return error or null result
    if "result" in resp:
        assert resp["result"] is None or resp["result"].get("scene") is None
    else:
        assert "error" in resp


def test_rpc_invalid_stage_value_accepted(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Invalid stage value is accepted (free-form field for flexibility)."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act and scene
    act_resp = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Test Act"})
    act_id = act_resp["result"]["created_act_id"]

    scene_resp = _rpc(
        db,
        req_id=2,
        method="play/scenes/create",
        params={"act_id": act_id, "title": "Test Scene"},
    )
    scene_id = scene_resp["result"]["scenes"][0]["scene_id"]

    # Update with custom stage value (should be accepted)
    update_resp = _rpc(
        db,
        req_id=3,
        method="play/scenes/update",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "stage": "custom_stage",
        },
    )

    # Should succeed (stage is free-form)
    assert "result" in update_resp
    scenes = update_resp["result"]["scenes"]
    updated_scene = next((s for s in scenes if s["scene_id"] == scene_id), None)
    assert updated_scene is not None
    assert updated_scene["stage"] == "custom_stage"


def test_rpc_missing_required_params_returns_error(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Missing required parameters return appropriate error."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Try to create scene without act_id
    resp = _rpc(
        db,
        req_id=1,
        method="play/scenes/create",
        params={"title": "Orphan Scene"},  # Missing act_id
    )

    # Should return error for missing required param
    assert "error" in resp


def test_rpc_minimal_title_accepted(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Minimal title is accepted."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act with single character title
    resp = _rpc(db, req_id=1, method="play/acts/create", params={"title": "X"})

    # Should succeed
    assert "result" in resp
    assert "created_act_id" in resp["result"]


def test_rpc_unicode_in_title_and_notes(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Unicode characters in title and notes work correctly."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act with unicode
    unicode_title = "Project \u65e5\u672c\u8a9e \U0001f680"
    unicode_notes = "Notes with \u00e9\u00e0\u00fc\u00f1 and more"

    resp = _rpc(
        db,
        req_id=1,
        method="play/acts/create",
        params={"title": unicode_title, "notes": unicode_notes},
    )

    assert "result" in resp
    act_id = resp["result"]["created_act_id"]

    # Retrieve and verify
    list_resp = _rpc(db, req_id=2, method="play/acts/list")
    acts = list_resp["result"]["acts"]
    created_act = next((a for a in acts if a["act_id"] == act_id), None)

    assert created_act is not None
    assert created_act["title"] == unicode_title
    assert created_act["notes"] == unicode_notes


def test_rpc_create_multiple_scenes(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Creating multiple scenes in an act works correctly."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act
    act_resp = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Multi Scene Act"})
    act_id = act_resp["result"]["created_act_id"]

    # Create multiple scenes
    _rpc(db, req_id=2, method="play/scenes/create", params={"act_id": act_id, "title": "Scene 1"})
    _rpc(db, req_id=3, method="play/scenes/create", params={"act_id": act_id, "title": "Scene 2"})
    scene_resp = _rpc(db, req_id=4, method="play/scenes/create", params={"act_id": act_id, "title": "Scene 3"})

    # Should have 3 scenes
    scenes = scene_resp["result"]["scenes"]
    assert len(scenes) == 3
    titles = {s["title"] for s in scenes}
    assert titles == {"Scene 1", "Scene 2", "Scene 3"}


def test_rpc_update_scene_partial_params(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """Partial update only changes specified fields."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act and scene with all fields
    act_resp = _rpc(db, req_id=1, method="play/acts/create", params={"title": "Test Act"})
    act_id = act_resp["result"]["created_act_id"]

    scene_resp = _rpc(
        db,
        req_id=2,
        method="play/scenes/create",
        params={
            "act_id": act_id,
            "title": "Original Title",
        },
    )
    scene_id = scene_resp["result"]["scenes"][0]["scene_id"]

    # Update notes with specific text
    _rpc(
        db,
        req_id=3,
        method="play/scenes/update",
        params={"act_id": act_id, "scene_id": scene_id, "notes": "Original notes"},
    )

    # Partial update - only change title
    update_resp = _rpc(
        db,
        req_id=4,
        method="play/scenes/update",
        params={
            "act_id": act_id,
            "scene_id": scene_id,
            "title": "New Title",
            # Not specifying notes - should remain unchanged
        },
    )

    scenes = update_resp["result"]["scenes"]
    updated = next((s for s in scenes if s["scene_id"] == scene_id), None)

    assert updated is not None
    assert updated["title"] == "New Title"
    assert updated["notes"] == "Original notes"  # Unchanged


def test_rpc_list_all_scenes_returns_list(tmp_path, monkeypatch, isolated_db_singleton: object) -> None:
    """List all scenes returns a list."""
    monkeypatch.setenv("REOS_DATA_DIR", str(tmp_path / "data"))

    from reos.db import get_db

    db = get_db()

    # Create act and scene
    act_resp = _rpc(db, req_id=1, method="play/acts/create", params={"title": "List Test Act"})
    act_id = act_resp["result"]["created_act_id"]

    _rpc(db, req_id=2, method="play/scenes/create", params={"act_id": act_id, "title": "Test Scene"})

    # List all scenes
    resp = _rpc(db, req_id=3, method="play/scenes/list_all")

    assert "result" in resp
    scenes = resp["result"]["scenes"]
    assert isinstance(scenes, list)
    # Should have at least our test scene
    assert any(s["title"] == "Test Scene" for s in scenes)
