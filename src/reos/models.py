from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Event(BaseModel):
    source: str = Field(..., description="Event origin (e.g., git, reos)")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload_metadata: dict[str, Any] | None = Field(
        default=None, description="Metadata only; no content bodies."
    )
    note: str | None = Field(
        default=None, description="Optional human-readable note; avoid content dumps."
    )


class EventIngestResponse(BaseModel):
    stored: bool
    event_id: str


class Reflection(BaseModel):
    message: str
    switches_last_window: int
    window_minutes: int


class ReflectionsResponse(BaseModel):
    reflections: list[Reflection]
    events_seen: int


class OllamaHealthResponse(BaseModel):
    reachable: bool
    model_count: int | None = None
    error: str | None = None


# ============================================================================
# User Presence Models
# ============================================================================


class UserProfile(BaseModel):
    """User profile information (public, unencrypted metadata)."""

    user_id: str = Field(..., description="Unique user identifier (usr_...)")
    display_name: str = Field(..., description="User's display name", min_length=1, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserBio(BaseModel):
    """User biographical information (encrypted at rest).

    This contains sensitive personal information that ReOS uses to understand
    the user. All fields are optional and can be expanded over time.
    """

    short_bio: str = Field(default="", description="Brief bio (1-2 sentences)")
    full_bio: str = Field(default="", description="Expanded biography")
    skills: list[str] = Field(default_factory=list, description="Skills and expertise")
    interests: list[str] = Field(default_factory=list, description="Personal interests")
    goals: str = Field(default="", description="Current goals and objectives")
    context: str = Field(default="", description="Additional context for ReOS")


class UserCard(BaseModel):
    """Complete user card combining profile and bio.

    This is the full representation of a user's presence in ReOS.
    """

    profile: UserProfile
    bio: UserBio
    has_recovery_phrase: bool = Field(
        default=False, description="Whether recovery phrase is set up"
    )
    encryption_enabled: bool = Field(
        default=True, description="Whether bio data is encrypted"
    )


class UserSession(BaseModel):
    """Active user session with authentication state."""

    session_id: str = Field(..., description="Unique session identifier")
    user_id: str = Field(..., description="Authenticated user ID")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(..., description="Session expiration time")
    is_valid: bool = Field(default=True)


class UserRegistration(BaseModel):
    """Request model for user registration."""

    display_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    short_bio: str = Field(default="", max_length=500)


class UserAuthRequest(BaseModel):
    """Request model for user authentication."""

    password: str = Field(...)


class UserAuthResponse(BaseModel):
    """Response model for successful authentication."""

    user_id: str
    display_name: str
    session_id: str
    recovery_phrase: str | None = Field(
        default=None, description="Only returned on first registration"
    )


class UserProfileUpdate(BaseModel):
    """Request model for updating user profile."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    short_bio: str | None = Field(default=None, max_length=500)
    full_bio: str | None = Field(default=None, max_length=10000)
    skills: list[str] | None = Field(default=None)
    interests: list[str] | None = Field(default=None)
    goals: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=5000)


class PasswordChangeRequest(BaseModel):
    """Request model for changing password."""

    current_password: str = Field(...)
    new_password: str = Field(..., min_length=8, max_length=128)


class RecoveryRequest(BaseModel):
    """Request model for account recovery."""

    recovery_phrase: str = Field(...)
    new_password: str = Field(..., min_length=8, max_length=128)
