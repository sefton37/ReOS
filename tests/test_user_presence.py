"""Tests for user presence system.

This module tests the complete user presence flow including:
- Cryptographic operations (hashing, encryption, key derivation)
- User registration and authentication
- Profile and bio management
- Recovery passphrase flow
- Session management
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import pytest

from reos.crypto import (
    CryptoError,
    DecryptionError,
    EncryptedData,
    HashedPassword,
    PasswordHashError,
    decrypt,
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
from reos.db import Database
from reos.user import (
    AuthenticationError,
    RecoveryError,
    SessionError,
    UserError,
    UserExistsError,
    UserNotFoundError,
    UserService,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_db() -> Database:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "test.db")
        db.migrate()
        yield db
        db.close()


@pytest.fixture
def user_service(temp_db: Database) -> UserService:
    """Create a user service with temporary database."""
    return UserService(temp_db)


# ============================================================================
# Cryptography Tests
# ============================================================================


class TestPasswordHashing:
    """Tests for Argon2id password hashing."""

    def test_hash_password_creates_valid_hash(self) -> None:
        """Hashing a password should create a valid hash object."""
        hashed = hash_password("testpassword123")

        assert hashed.algorithm == "argon2id"
        assert hashed.version == 19
        assert len(hashed.salt) == 16
        assert len(hashed.hash) == 32

    def test_hash_password_different_salts(self) -> None:
        """Same password with different salts should produce different hashes."""
        hashed1 = hash_password("testpassword123")
        hashed2 = hash_password("testpassword123")

        assert hashed1.salt != hashed2.salt
        assert hashed1.hash != hashed2.hash

    def test_hash_password_same_salt_same_hash(self) -> None:
        """Same password with same salt should produce same hash."""
        salt = generate_salt()
        hashed1 = hash_password("testpassword123", salt)
        hashed2 = hash_password("testpassword123", salt)

        assert hashed1.hash == hashed2.hash

    def test_hash_password_empty_raises(self) -> None:
        """Empty password should raise error."""
        with pytest.raises(PasswordHashError):
            hash_password("")

    def test_verify_password_correct(self) -> None:
        """Correct password should verify successfully."""
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """Incorrect password should fail verification."""
        hashed = hash_password("mypassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty(self) -> None:
        """Empty password should fail verification."""
        hashed = hash_password("mypassword")
        assert verify_password("", hashed) is False

    def test_hashed_password_encode_decode(self) -> None:
        """HashedPassword should round-trip through encode/decode."""
        original = hash_password("testpassword")
        encoded = original.encode()
        decoded = HashedPassword.decode(encoded)

        assert decoded.algorithm == original.algorithm
        assert decoded.version == original.version
        assert decoded.memory_cost == original.memory_cost
        assert decoded.time_cost == original.time_cost
        assert decoded.parallelism == original.parallelism
        assert decoded.salt == original.salt
        assert decoded.hash == original.hash


class TestEncryption:
    """Tests for ChaCha20-Poly1305 encryption."""

    def test_encrypt_decrypt_string(self) -> None:
        """Encrypting and decrypting a string should return original."""
        key = generate_salt(32)
        plaintext = "Hello, World! This is a test message."

        encrypted = encrypt(plaintext, key)
        decrypted = decrypt_string(encrypted, key)

        assert decrypted == plaintext

    def test_encrypt_decrypt_bytes(self) -> None:
        """Encrypting and decrypting bytes should return original."""
        key = generate_salt(32)
        plaintext = b"\x00\x01\x02\x03\x04\x05"

        encrypted = encrypt(plaintext, key)
        decrypted = decrypt(encrypted, key)

        assert decrypted == plaintext

    def test_different_keys_fail_decrypt(self) -> None:
        """Decrypting with wrong key should fail."""
        key1 = generate_salt(32)
        key2 = generate_salt(32)

        encrypted = encrypt("secret message", key1)

        with pytest.raises(DecryptionError):
            decrypt(encrypted, key2)

    def test_tampered_ciphertext_fails(self) -> None:
        """Tampered ciphertext should fail authentication."""
        key = generate_salt(32)
        encrypted = encrypt("secret message", key)

        # Tamper with ciphertext
        tampered_ct = bytes([encrypted.ciphertext[0] ^ 0xFF]) + encrypted.ciphertext[1:]
        tampered = EncryptedData(
            version=encrypted.version,
            nonce=encrypted.nonce,
            ciphertext=tampered_ct,
        )

        with pytest.raises(DecryptionError):
            decrypt(tampered, key)

    def test_encrypted_data_encode_decode(self) -> None:
        """EncryptedData should round-trip through encode/decode."""
        key = generate_salt(32)
        encrypted = encrypt("test message", key)

        # Binary round-trip
        encoded = encrypted.encode()
        decoded = EncryptedData.decode(encoded)
        assert decrypt_string(decoded, key) == "test message"

        # Base64 round-trip
        encoded_b64 = encrypted.encode_base64()
        decoded_b64 = EncryptedData.decode_base64(encoded_b64)
        assert decrypt_string(decoded_b64, key) == "test message"


class TestKeyDerivation:
    """Tests for key derivation from passwords."""

    def test_derive_keys_from_password(self) -> None:
        """Deriving keys from password should produce consistent keys."""
        salt = generate_salt(32)
        keys1 = derive_keys_from_password("mypassword", salt)
        keys2 = derive_keys_from_password("mypassword", salt)

        assert keys1.encryption_key == keys2.encryption_key
        assert keys1.auth_key == keys2.auth_key
        assert keys1.encryption_key != keys1.auth_key  # Different purposes

    def test_different_passwords_different_keys(self) -> None:
        """Different passwords should produce different keys."""
        salt = generate_salt(32)
        keys1 = derive_keys_from_password("password1", salt)
        keys2 = derive_keys_from_password("password2", salt)

        assert keys1.encryption_key != keys2.encryption_key

    def test_different_salts_different_keys(self) -> None:
        """Different salts should produce different keys."""
        keys1 = derive_keys_from_password("password", generate_salt(32))
        keys2 = derive_keys_from_password("password", generate_salt(32))

        assert keys1.encryption_key != keys2.encryption_key


class TestRecoveryPassphrase:
    """Tests for recovery passphrase generation and verification."""

    def test_generate_recovery_passphrase(self) -> None:
        """Generated passphrase should have correct word count."""
        phrase = generate_recovery_passphrase(8)
        words = phrase.split()
        assert len(words) == 8

    def test_recovery_passphrase_uniqueness(self) -> None:
        """Generated passphrases should be unique."""
        phrases = [generate_recovery_passphrase(8) for _ in range(10)]
        assert len(set(phrases)) == 10

    def test_hash_and_verify_recovery_passphrase(self) -> None:
        """Passphrase hash should verify correctly."""
        phrase = generate_recovery_passphrase(8)
        hashed = hash_recovery_passphrase(phrase)

        assert verify_recovery_passphrase(phrase, hashed) is True
        assert verify_recovery_passphrase("wrong phrase", hashed) is False

    def test_recovery_passphrase_case_insensitive(self) -> None:
        """Passphrase verification should be case-insensitive."""
        phrase = generate_recovery_passphrase(8)
        hashed = hash_recovery_passphrase(phrase)

        assert verify_recovery_passphrase(phrase.upper(), hashed) is True
        assert verify_recovery_passphrase(phrase.lower(), hashed) is True

    def test_derive_keys_from_recovery_passphrase(self) -> None:
        """Keys should be derivable from recovery passphrase."""
        phrase = generate_recovery_passphrase(8)
        salt = generate_salt(32)

        keys = derive_keys_from_recovery_passphrase(phrase, salt)

        assert len(keys.encryption_key) == 32
        assert len(keys.auth_key) == 32


class TestUserIdGeneration:
    """Tests for user ID generation."""

    def test_generate_user_id_format(self) -> None:
        """User ID should have correct format."""
        user_id = generate_user_id()
        assert user_id.startswith("usr_")
        assert len(user_id) == 24  # "usr_" + 20 hex chars

    def test_generate_user_id_uniqueness(self) -> None:
        """User IDs should be unique."""
        ids = [generate_user_id() for _ in range(100)]
        assert len(set(ids)) == 100


# ============================================================================
# User Service Tests
# ============================================================================


class TestUserRegistration:
    """Tests for user registration."""

    def test_register_creates_user(self, user_service: UserService) -> None:
        """Registration should create a user and return auth result."""
        result = user_service.register(
            display_name="Test User",
            password="securepassword123",
            short_bio="I am a test user.",
        )

        assert result.user_id.startswith("usr_")
        assert result.display_name == "Test User"
        assert result.session_id.startswith("ses_")
        assert result.recovery_phrase is not None
        assert len(result.recovery_phrase.split()) == 8

    def test_register_creates_session(self, user_service: UserService) -> None:
        """Registration should create an active session."""
        result = user_service.register(
            display_name="Test User",
            password="securepassword123",
        )

        session = user_service.get_session(result.session_id)
        assert session is not None
        assert session.user_id == result.user_id

    def test_register_second_user_fails(self, user_service: UserService) -> None:
        """Registering a second user should fail (single-user mode)."""
        user_service.register(
            display_name="First User",
            password="password123",
        )

        with pytest.raises(UserExistsError):
            user_service.register(
                display_name="Second User",
                password="password456",
            )

    def test_register_short_password_fails(self, user_service: UserService) -> None:
        """Password shorter than 8 characters should fail."""
        with pytest.raises(UserError) as exc_info:
            user_service.register(
                display_name="Test User",
                password="short",
            )
        assert "8 characters" in str(exc_info.value)

    def test_register_empty_name_fails(self, user_service: UserService) -> None:
        """Empty display name should fail."""
        with pytest.raises(UserError):
            user_service.register(
                display_name="   ",
                password="securepassword123",
            )


class TestUserAuthentication:
    """Tests for user authentication."""

    def test_authenticate_correct_password(self, user_service: UserService) -> None:
        """Correct password should authenticate successfully."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )
        user_service.logout()

        result = user_service.authenticate(password="mypassword123")

        assert result.display_name == "Test User"
        assert result.session_id.startswith("ses_")

    def test_authenticate_wrong_password(self, user_service: UserService) -> None:
        """Wrong password should fail authentication."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )
        user_service.logout()

        with pytest.raises(AuthenticationError):
            user_service.authenticate(password="wrongpassword")

    def test_authenticate_no_user(self, user_service: UserService) -> None:
        """Authentication with no registered user should fail."""
        with pytest.raises(UserNotFoundError):
            user_service.authenticate(password="anypassword")


class TestUserProfile:
    """Tests for user profile management."""

    def test_get_user_card(self, user_service: UserService) -> None:
        """Should return user card with profile and bio."""
        user_service.register(
            display_name="Test User",
            password="securepassword123",
            short_bio="Hello, I am a test user.",
        )

        card = user_service.get_user_card()

        assert card.profile.display_name == "Test User"
        assert card.bio.short_bio == "Hello, I am a test user."
        assert card.encryption_enabled is True
        assert card.has_recovery_phrase is True

    def test_update_profile(self, user_service: UserService) -> None:
        """Should update profile fields."""
        user_service.register(
            display_name="Original Name",
            password="securepassword123",
        )

        card = user_service.update_profile(
            display_name="New Name",
            short_bio="New bio",
            skills=["Python", "TypeScript"],
            interests=["AI", "Security"],
        )

        assert card.profile.display_name == "New Name"
        assert card.bio.short_bio == "New bio"
        assert card.bio.skills == ["Python", "TypeScript"]
        assert card.bio.interests == ["AI", "Security"]

    def test_update_profile_partial(self, user_service: UserService) -> None:
        """Should update only specified fields."""
        user_service.register(
            display_name="Test User",
            password="securepassword123",
            short_bio="Original bio",
        )

        # Update only goals
        card = user_service.update_profile(goals="New goals")

        assert card.profile.display_name == "Test User"  # Unchanged
        assert card.bio.short_bio == "Original bio"  # Unchanged
        assert card.bio.goals == "New goals"  # Changed

    def test_get_user_card_requires_session(self, user_service: UserService) -> None:
        """Getting user card without session should fail."""
        user_service.register(
            display_name="Test User",
            password="securepassword123",
        )
        user_service.logout()

        with pytest.raises(SessionError):
            user_service.get_user_card()


class TestPasswordChange:
    """Tests for password change."""

    def test_change_password_success(self, user_service: UserService) -> None:
        """Changing password should work and create new session."""
        user_service.register(
            display_name="Test User",
            password="oldpassword123",
            short_bio="Test bio",
        )

        result = user_service.change_password(
            current_password="oldpassword123",
            new_password="newpassword456",
        )

        assert result.session_id.startswith("ses_")

        # Old password should no longer work
        user_service.logout()
        with pytest.raises(AuthenticationError):
            user_service.authenticate(password="oldpassword123")

        # New password should work
        user_service.authenticate(password="newpassword456")

    def test_change_password_preserves_bio(self, user_service: UserService) -> None:
        """Changing password should preserve encrypted bio."""
        user_service.register(
            display_name="Test User",
            password="oldpassword123",
            short_bio="My important bio",
        )

        user_service.change_password(
            current_password="oldpassword123",
            new_password="newpassword456",
        )

        card = user_service.get_user_card()
        assert card.bio.short_bio == "My important bio"

    def test_change_password_wrong_current(self, user_service: UserService) -> None:
        """Wrong current password should fail."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )

        with pytest.raises(AuthenticationError):
            user_service.change_password(
                current_password="wrongpassword",
                new_password="newpassword456",
            )


