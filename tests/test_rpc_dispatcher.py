"""Tests for the rpc_dispatcher module."""

from __future__ import annotations

from typing import Any

import pytest

from reos.rpc_dispatcher import (
    ParamSpec,
    ParamType,
    RpcRegistry,
    bool_param,
    int_param,
    object_param,
    optional_bool_param,
    optional_int_param,
    optional_string_param,
    string_param,
)
from reos.rpc_validation import MAX_ID_LENGTH, MAX_TITLE_LENGTH, RpcError


class FakeDatabase:
    """Fake database for testing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def record_call(self, method: str, params: dict[str, Any]) -> None:
        self.calls.append((method, params))


class TestRpcRegistry:
    def test_register_and_has_method(self) -> None:
        registry = RpcRegistry()
        registry.register("test/method", lambda db, p: {"ok": True})

        assert registry.has_method("test/method")
        assert not registry.has_method("unknown/method")

    def test_list_methods(self) -> None:
        registry = RpcRegistry()
        registry.register("b/method", lambda db, p: {})
        registry.register("a/method", lambda db, p: {})
        registry.register("c/method", lambda db, p: {})

        assert registry.list_methods() == ["a/method", "b/method", "c/method"]

    def test_dispatch_calls_handler(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            db.record_call("test", params)
            return {"result": "success"}

        registry.register("test/method", handler)
        result = registry.dispatch(db, "test/method", {}, req_id=1)

        assert result["result"]["result"] == "success"
        assert len(db.calls) == 1

    def test_dispatch_unknown_method_raises(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "unknown/method", {}, req_id=1)

        assert exc_info.value.code == -32601
        assert "Method not found" in exc_info.value.message

    def test_dispatch_validates_params_object(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register("test/method", lambda db, p: {})

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", "not an object", req_id=1)

        assert exc_info.value.code == -32602
        assert "params must be an object" in exc_info.value.message

    def test_dispatch_no_params_required(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register("test/method", lambda db, p: {"ok": True}, requires_params=False)

        result = registry.dispatch(db, "test/method", None, req_id=1)
        assert result["result"]["ok"] is True

    def test_dispatch_with_string_param(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"title": params["title"]}

        registry.register(
            "test/method",
            handler,
            params=[string_param("title")],
        )

        result = registry.dispatch(db, "test/method", {"title": "Hello"}, req_id=1)
        assert result["result"]["title"] == "Hello"

    def test_dispatch_missing_required_string(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[string_param("title")],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {}, req_id=1)

        assert "title is required" in exc_info.value.message

    def test_dispatch_string_exceeds_max_length(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[string_param("title", max_length=10)],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"title": "x" * 15}, req_id=1)

        assert "maximum length" in exc_info.value.message

    def test_dispatch_with_optional_string(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"notes": params.get("notes")}

        registry.register(
            "test/method",
            handler,
            params=[optional_string_param("notes")],
        )

        result = registry.dispatch(db, "test/method", {}, req_id=1)
        assert result["result"]["notes"] is None

        result = registry.dispatch(db, "test/method", {"notes": "test"}, req_id=1)
        assert result["result"]["notes"] == "test"

    def test_dispatch_with_int_param(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"count": params["count"]}

        registry.register(
            "test/method",
            handler,
            params=[int_param("count", min_value=1, max_value=100)],
        )

        result = registry.dispatch(db, "test/method", {"count": 50}, req_id=1)
        assert result["result"]["count"] == 50

    def test_dispatch_int_below_min(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[int_param("count", min_value=10)],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"count": 5}, req_id=1)

        assert "at least 10" in exc_info.value.message

    def test_dispatch_int_above_max(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[int_param("count", max_value=10)],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"count": 15}, req_id=1)

        assert "at most 10" in exc_info.value.message

    def test_dispatch_with_optional_int(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"limit": params.get("limit")}

        registry.register(
            "test/method",
            handler,
            params=[optional_int_param("limit")],
        )

        result = registry.dispatch(db, "test/method", {}, req_id=1)
        assert result["result"]["limit"] is None

        result = registry.dispatch(db, "test/method", {"limit": 20}, req_id=1)
        assert result["result"]["limit"] == 20

    def test_dispatch_with_object_param(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"config": params["config"]}

        registry.register(
            "test/method",
            handler,
            params=[object_param("config")],
        )

        result = registry.dispatch(db, "test/method", {"config": {"key": "value"}}, req_id=1)
        assert result["result"]["config"] == {"key": "value"}

    def test_dispatch_object_param_not_dict(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[object_param("config")],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"config": "not an object"}, req_id=1)

        assert "must be an object" in exc_info.value.message

    def test_dispatch_with_bool_param(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"enabled": params["enabled"]}

        registry.register(
            "test/method",
            handler,
            params=[bool_param("enabled")],
        )

        result = registry.dispatch(db, "test/method", {"enabled": True}, req_id=1)
        assert result["result"]["enabled"] is True

    def test_dispatch_bool_not_bool(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[bool_param("enabled")],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"enabled": "true"}, req_id=1)

        assert "must be a boolean" in exc_info.value.message

    def test_dispatch_with_optional_bool(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {"verbose": params.get("verbose")}

        registry.register(
            "test/method",
            handler,
            params=[optional_bool_param("verbose")],
        )

        result = registry.dispatch(db, "test/method", {}, req_id=1)
        assert result["result"]["verbose"] is None

        result = registry.dispatch(db, "test/method", {"verbose": False}, req_id=1)
        assert result["result"]["verbose"] is False


class TestParamSpecDefaults:
    def test_string_param_id_default_length(self) -> None:
        spec = string_param("act_id")
        assert spec.max_length == MAX_ID_LENGTH

    def test_string_param_title_default_length(self) -> None:
        spec = string_param("title")
        assert spec.max_length == MAX_TITLE_LENGTH

    def test_string_param_custom_length(self) -> None:
        spec = string_param("custom", max_length=42)
        assert spec.max_length == 42


class TestMultipleParams:
    def test_multiple_params_all_validated(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()

        def handler(db: Any, params: dict[str, Any]) -> dict[str, Any]:
            return {
                "title": params["title"],
                "notes": params.get("notes"),
                "count": params.get("count"),
            }

        registry.register(
            "test/method",
            handler,
            params=[
                string_param("title"),
                optional_string_param("notes"),
                optional_int_param("count"),
            ],
        )

        result = registry.dispatch(
            db,
            "test/method",
            {"title": "Hello", "notes": "Some notes", "count": 5},
            req_id=1,
        )

        assert result["result"]["title"] == "Hello"
        assert result["result"]["notes"] == "Some notes"
        assert result["result"]["count"] == 5

    def test_multiple_params_missing_required(self) -> None:
        registry = RpcRegistry()
        db = FakeDatabase()
        registry.register(
            "test/method",
            lambda db, p: {},
            params=[
                string_param("title"),
                string_param("description"),
            ],
        )

        with pytest.raises(RpcError) as exc_info:
            registry.dispatch(db, "test/method", {"title": "Hello"}, req_id=1)

        assert "description is required" in exc_info.value.message
