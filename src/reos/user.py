"""User presence service for ReOS.

This module provides the business logic for user account management:
- Account registration with secure password hashing
- Authentication with session management
- Profile and bio management with encryption
- Recovery passphrase generation and account recovery
- Password changes with re-encryption of data

All sensitive data (bio, personal info) is encrypted at rest using keys
derived from the user's password. The encryption keys are never stored.

Design principles:
- Zero-trust: All sensitive data encrypted with user-derived keys
- Local-first: All data stored locally in SQLite
- Transparent: User can see what's stored and export/delete their data
- Privacy-first: Minimal metadata, maximum encryption
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .crypto import (
    CryptoError,
    DecryptionError,
    EncryptedData,
    HashedPassword,
    PasswordHashError,
    decrypt_string,
    derive_keys_from_password,
    derive_keys_from_recovery_passphrase,
    encrypt,
    generate_recovery_passphrase,
    generate_salt,
    generate_user_id,
    hash_password,
    hash_recovery_passphrase,
    verify_password,
    verify_recovery_passphrase,
)
from .models import UserBio, UserCard, UserProfile

if TYPE_CHECKING:
    from .db import Database


class UserError(Exception):
    """Base exception for user operations."""

    def __init__(self, message: str, code: str = "user_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class UserNotFoundError(UserError):
    """Raised when a user is not found."""

    def __init__(self, message: str = "User not found") -> None:
        super().__init__(message, "user_not_found")


class UserExistsError(UserError):
    """Raised when trying to create a user that already exists."""

    def __init__(self, message: str = "User already exists") -> None:
        super().__init__(message, "user_exists")


class AuthenticationError(UserError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, "auth_failed")


class SessionError(UserError):
    """Raised for session-related errors."""

    def __init__(self, message: str = "Session invalid") -> None:
        super().__init__(message, "session_error")


class RecoveryError(UserError):
    """Raised when account recovery fails."""

    def __init__(self, message: str = "Recovery failed") -> None:
        super().__init__(message, "recovery_failed")


# Data type constants for encrypted storage
DATA_TYPE_BIO = "bio"

# Session configuration
SESSION_DURATION_HOURS = 24 * 7  # 1 week


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Result of successful authentication."""

    user_id: str
    display_name: str
    session_id: str
    recovery_phrase: str | None = None  # Only set on registration


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Authenticated session context with derived keys."""

    session_id: str
    user_id: str
    encryption_key: bytes
    auth_key: bytes


class UserService:
    """Service for managing user presence in ReOS.

    This service handles all user-related operations with proper encryption
    and security practices. It maintains the principle that encryption keys
    are derived from user passwords and never stored.
    """

    def __init__(self, db: "Database") -> None:
        self._db = db
        # In-memory session key cache (cleared on app restart)
        # Maps session_id -> SessionContext
        self._session_cache: dict[str, SessionContext] = {}

    def has_user(self) -> bool:
        """Check if any user exists in the system."""
        return self._db.count_users() > 0

    def get_current_user_id(self) -> str | None:
        """Get the current user ID from app state."""
        return self._db.get_state(key="current_user_id")

    def set_current_user_id(self, user_id: str | None) -> None:
        """Set the current user ID in app state."""
        self._db.set_state(key="current_user_id", value=user_id)

    def register(
        self,
        *,
        display_name: str,
        password: str,
        short_bio: str = "",
    ) -> AuthResult:
        """Register a new user account.

        This creates the user, hashes the password, generates a recovery phrase,
        encrypts initial bio data, and creates a session.

        Args:
            display_name: User's display name
            password: User's chosen password (min 8 chars)
            short_bio: Optional initial bio

        Returns:
            AuthResult with user info, session, and recovery phrase

        Raises:
            UserExistsError: If a user already exists (single-user system)
            UserError: For other registration errors
        """
        # Validate inputs
        if not display_name or not display_name.strip():
            raise UserError("Display name is required", "invalid_input")
        if not password or len(password) < 8:
            raise UserError("Password must be at least 8 characters", "invalid_password")

        display_name = display_name.strip()

        # Check if user already exists (ReOS is single-user for now)
        if self.has_user():
            raise UserExistsError("A user already exists. ReOS currently supports single-user mode.")

        try:
            # Generate user ID
            user_id = generate_user_id()

            # Generate key salt for this user
            key_salt = generate_salt(32)

            # Hash password with Argon2id
            hashed = hash_password(password)

            # Generate recovery passphrase
            recovery_phrase = generate_recovery_passphrase(8)
            recovery_hash = hash_recovery_passphrase(recovery_phrase)

            # Derive encryption keys from password
            keys = derive_keys_from_password(password, key_salt)

            # Create initial bio
            bio = UserBio(short_bio=short_bio)

            # Encrypt bio data
            bio_json = bio.model_dump_json()
            encrypted_bio = encrypt(bio_json, keys.encryption_key)

            # Create database records
            self._db.create_user(user_id=user_id, display_name=display_name)

            self._db.create_user_credentials(
                credential_id=str(uuid.uuid4()),
                user_id=user_id,
                password_hash=hashed.encode(),
                key_salt=base64.b64encode(key_salt).decode("ascii"),
                recovery_phrase_hash=recovery_hash,
            )

            self._db.upsert_user_encrypted_data(
                data_id=str(uuid.uuid4()),
                user_id=user_id,
                data_type=DATA_TYPE_BIO,
                encrypted_data=encrypted_bio.encode_base64(),
            )

            # Create session
            session_id = self._create_session(user_id, keys.encryption_key, keys.auth_key)

            # Set as current user
            self.set_current_user_id(user_id)

            return AuthResult(
                user_id=user_id,
                display_name=display_name,
                session_id=session_id,
                recovery_phrase=recovery_phrase,
            )

        except (CryptoError, PasswordHashError) as e:
            raise UserError(f"Registration failed: {e}", "crypto_error") from e

    def authenticate(self, *, password: str) -> AuthResult:
        """Authenticate the user with password.

        Args:
            password: User's password

        Returns:
            AuthResult with user info and session

        Raises:
            UserNotFoundError: If no user exists
            AuthenticationError: If password is wrong
        """
        # Get the user (single-user system)
        users = self._db.iter_users()
        if not users:
            raise UserNotFoundError("No user registered")

        user = users[0]
        user_id = str(user["id"])
        display_name = str(user["display_name"])

        # Get credentials
        creds = self._db.get_user_credentials(user_id=user_id)
        if not creds:
            raise AuthenticationError("User credentials not found")

        # Verify password
        try:
            hashed = HashedPassword.decode(str(creds["password_hash"]))
            if not verify_password(password, hashed):
                raise AuthenticationError("Invalid password")
        except PasswordHashError as e:
            raise AuthenticationError(f"Password verification failed: {e}") from e

        # Derive keys
        key_salt = base64.b64decode(str(creds["key_salt"]))
        keys = derive_keys_from_password(password, key_salt)

        # Create session
        session_id = self._create_session(user_id, keys.encryption_key, keys.auth_key)

        # Set as current user
        self.set_current_user_id(user_id)

        return AuthResult(
            user_id=user_id,
            display_name=display_name,
            session_id=session_id,
        )

    def _create_session(
        self,
        user_id: str,
        encryption_key: bytes,
        auth_key: bytes,
    ) -> str:
        """Create a new session and cache the keys."""
        session_id = f"ses_{os.urandom(16).hex()}"
        expires_at = datetime.now(UTC) + timedelta(hours=SESSION_DURATION_HOURS)

        # Store session in database
        self._db.create_user_session(
            session_id=session_id,
            user_id=user_id,
            expires_at=expires_at.isoformat(),
        )

        # Cache session with keys
        self._session_cache[session_id] = SessionContext(
            session_id=session_id,
            user_id=user_id,
            encryption_key=encryption_key,
            auth_key=auth_key,
        )

        # Store current session ID
        self._db.set_state(key="current_session_id", value=session_id)

        return session_id

    def get_session(self, session_id: str | None = None) -> SessionContext | None:
        """Get an active session context.

        Args:
            session_id: Session ID to look up, or None to get current session

        Returns:
            SessionContext if valid, None otherwise
        """
        if session_id is None:
            session_id = self._db.get_state(key="current_session_id")
            if not session_id:
                return None

        # Check cache first
        if session_id in self._session_cache:
            ctx = self._session_cache[session_id]
            # Verify still valid in DB
            session = self._db.get_user_session(session_id=session_id)
            if session and session["is_valid"]:
                expires_at = datetime.fromisoformat(str(session["expires_at"]))
                if expires_at > datetime.now(UTC):
                    return ctx

            # Session expired or invalid, remove from cache
            del self._session_cache[session_id]
            return None

        return None

    def require_session(self, session_id: str | None = None) -> SessionContext:
        """Get session or raise SessionError."""
        ctx = self.get_session(session_id)
        if ctx is None:
            raise SessionError("No active session. Please authenticate.")
        return ctx

    def logout(self, session_id: str | None = None) -> None:
        """Logout and invalidate the session."""
        if session_id is None:
            session_id = self._db.get_state(key="current_session_id")

        if session_id:
            self._db.invalidate_user_session(session_id=session_id)
            self._session_cache.pop(session_id, None)

        self._db.set_state(key="current_session_id", value=None)

    def get_user_card(self, session_id: str | None = None) -> UserCard:
        """Get the complete user card with decrypted bio.

        Args:
            session_id: Session ID for decryption keys

        Returns:
            UserCard with profile and decrypted bio

        Raises:
            SessionError: If session invalid
            UserNotFoundError: If user not found
        """
        ctx = self.require_session(session_id)

        user = self._db.get_user(user_id=ctx.user_id)
        if not user:
            raise UserNotFoundError()

        creds = self._db.get_user_credentials(user_id=ctx.user_id)
        has_recovery = bool(creds and creds.get("recovery_phrase_hash"))

        # Create profile
        profile = UserProfile(
            user_id=ctx.user_id,
            display_name=str(user["display_name"]),
            created_at=datetime.fromisoformat(str(user["created_at"])),
            updated_at=datetime.fromisoformat(str(user["updated_at"])),
        )

        # Decrypt bio
        bio = self._decrypt_bio(ctx.user_id, ctx.encryption_key)

        return UserCard(
            profile=profile,
            bio=bio,
            has_recovery_phrase=has_recovery,
            encryption_enabled=True,
        )

    def _decrypt_bio(self, user_id: str, encryption_key: bytes) -> UserBio:
        """Decrypt user bio data."""
        encrypted = self._db.get_user_encrypted_data(
            user_id=user_id,
            data_type=DATA_TYPE_BIO,
        )

        if not encrypted:
            return UserBio()

        try:
            enc_data = EncryptedData.decode_base64(str(encrypted["encrypted_data"]))
            bio_json = decrypt_string(enc_data, encryption_key)
            return UserBio.model_validate_json(bio_json)
        except (DecryptionError, ValueError):
            # If decryption fails, return empty bio
            return UserBio()

    def update_profile(
        self,
        *,
        session_id: str | None = None,
        display_name: str | None = None,
        short_bio: str | None = None,
        full_bio: str | None = None,
        skills: list[str] | None = None,
        interests: list[str] | None = None,
        goals: str | None = None,
        context: str | None = None,
    ) -> UserCard:
        """Update user profile and bio.

        All bio fields are re-encrypted with the session's encryption key.

        Args:
            session_id: Session ID
            display_name: New display name (optional)
            short_bio: New short bio (optional)
            full_bio: New full bio (optional)
            skills: New skills list (optional)
            interests: New interests list (optional)
            goals: New goals (optional)
            context: New context (optional)

        Returns:
            Updated UserCard
        """
        ctx = self.require_session(session_id)

        # Update display name if provided
        if display_name is not None:
            display_name = display_name.strip()
            if not display_name:
                raise UserError("Display name cannot be empty", "invalid_input")
            self._db.update_user(user_id=ctx.user_id, display_name=display_name)

        # Get current bio and update fields
        current_bio = self._decrypt_bio(ctx.user_id, ctx.encryption_key)

        updated_bio = UserBio(
            short_bio=short_bio if short_bio is not None else current_bio.short_bio,
            full_bio=full_bio if full_bio is not None else current_bio.full_bio,
            skills=skills if skills is not None else current_bio.skills,
            interests=interests if interests is not None else current_bio.interests,
            goals=goals if goals is not None else current_bio.goals,
            context=context if context is not None else current_bio.context,
        )

        # Encrypt and store
        bio_json = updated_bio.model_dump_json()
        encrypted_bio = encrypt(bio_json, ctx.encryption_key)

        self._db.upsert_user_encrypted_data(
            data_id=str(uuid.uuid4()),
            user_id=ctx.user_id,
            data_type=DATA_TYPE_BIO,
            encrypted_data=encrypted_bio.encode_base64(),
        )

        return self.get_user_card(session_id)

    def change_password(
        self,
        *,
        session_id: str | None = None,
        current_password: str,
        new_password: str,
    ) -> AuthResult:
        """Change user password and re-encrypt all data.

        This requires the current password to derive the old encryption key,
        then re-encrypts all data with a new key derived from the new password.

        Args:
            session_id: Session ID
            current_password: Current password for verification
            new_password: New password (min 8 chars)

        Returns:
            New AuthResult with new session

        Raises:
            AuthenticationError: If current password wrong
            UserError: For other errors
        """
        if not new_password or len(new_password) < 8:
            raise UserError("New password must be at least 8 characters", "invalid_password")

        ctx = self.require_session(session_id)

        # Get credentials
        creds = self._db.get_user_credentials(user_id=ctx.user_id)
        if not creds:
            raise UserError("Credentials not found", "internal_error")

        # Verify current password
        hashed = HashedPassword.decode(str(creds["password_hash"]))
        if not verify_password(current_password, hashed):
            raise AuthenticationError("Current password is incorrect")

        # Get current key salt and decrypt bio with old key
        old_key_salt = base64.b64decode(str(creds["key_salt"]))
        old_keys = derive_keys_from_password(current_password, old_key_salt)
        bio = self._decrypt_bio(ctx.user_id, old_keys.encryption_key)

        # Generate new credentials
        new_key_salt = generate_salt(32)
        new_hashed = hash_password(new_password)
        new_keys = derive_keys_from_password(new_password, new_key_salt)

        # Re-encrypt bio with new key
        bio_json = bio.model_dump_json()
        encrypted_bio = encrypt(bio_json, new_keys.encryption_key)

        # Update credentials
        self._db.update_user_credentials(
            user_id=ctx.user_id,
            password_hash=new_hashed.encode(),
        )

        # Update key salt separately (need to update the raw SQL for this)
        now = datetime.now(UTC).isoformat()
        self._db._execute(
            """
            UPDATE user_credentials SET key_salt = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (base64.b64encode(new_key_salt).decode("ascii"), now, ctx.user_id),
        )
        self._db.connect().commit()

        # Update encrypted data
        self._db.upsert_user_encrypted_data(
            data_id=str(uuid.uuid4()),
            user_id=ctx.user_id,
            data_type=DATA_TYPE_BIO,
            encrypted_data=encrypted_bio.encode_base64(),
        )

        # Invalidate all old sessions
        self._db.invalidate_all_user_sessions(user_id=ctx.user_id)
        self._session_cache.clear()

        # Create new session
        user = self._db.get_user(user_id=ctx.user_id)
        session_id = self._create_session(ctx.user_id, new_keys.encryption_key, new_keys.auth_key)

        return AuthResult(
            user_id=ctx.user_id,
            display_name=str(user["display_name"]) if user else "",
            session_id=session_id,
        )

    def recover_account(
        self,
        *,
        recovery_phrase: str,
        new_password: str,
    ) -> AuthResult:
        """Recover account using recovery phrase.

        This allows a user who forgot their password to reset it using their
        recovery phrase. The bio data will be lost since it was encrypted
        with the old password-derived key.

        Args:
            recovery_phrase: The recovery phrase from registration
            new_password: New password to set

        Returns:
            AuthResult with new session

        Raises:
            RecoveryError: If recovery phrase invalid
            UserError: For other errors
        """
        if not new_password or len(new_password) < 8:
            raise UserError("New password must be at least 8 characters", "invalid_password")

        # Get user
        users = self._db.iter_users()
        if not users:
            raise UserNotFoundError("No user registered")

        user = users[0]
        user_id = str(user["id"])
        display_name = str(user["display_name"])

        # Get credentials
        creds = self._db.get_user_credentials(user_id=user_id)
        if not creds:
            raise RecoveryError("Credentials not found")

        stored_hash = creds.get("recovery_phrase_hash")
        if not stored_hash:
            raise RecoveryError("No recovery phrase configured")

        # Verify recovery phrase
        if not verify_recovery_passphrase(recovery_phrase, str(stored_hash)):
            raise RecoveryError("Invalid recovery phrase")

        # Generate new credentials
        new_key_salt = generate_salt(32)
        new_hashed = hash_password(new_password)
        new_keys = derive_keys_from_password(new_password, new_key_salt)

        # Create empty bio (old data is lost since we can't decrypt it)
        bio = UserBio()
        bio_json = bio.model_dump_json()
        encrypted_bio = encrypt(bio_json, new_keys.encryption_key)

        # Update credentials
        now = datetime.now(UTC).isoformat()
        self._db._execute(
            """
            UPDATE user_credentials
            SET password_hash = ?, key_salt = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                new_hashed.encode(),
                base64.b64encode(new_key_salt).decode("ascii"),
                now,
                user_id,
            ),
        )
        self._db.connect().commit()

        # Update encrypted data (reset to empty since we can't decrypt old data)
        self._db.upsert_user_encrypted_data(
            data_id=str(uuid.uuid4()),
            user_id=user_id,
            data_type=DATA_TYPE_BIO,
            encrypted_data=encrypted_bio.encode_base64(),
        )

        # Invalidate all old sessions
        self._db.invalidate_all_user_sessions(user_id=user_id)
        self._session_cache.clear()

        # Create new session
        session_id = self._create_session(user_id, new_keys.encryption_key, new_keys.auth_key)

        # Set as current user
        self.set_current_user_id(user_id)

        return AuthResult(
            user_id=user_id,
            display_name=display_name,
            session_id=session_id,
        )

    def generate_new_recovery_phrase(self, session_id: str | None = None) -> str:
        """Generate a new recovery phrase.

        This invalidates the old recovery phrase and generates a new one.
        The user should store this securely.

        Args:
            session_id: Session ID

        Returns:
            New recovery phrase

        Raises:
            SessionError: If session invalid
        """
        ctx = self.require_session(session_id)

        recovery_phrase = generate_recovery_passphrase(8)
        recovery_hash = hash_recovery_passphrase(recovery_phrase)

        self._db.update_user_credentials(
            user_id=ctx.user_id,
            recovery_phrase_hash=recovery_hash,
        )

        return recovery_phrase

    def delete_account(self, *, session_id: str | None = None, password: str) -> None:
        """Permanently delete the user account.

        Requires password confirmation for safety.

        Args:
            session_id: Session ID
            password: Password for confirmation

        Raises:
            AuthenticationError: If password wrong
            SessionError: If session invalid
        """
        ctx = self.require_session(session_id)

        # Verify password
        creds = self._db.get_user_credentials(user_id=ctx.user_id)
        if not creds:
            raise UserError("Credentials not found", "internal_error")

        hashed = HashedPassword.decode(str(creds["password_hash"]))
        if not verify_password(password, hashed):
            raise AuthenticationError("Password is incorrect")

        # Clear session cache
        self._session_cache.clear()
        self._db.set_state(key="current_session_id", value=None)
        self._db.set_state(key="current_user_id", value=None)

        # Delete user (cascades to credentials, encrypted data, sessions)
        self._db.delete_user(user_id=ctx.user_id)


# Global service instance
_user_service: UserService | None = None


def get_user_service(db: "Database") -> UserService:
    """Get or create the global user service instance."""
    global _user_service
    if _user_service is None:
        _user_service = UserService(db)
    return _user_service
