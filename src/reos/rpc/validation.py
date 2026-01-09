"""Input validation helpers for RPC handlers.

Provides validation decorators and utility functions that handlers
can use to ensure inputs are safe and well-formed.
"""

from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable, TypeVar

from reos.rpc.types import RpcError, INVALID_PARAMS
from reos.security import (
    ValidationError,
    validate_service_name,
    validate_container_id,
    validate_package_name,
    is_command_safe,
    detect_prompt_injection,
    MAX_COMMAND_LEN,
)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# String Validation
# =============================================================================


def validate_string(
    value: Any,
    name: str,
    *,
    min_length: int = 0,
    max_length: int = 10000,
    pattern: re.Pattern[str] | None = None,
    allow_empty: bool = False,
) -> str:
    """Validate a string parameter.

    Args:
        value: The value to validate
        name: Parameter name for error messages
        min_length: Minimum length (default 0)
        max_length: Maximum length (default 10000)
        pattern: Optional regex pattern to match
        allow_empty: Whether empty strings are allowed

    Returns:
        The validated string

    Raises:
        RpcError: If validation fails
    """
    if not isinstance(value, str):
        raise RpcError(INVALID_PARAMS, f"{name} must be a string")

    if not value and not allow_empty:
        raise RpcError(INVALID_PARAMS, f"{name} cannot be empty")

    if len(value) < min_length:
        raise RpcError(INVALID_PARAMS, f"{name} must be at least {min_length} characters")

    if len(value) > max_length:
        raise RpcError(INVALID_PARAMS, f"{name} must be at most {max_length} characters")

    if pattern and not pattern.match(value):
        raise RpcError(INVALID_PARAMS, f"{name} has invalid format")

    return value


def validate_identifier(value: Any, name: str) -> str:
    """Validate an identifier (alphanumeric + underscore + dash).

    Args:
        value: The value to validate
        name: Parameter name for error messages

    Returns:
        The validated identifier

    Raises:
        RpcError: If validation fails
    """
    value = validate_string(value, name, max_length=256)
    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
        raise RpcError(
            INVALID_PARAMS,
            f"{name} must contain only alphanumeric characters, underscores, and dashes",
        )
    return value


def validate_path(value: Any, name: str) -> str:
    """Validate a file path.

    Checks for path traversal attacks and invalid characters.

    Args:
        value: The value to validate
        name: Parameter name for error messages

    Returns:
        The validated path

    Raises:
        RpcError: If validation fails
    """
    value = validate_string(value, name, max_length=4096)

    # Check for path traversal
    if ".." in value:
        raise RpcError(INVALID_PARAMS, f"{name} cannot contain '..' (path traversal)")

    # Check for null bytes (can cause truncation in C-based libs)
    if "\x00" in value:
        raise RpcError(INVALID_PARAMS, f"{name} contains invalid characters")

    return value


# =============================================================================
# Numeric Validation
# =============================================================================


def validate_int(
    value: Any,
    name: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    """Validate an integer parameter.

    Args:
        value: The value to validate
        name: Parameter name for error messages
        min_value: Minimum allowed value
        max_value: Maximum allowed value

    Returns:
        The validated integer

    Raises:
        RpcError: If validation fails
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"{name} must be an integer")

    if min_value is not None and value < min_value:
        raise RpcError(INVALID_PARAMS, f"{name} must be at least {min_value}")

    if max_value is not None and value > max_value:
        raise RpcError(INVALID_PARAMS, f"{name} must be at most {max_value}")

    return value


def validate_positive_int(value: Any, name: str, *, max_value: int | None = None) -> int:
    """Validate a positive integer (> 0)."""
    return validate_int(value, name, min_value=1, max_value=max_value)


# =============================================================================
# Boolean Validation
# =============================================================================


def validate_bool(value: Any, name: str) -> bool:
    """Validate a boolean parameter.

    Args:
        value: The value to validate
        name: Parameter name for error messages

    Returns:
        The validated boolean

    Raises:
        RpcError: If validation fails
    """
    if not isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"{name} must be a boolean")
    return value


# =============================================================================
# List Validation
# =============================================================================


def validate_list(
    value: Any,
    name: str,
    *,
    max_length: int = 1000,
    item_validator: Callable[[Any, str], Any] | None = None,
) -> list[Any]:
    """Validate a list parameter.

    Args:
        value: The value to validate
        name: Parameter name for error messages
        max_length: Maximum list length
        item_validator: Optional validator function for each item

    Returns:
        The validated list

    Raises:
        RpcError: If validation fails
    """
    if not isinstance(value, list):
        raise RpcError(INVALID_PARAMS, f"{name} must be a list")

    if len(value) > max_length:
        raise RpcError(INVALID_PARAMS, f"{name} cannot have more than {max_length} items")

    if item_validator:
        result = []
        for i, item in enumerate(value):
            try:
                result.append(item_validator(item, f"{name}[{i}]"))
            except RpcError:
                raise
            except Exception as e:
                raise RpcError(INVALID_PARAMS, f"Invalid item in {name}: {e}") from e
        return result

    return value


# =============================================================================
# Security-Specific Validation
# =============================================================================


def validate_command(command: str) -> str:
    """Validate a shell command for safety.

    Args:
        command: The command to validate

    Returns:
        The validated command

    Raises:
        RpcError: If command is unsafe
    """
    if len(command) > MAX_COMMAND_LEN:
        raise RpcError(
            INVALID_PARAMS,
            f"Command too long (max {MAX_COMMAND_LEN} characters)",
        )

    is_safe, reason = is_command_safe(command)
    if not is_safe:
        raise RpcError(INVALID_PARAMS, f"Command blocked: {reason}")

    return command


def validate_user_input(text: str, *, check_injection: bool = True) -> str:
    """Validate user input text.

    Args:
        text: The user input to validate
        check_injection: Whether to check for prompt injection

    Returns:
        The validated (possibly sanitized) text

    Raises:
        RpcError: If input appears malicious
    """
    if len(text) > 50000:  # 50KB limit for user input
        raise RpcError(INVALID_PARAMS, "Input too long")

    if check_injection:
        result = detect_prompt_injection(text)
        if result.is_suspicious and result.confidence > 0.5:
            # High-confidence injection attempt - block it
            raise RpcError(
                INVALID_PARAMS,
                "Input contains suspicious patterns",
                data={"patterns": result.detected_patterns},
            )
        # Return sanitized version for lower-confidence matches
        return result.sanitized_input

    return text


# =============================================================================
# Validation Decorator
# =============================================================================


def validated(**validators: Callable[[Any, str], Any]) -> Callable[[F], F]:
    """Decorator to validate handler parameters.

    Usage:
        @validated(
            name=validate_identifier,
            count=lambda v, n: validate_int(v, n, min_value=1, max_value=100),
        )
        def handle_something(*, name: str, count: int) -> dict:
            ...

    Args:
        **validators: Mapping of parameter name to validator function

    Returns:
        Decorator function
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate each configured parameter
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    kwargs[param_name] = validator(kwargs[param_name], param_name)
            return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator
