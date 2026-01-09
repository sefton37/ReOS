"""Authentication handlers.

Handles login, logout, session validation, and refresh via PAM/Polkit.
"""

from __future__ import annotations

from typing import Any

from reos import auth
from reos.rpc.router import register
from reos.security import (
    AuditEventType,
    RateLimitExceeded,
    audit_log,
    check_rate_limit,
)


@register("auth/login")
def handle_login(
    *,
    username: str,
    password: str | None = None,
) -> dict[str, Any]:
    """Authenticate user via Polkit and create session.

    Security:
    - Uses Polkit for authentication (native system dialog)
    - Integrates with PAM, fingerprint, smartcard, etc.
    - Session token returned to Rust for storage
    """
    # Rate limit login attempts
    try:
        check_rate_limit("auth")
    except RateLimitExceeded as e:
        audit_log(
            AuditEventType.RATE_LIMIT_EXCEEDED,
            {"category": "auth", "username": username},
        )
        return {"success": False, "error": str(e)}

    result = auth.login(username, password)

    # Audit the attempt
    if result.get("success"):
        audit_log(AuditEventType.AUTH_LOGIN_SUCCESS, {"username": username})
    else:
        audit_log(
            AuditEventType.AUTH_LOGIN_FAILED,
            {
                "username": username,
                "error": result.get("error", "unknown"),
            },
        )

    return result


@register("auth/logout")
def handle_logout(
    *,
    session_token: str,
) -> dict[str, Any]:
    """Destroy a session (zeroizes key material)."""
    result = auth.logout(session_token)

    if result.get("success"):
        audit_log(AuditEventType.AUTH_LOGOUT, {"session_id": session_token[:16]})

    return result


@register("auth/validate")
def handle_validate(
    *,
    session_token: str,
) -> dict[str, Any]:
    """Validate a session token."""
    return auth.validate_session(session_token)


@register("auth/refresh")
def handle_refresh(
    *,
    session_token: str,
) -> dict[str, Any]:
    """Refresh session activity timestamp."""
    refreshed = auth.refresh_session(session_token)
    return {"success": refreshed}