class TestAccountRecovery:
    """Tests for account recovery."""

    def test_recover_account_success(self, user_service: UserService) -> None:
        """Recovery with correct phrase should work."""
        reg_result = user_service.register(
            display_name="Test User",
            password="oldpassword123",
        )
        recovery_phrase = reg_result.recovery_phrase
        user_service.logout()

        result = user_service.recover_account(
            recovery_phrase=recovery_phrase,
            new_password="newpassword456",
        )

        assert result.display_name == "Test User"
        assert result.session_id.startswith("ses_")

    def test_recover_account_resets_bio(self, user_service: UserService) -> None:
        """Recovery should reset encrypted bio (can't decrypt with old key)."""
        reg_result = user_service.register(
            display_name="Test User",
            password="oldpassword123",
            short_bio="Important bio that will be lost",
        )
        recovery_phrase = reg_result.recovery_phrase
        user_service.logout()

        user_service.recover_account(
            recovery_phrase=recovery_phrase,
            new_password="newpassword456",
        )

        card = user_service.get_user_card()
        assert card.bio.short_bio == ""  # Reset to empty

    def test_recover_account_wrong_phrase(self, user_service: UserService) -> None:
        """Wrong recovery phrase should fail."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )
        user_service.logout()

        with pytest.raises(RecoveryError):
            user_service.recover_account(
                recovery_phrase="wrong phrase here",
                new_password="newpassword456",
            )

    def test_generate_new_recovery_phrase(self, user_service: UserService) -> None:
        """Generating new recovery phrase should invalidate old one."""
        reg_result = user_service.register(
            display_name="Test User",
            password="mypassword123",
        )
        old_phrase = reg_result.recovery_phrase

        new_phrase = user_service.generate_new_recovery_phrase()

        assert new_phrase != old_phrase
        assert len(new_phrase.split()) == 8

        # Old phrase should no longer work
        user_service.logout()
        with pytest.raises(RecoveryError):
            user_service.recover_account(
                recovery_phrase=old_phrase,
                new_password="newpassword456",
            )

        # New phrase should work
        user_service.recover_account(
            recovery_phrase=new_phrase,
            new_password="newpassword456",
        )


class TestSessionManagement:
    """Tests for session management."""

    def test_logout_invalidates_session(self, user_service: UserService) -> None:
        """Logout should invalidate the current session."""
        result = user_service.register(
            display_name="Test User",
            password="mypassword123",
        )

        session_before = user_service.get_session(result.session_id)
        assert session_before is not None

        user_service.logout()

        session_after = user_service.get_session(result.session_id)
        assert session_after is None

    def test_require_session_without_login(self, user_service: UserService) -> None:
        """require_session without active session should raise."""
        with pytest.raises(SessionError):
            user_service.require_session()

    def test_has_user(self, user_service: UserService) -> None:
        """has_user should return correct state."""
        assert user_service.has_user() is False

        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )

        assert user_service.has_user() is True


class TestAccountDeletion:
    """Tests for account deletion."""

    def test_delete_account_success(self, user_service: UserService, temp_db: Database) -> None:
        """Deleting account should remove all user data."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )

        user_service.delete_account(password="mypassword123")

        assert user_service.has_user() is False
        assert temp_db.count_users() == 0

    def test_delete_account_wrong_password(self, user_service: UserService) -> None:
        """Deleting with wrong password should fail."""
        user_service.register(
            display_name="Test User",
            password="mypassword123",
        )

        with pytest.raises(AuthenticationError):
            user_service.delete_account(password="wrongpassword")


