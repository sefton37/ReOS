"""RPC method router.

Maps JSON-RPC method names to handler functions with security middleware.

Security features:
- Rate limiting for sensitive endpoints
- Input validation and sanitization
- Audit logging for security-relevant operations
- Exception wrapping for security errors
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from reos.db import Database
from reos.rpc.types import (
    JSON,
    RpcError,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)
from reos.errors import (
    TalkingRockError,
    ValidationError as DomainValidationError,
    SafetyError,
    RateLimitError as DomainRateLimitError,
    LLMError,
    DatabaseError,
    NotFoundError,
    AuthenticationError,
    get_error_code,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Security Configuration
# =============================================================================


@dataclass
class MethodSecurityConfig:
    """Security configuration for an RPC method."""

    rate_limit_category: str | None = None  # Rate limit category to apply
    audit: bool = False  # Whether to audit log this method
    requires_validation: bool = False  # Whether to validate inputs strictly


# Method -> security config mapping
# Methods not listed get no special security treatment
METHOD_SECURITY: dict[str, MethodSecurityConfig] = {
    # Authentication (strict rate limiting)
    "auth/login": MethodSecurityConfig(rate_limit_category="auth", audit=True),
    "auth/logout": MethodSecurityConfig(audit=True),
    "auth/validate": MethodSecurityConfig(rate_limit_category="auth"),
    "auth/refresh": MethodSecurityConfig(rate_limit_category="auth"),

    # Execution (moderate rate limiting, full audit)
    "execution/start": MethodSecurityConfig(rate_limit_category="service", audit=True),
    "execution/kill": MethodSecurityConfig(audit=True),

    # Service/Container operations (rate limited)
    "service/action": MethodSecurityConfig(rate_limit_category="service", audit=True),
    "container/action": MethodSecurityConfig(rate_limit_category="container", audit=True),

    # Code Mode execution (rate limited, audited)
    "code/exec/start": MethodSecurityConfig(rate_limit_category="service", audit=True),
    "code/plan/approve": MethodSecurityConfig(audit=True),

    # Approval workflow (audited)
    "approval/respond": MethodSecurityConfig(rate_limit_category="approval", audit=True),

    # Tools (moderate rate limiting)
    "tools/call": MethodSecurityConfig(rate_limit_category="service", audit=True),

    # Safety settings (audited - changes to safety settings are security-relevant)
    "safety/set_rate_limit": MethodSecurityConfig(audit=True),
    "safety/set_sudo_limit": MethodSecurityConfig(audit=True),
    "safety/set_command_length": MethodSecurityConfig(audit=True),
    "safety/set_max_iterations": MethodSecurityConfig(audit=True),
    "safety/set_wall_clock_timeout": MethodSecurityConfig(audit=True),

    # Handoff (audited - agent switching is security-relevant)
    "handoff/switch": MethodSecurityConfig(audit=True),
    "handoff/confirm": MethodSecurityConfig(audit=True),
}


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
    """Dispatch a method call to its handler with security middleware.

    Security checks applied:
    1. Rate limiting (if configured for method)
    2. Audit logging (if configured for method)
    3. Exception wrapping for security errors

    Args:
        method: The JSON-RPC method name.
        params: The method parameters (may be None).
        db: Database instance for handlers that need it.

    Returns:
        The handler's result.

    Raises:
        RpcError: If method not found, rate limited, or handler fails.
    """
    from reos.security import (
        check_rate_limit,
        RateLimitExceeded,
        ValidationError,
        audit_log,
        AuditEventType,
    )

    handler_info = get_handler(method)

    if handler_info is None:
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    handler, needs_db = handler_info
    kwargs = params or {}

    # Get security config for this method
    security_config = METHOD_SECURITY.get(method)

    # Apply rate limiting if configured
    if security_config and security_config.rate_limit_category:
        try:
            check_rate_limit(security_config.rate_limit_category)
        except RateLimitExceeded as e:
            logger.warning(
                "Rate limit exceeded for %s (category: %s)",
                method,
                security_config.rate_limit_category,
            )
            # Audit log rate limit hit
            audit_log(
                AuditEventType.RATE_LIMIT_EXCEEDED,
                {
                    "method": method,
                    "category": security_config.rate_limit_category,
                    "retry_after": e.retry_after_seconds,
                },
                success=False,
            )
            raise RpcError(
                RATE_LIMIT_ERROR,
                str(e),
                data={"retry_after_seconds": e.retry_after_seconds},
            ) from e

    # Execute handler with security exception wrapping
    try:
        if needs_db:
            result = handler(db, **kwargs)
        else:
            result = handler(**kwargs)

        # Audit log successful security-relevant operations
        if security_config and security_config.audit:
            _audit_method_call(method, kwargs, success=True)

        return result

    except RpcError:
        # Re-raise RPC errors as-is, but audit if configured
        if security_config and security_config.audit:
            _audit_method_call(method, kwargs, success=False)
        raise

    except TalkingRockError as e:
        # Handle all domain errors with proper RPC error codes
        error_code = get_error_code(e)
        logger.warning("%s in %s: %s", type(e).__name__, method, e.message)
        if security_config and security_config.audit:
            audit_log(
                AuditEventType.VALIDATION_FAILED if isinstance(e, DomainValidationError)
                else AuditEventType.COMMAND_EXECUTED,
                {"method": method, "error_type": type(e).__name__, "message": e.message},
                success=False,
            )
        raise RpcError(
            error_code,
            e.message,
            data=e.to_dict() if e.context else None,
        ) from e

    except ValidationError as e:
        # Handle legacy security.ValidationError
        logger.warning("Validation error in %s: %s", method, e.message)
        if security_config and security_config.audit:
            audit_log(
                AuditEventType.VALIDATION_FAILED,
                {"method": method, "field": e.field, "message": e.message},
                success=False,
            )
        raise RpcError(
            -32000,  # VALIDATION_ERROR
            e.message,
            data={"field": e.field} if e.field else None,
        ) from e

    except TypeError as e:
        # Parameter mismatch - likely missing required param
        raise RpcError(INVALID_PARAMS, f"Invalid parameters for {method}: {e}") from e

    except Exception as e:
        # Log unexpected errors but don't expose details
        logger.exception("Unexpected error in %s", method)
        if security_config and security_config.audit:
            _audit_method_call(method, kwargs, success=False, error=str(e))
        raise RpcError(INTERNAL_ERROR, "Internal error") from e


def _audit_method_call(
    method: str,
    params: dict[str, Any],
    success: bool,
    error: str | None = None,
) -> None:
    """Audit log a method call."""
    from reos.security import audit_log, AuditEventType

    # Redact sensitive parameters
    safe_params = _redact_sensitive_params(params)

    details: dict[str, Any] = {
        "method": method,
        "params": safe_params,
    }
    if error:
        details["error"] = error[:200]  # Truncate error message

    audit_log(
        AuditEventType.COMMAND_EXECUTED,
        details,
        success=success,
    )


def _redact_sensitive_params(params: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive parameter values for audit logging."""
    sensitive_keys = {"password", "token", "secret", "key", "credential", "api_key"}
    result = {}
    for k, v in params.items():
        if any(s in k.lower() for s in sensitive_keys):
            result[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 500:
            result[k] = f"[STRING: {len(v)} chars]"
        elif isinstance(v, dict):
            result[k] = _redact_sensitive_params(v)
        else:
            result[k] = v
    return result


def register_handlers() -> None:
    """Import all handler modules to register their handlers.

    Call this once at startup to populate the handler registry.
    """
    # Import handlers package - it imports all handler modules
    from reos.rpc import handlers as _  # noqa: F401

    logger.debug(f"Registered {len(_HANDLERS)} RPC handlers")
