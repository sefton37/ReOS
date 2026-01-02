"""RPC method dispatcher with registry pattern.

This module provides a registry-based approach to JSON-RPC method handling.
Methods are registered with their handlers and parameter specifications,
enabling automatic validation and consistent error handling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .db import Database
from .rpc_validation import (
    ERROR_INVALID_PARAMS,
    ERROR_METHOD_NOT_FOUND,
    MAX_ID_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_PATH_LENGTH,
    MAX_SYSTEM_PROMPT_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_TITLE_LENGTH,
    RpcError,
    jsonrpc_error,
    jsonrpc_result,
    validate_optional_string,
    validate_params_object,
    validate_required_string,
)

logger = logging.getLogger(__name__)

# Type alias for JSON
JSON = dict[str, Any]

# Handler function type: takes db and validated params, returns result dict
HandlerFunc = Callable[[Database, dict[str, Any]], dict[str, Any]]


class ParamType(Enum):
    """Parameter types for automatic validation."""

    STRING = "string"
    STRING_OPTIONAL = "string_optional"
    INT = "int"
    INT_OPTIONAL = "int_optional"
    BOOL = "bool"
    BOOL_OPTIONAL = "bool_optional"
    OBJECT = "object"
    OBJECT_OPTIONAL = "object_optional"
    ANY = "any"


@dataclass(frozen=True)
class ParamSpec:
    """Specification for a single parameter."""

    name: str
    param_type: ParamType
    max_length: int | None = None  # For strings
    min_value: int | None = None  # For ints
    max_value: int | None = None  # For ints
    allow_empty: bool = False  # For strings


@dataclass
class MethodSpec:
    """Specification for an RPC method."""

    name: str
    handler: HandlerFunc
    params: list[ParamSpec] = field(default_factory=list)
    requires_params: bool = True  # If True, params must be an object


class RpcRegistry:
    """Registry of RPC methods with automatic validation."""

    def __init__(self) -> None:
        self._methods: dict[str, MethodSpec] = {}

    def register(
        self,
        name: str,
        handler: HandlerFunc,
        params: list[ParamSpec] | None = None,
        requires_params: bool = True,
    ) -> None:
        """Register an RPC method.

        Args:
            name: The method name (e.g., "play/acts/create").
            handler: The handler function.
            params: List of parameter specifications.
            requires_params: If True, params must be provided as an object.
        """
        self._methods[name] = MethodSpec(
            name=name,
            handler=handler,
            params=params or [],
            requires_params=requires_params,
        )

    def has_method(self, name: str) -> bool:
        """Check if a method is registered."""
        return name in self._methods

    def get_method(self, name: str) -> MethodSpec | None:
        """Get a method spec by name."""
        return self._methods.get(name)

    def list_methods(self) -> list[str]:
        """List all registered method names."""
        return sorted(self._methods.keys())

    def dispatch(
        self, db: Database, method: str, params: Any, req_id: Any
    ) -> JSON | None:
        """Dispatch an RPC request to the appropriate handler.

        Args:
            db: Database instance.
            method: Method name.
            params: Request parameters.
            req_id: Request ID.

        Returns:
            JSON-RPC response dict, or None for notifications.
        """
        spec = self._methods.get(method)
        if spec is None:
            raise RpcError(code=ERROR_METHOD_NOT_FOUND, message=f"Method not found: {method}")

        # Validate params structure
        if spec.requires_params:
            validated_params = validate_params_object(params)
        else:
            validated_params = params if isinstance(params, dict) else {}

        # Validate individual parameters
        extracted = self._validate_params(validated_params, spec.params)

        # Call the handler
        result = spec.handler(db, extracted)
        return jsonrpc_result(req_id=req_id, result=result)

    def _validate_params(
        self, params: dict[str, Any], specs: list[ParamSpec]
    ) -> dict[str, Any]:
        """Validate and extract parameters according to specs.

        Returns a dict with validated parameter values.
        """
        extracted: dict[str, Any] = {}

        for spec in specs:
            value = self._validate_single_param(params, spec)
            extracted[spec.name] = value

        return extracted

    def _validate_single_param(self, params: dict[str, Any], spec: ParamSpec) -> Any:
        """Validate a single parameter and return the extracted value."""
        value = params.get(spec.name)

        if spec.param_type == ParamType.STRING:
            max_len = spec.max_length or MAX_TEXT_LENGTH
            return validate_required_string(
                params, spec.name, max_len, allow_empty=spec.allow_empty
            )

        if spec.param_type == ParamType.STRING_OPTIONAL:
            max_len = spec.max_length or MAX_TEXT_LENGTH
            return validate_optional_string(params, spec.name, max_len)

        if spec.param_type == ParamType.INT:
            if not isinstance(value, int) or isinstance(value, bool):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS, message=f"{spec.name} must be an integer"
                )
            if spec.min_value is not None and value < spec.min_value:
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be at least {spec.min_value}",
                )
            if spec.max_value is not None and value > spec.max_value:
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be at most {spec.max_value}",
                )
            return value

        if spec.param_type == ParamType.INT_OPTIONAL:
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be an integer or null",
                )
            if spec.min_value is not None and value < spec.min_value:
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be at least {spec.min_value}",
                )
            if spec.max_value is not None and value > spec.max_value:
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be at most {spec.max_value}",
                )
            return value

        if spec.param_type == ParamType.BOOL:
            if not isinstance(value, bool):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS, message=f"{spec.name} must be a boolean"
                )
            return value

        if spec.param_type == ParamType.BOOL_OPTIONAL:
            if value is None:
                return None
            if not isinstance(value, bool):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be a boolean or null",
                )
            return value

        if spec.param_type == ParamType.OBJECT:
            if not isinstance(value, dict):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS, message=f"{spec.name} must be an object"
                )
            return value

        if spec.param_type == ParamType.OBJECT_OPTIONAL:
            if value is None:
                return None
            if not isinstance(value, dict):
                raise RpcError(
                    code=ERROR_INVALID_PARAMS,
                    message=f"{spec.name} must be an object or null",
                )
            return value

        # ParamType.ANY - no validation
        return value


def create_param(
    name: str,
    param_type: ParamType | str,
    *,
    max_length: int | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
    allow_empty: bool = False,
) -> ParamSpec:
    """Factory function for creating parameter specs.

    Args:
        name: Parameter name.
        param_type: Type of parameter.
        max_length: Max string length (uses defaults based on name if not provided).
        min_value: Min int value.
        max_value: Max int value.
        allow_empty: Allow empty strings.

    Returns:
        ParamSpec instance.
    """
    if isinstance(param_type, str):
        param_type = ParamType(param_type)

    # Apply sensible defaults based on parameter name patterns
    if max_length is None and param_type in (ParamType.STRING, ParamType.STRING_OPTIONAL):
        if "id" in name.lower():
            max_length = MAX_ID_LENGTH
        elif "title" in name.lower():
            max_length = MAX_TITLE_LENGTH
        elif "notes" in name.lower():
            max_length = MAX_NOTES_LENGTH
        elif "path" in name.lower():
            max_length = MAX_PATH_LENGTH
        elif "prompt" in name.lower() or "context" in name.lower():
            max_length = MAX_SYSTEM_PROMPT_LENGTH
        else:
            max_length = MAX_TEXT_LENGTH

    return ParamSpec(
        name=name,
        param_type=param_type,
        max_length=max_length,
        min_value=min_value,
        max_value=max_value,
        allow_empty=allow_empty,
    )


# Convenience functions for common parameter types
def string_param(name: str, *, max_length: int | None = None, allow_empty: bool = False) -> ParamSpec:
    """Create a required string parameter spec."""
    return create_param(name, ParamType.STRING, max_length=max_length, allow_empty=allow_empty)


def optional_string_param(name: str, *, max_length: int | None = None) -> ParamSpec:
    """Create an optional string parameter spec."""
    return create_param(name, ParamType.STRING_OPTIONAL, max_length=max_length)


def int_param(name: str, *, min_value: int | None = None, max_value: int | None = None) -> ParamSpec:
    """Create a required integer parameter spec."""
    return create_param(name, ParamType.INT, min_value=min_value, max_value=max_value)


def optional_int_param(name: str, *, min_value: int | None = None, max_value: int | None = None) -> ParamSpec:
    """Create an optional integer parameter spec."""
    return create_param(name, ParamType.INT_OPTIONAL, min_value=min_value, max_value=max_value)


def object_param(name: str) -> ParamSpec:
    """Create a required object parameter spec."""
    return create_param(name, ParamType.OBJECT)


def optional_object_param(name: str) -> ParamSpec:
    """Create an optional object parameter spec."""
    return create_param(name, ParamType.OBJECT_OPTIONAL)


def bool_param(name: str) -> ParamSpec:
    """Create a required boolean parameter spec."""
    return create_param(name, ParamType.BOOL)


def optional_bool_param(name: str) -> ParamSpec:
    """Create an optional boolean parameter spec."""
    return create_param(name, ParamType.BOOL_OPTIONAL)