# ============================================================================
# Database Tests
# ============================================================================


class TestUserDatabaseOperations:
    """Tests for user-related database operations."""

    def test_create_and_get_user(self, temp_db: Database) -> None:
        """Creating and retrieving a user should work."""
        temp_db.create_user(user_id="usr_test123", display_name="Test User")

        user = temp_db.get_user(user_id="usr_test123")

        assert user is not None
        assert user["display_name"] == "Test User"

    def test_update_user(self, temp_db: Database) -> None:
        """Updating user should modify fields."""
        temp_db.create_user(user_id="usr_test123", display_name="Original Name")

        temp_db.update_user(user_id="usr_test123", display_name="New Name")

        user = temp_db.get_user(user_id="usr_test123")
        assert user is not None
        assert user["display_name"] == "New Name"

    def test_user_credentials(self, temp_db: Database) -> None:
        """Creating and retrieving credentials should work."""
        temp_db.create_user(user_id="usr_test123", display_name="Test User")
        temp_db.create_user_credentials(
            credential_id="cred_123",
            user_id="usr_test123",
            password_hash="$argon2id$...",
            key_salt=base64.b64encode(b"salt").decode(),
            recovery_phrase_hash="abc123",
        )

        creds = temp_db.get_user_credentials(user_id="usr_test123")

        assert creds is not None
        assert creds["password_hash"] == "$argon2id$..."
        assert creds["recovery_phrase_hash"] == "abc123"

    def test_user_encrypted_data(self, temp_db: Database) -> None:
        """Storing and retrieving encrypted data should work."""
        temp_db.create_user(user_id="usr_test123", display_name="Test User")
        temp_db.upsert_user_encrypted_data(
            data_id="data_123",
            user_id="usr_test123",
            data_type="bio",
            encrypted_data="encrypted_content_here",
        )

        data = temp_db.get_user_encrypted_data(user_id="usr_test123", data_type="bio")

        assert data is not None
        assert data["encrypted_data"] == "encrypted_content_here"

    def test_user_sessions(self, temp_db: Database) -> None:
        """Creating and managing sessions should work."""
        temp_db.create_user(user_id="usr_test123", display_name="Test User")
        temp_db.create_user_session(
            session_id="ses_abc",
            user_id="usr_test123",
            expires_at="2099-12-31T23:59:59Z",
        )

        session = temp_db.get_user_session(session_id="ses_abc")

        assert session is not None
        assert session["user_id"] == "usr_test123"
        assert session["is_valid"] == 1

        temp_db.invalidate_user_session(session_id="ses_abc")

        session = temp_db.get_user_session(session_id="ses_abc")
        assert session is not None
        assert session["is_valid"] == 0

    def test_delete_user_cascades(self, temp_db: Database) -> None:
        """Deleting user should cascade to related data."""
        temp_db.create_user(user_id="usr_test123", display_name="Test User")
        temp_db.create_user_credentials(
            credential_id="cred_123",
            user_id="usr_test123",
            password_hash="hash",
            key_salt="salt",
        )
        temp_db.upsert_user_encrypted_data(
            data_id="data_123",
            user_id="usr_test123",
            data_type="bio",
            encrypted_data="data",
        )
        temp_db.create_user_session(
            session_id="ses_abc",
            user_id="usr_test123",
            expires_at="2099-12-31T23:59:59Z",
        )

        temp_db.delete_user(user_id="usr_test123")

        assert temp_db.get_user(user_id="usr_test123") is None
        assert temp_db.get_user_credentials(user_id="usr_test123") is None
        assert temp_db.get_user_encrypted_data(user_id="usr_test123", data_type="bio") is None
        assert temp_db.get_user_session(session_id="ses_abc") is None
