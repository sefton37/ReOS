"""RPC method router.

Maps JSON-RPC method names to handler functions.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from reos.db import Database
from reos.rpc.types import JSON, RpcError, METHOD_NOT_FOUND

logger = logging.getLogger(__name__)


class Handler(Protocol):
    """Protocol for RPC handler functions."""

    def __call__(self, **kwargs: Any) -> Any:
        ...


class HandlerWithDb(Protocol):
    """Protocol for RPC handler functions that need database access."""

    def __call__(self, db: Database, **kwargs: Any) -> Any:
        ...


# Handler registry: method name -> (handler_func, needs_db)
_HANDLERS: dict[str, tuple[Callable[..., Any], bool]] = {}


def register(method: str, *, needs_db: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register an RPC handler.

    Usage:
        @register("auth/login")
        def handle_login(*, username: str, password: str | None = None) -> dict:
            ...

        @register("tools/call", needs_db=True)
        def handle_call(db: Database, *, name: str, arguments: dict | None) -> Any:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _HANDLERS[method] = (func, needs_db)
        return func

    return decorator


def get_handler(method: str) -> tuple[Callable[..., Any], bool] | None:
    """Get handler for a method, or None if not found."""
    return _HANDLERS.get(method)


def list_methods() -> list[str]:
    """List all registered method names."""
    return sorted(_HANDLERS.keys())


def dispatch(method: str, params: JSON | None, db: Database) -> Any:
    """Dispatch a method call to its handler.

    Args:
        method: The JSON-RPC method name.
        params: The method parameters (may be None).
        db: Database instance for handlers that need it.

    Returns:
        The handler's result.

    Raises:
        RpcError: If method not found or handler fails.
    """
    handler_info = get_handler(method)

    if handler_info is None:
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    handler, needs_db = handler_info
    kwargs = params or {}

    try:
        if needs_db:
            return handler(db, **kwargs)
        else:
            return handler(**kwargs)
    except RpcError:
        # Re-raise RPC errors as-is
        raise
    except TypeError as e:
        # Parameter mismatch - likely missing required param
        raise RpcError(METHOD_NOT_FOUND, f"Invalid parameters for {method}: {e}") from e


def register_handlers() -> None:
    """Import all handler modules to register their handlers.

    Call this once at startup to populate the handler registry.
    """
    # Import handlers package - it imports all handler modules
    from reos.rpc import handlers as _  # noqa: F401

    logger.debug(f"Registered {len(_HANDLERS)} RPC handlers")
