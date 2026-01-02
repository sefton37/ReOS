"""Cryptographic primitives for user presence and zero-trust security.

This module provides production-ready cryptographic operations:
- Password hashing with Argon2id (OWASP recommended)
- Key derivation with HKDF-SHA256
- Authenticated encryption with ChaCha20-Poly1305
- Recovery passphrase generation (BIP39-style word list)
- Secure random generation

All operations are designed for local-first, zero-trust architecture.
Keys are derived from user passwords and never stored directly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Argon2 parameters (OWASP 2024 recommendations for Argon2id)
# Memory: 64 MiB, Iterations: 3, Parallelism: 4
ARGON2_MEMORY_COST = 65536  # 64 MiB in KiB
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16

# Encryption parameters
CHACHA20_KEY_LENGTH = 32
CHACHA20_NONCE_LENGTH = 12
HKDF_INFO_ENCRYPTION = b"reos-encryption-key-v1"
HKDF_INFO_AUTH = b"reos-auth-key-v1"

# Recovery passphrase word list (BIP39 subset - 256 common words for 8-word phrases)
# 8 words from 256-word list = 64 bits of entropy (sufficient for recovery)
RECOVERY_WORDLIST = [
    "abandon", "ability", "able", "about", "above", "absent", "absorb", "abstract",
    "absurd", "abuse", "access", "account", "accuse", "achieve", "acid", "across",
    "action", "actor", "actress", "actual", "adapt", "address", "adjust", "admit",
    "adult", "advance", "advice", "aerobic", "affair", "afford", "afraid", "again",
    "age", "agent", "agree", "ahead", "aim", "air", "airport", "aisle",
    "alarm", "album", "alcohol", "alert", "alien", "alive", "alley", "allow",
    "almost", "alone", "alpha", "already", "also", "alter", "always", "amateur",
    "amazing", "among", "amount", "amused", "anchor", "ancient", "anger", "angle",
    "angry", "animal", "ankle", "announce", "annual", "another", "answer", "antenna",
    "antique", "anxiety", "apart", "apology", "appear", "apple", "approve", "april",
    "arch", "arctic", "arena", "argue", "arise", "armor", "army", "around",
    "arrange", "arrest", "arrive", "arrow", "artist", "artwork", "aspect", "assault",
    "asset", "assist", "assume", "asthma", "athlete", "atom", "attack", "attend",
    "auction", "audit", "august", "aunt", "author", "autumn", "average", "avocado",
    "avoid", "awake", "aware", "awkward", "baby", "bachelor", "bacon", "badge",
    "balance", "balcony", "bamboo", "banana", "banner", "barely", "bargain", "barrel",
    "basic", "basket", "battle", "beach", "beauty", "become", "beef", "before",
    "begin", "behave", "behind", "believe", "bench", "benefit", "best", "betray",
    "better", "between", "beyond", "bicycle", "bitter", "blanket", "bless", "blind",
    "blood", "blossom", "blouse", "blue", "board", "boat", "body", "boil",
    "bomb", "bone", "bonus", "book", "boost", "border", "boring", "borrow",
    "boss", "bottom", "bounce", "box", "bracket", "brain", "brand", "brass",
    "brave", "bread", "breeze", "brick", "bridge", "brief", "bright", "bring",
    "brisk", "broccoli", "broken", "bronze", "broom", "brother", "brown", "brush",
    "bubble", "buddy", "budget", "buffalo", "build", "bullet", "bundle", "bunker",
    "burden", "burger", "burst", "bus", "business", "butter", "buyer", "cabbage",
    "cabin", "cable", "cactus", "cage", "cake", "call", "calm", "camera",
    "camp", "canal", "cancel", "candy", "cannon", "canvas", "canyon", "capable",
    "capital", "captain", "carbon", "card", "cargo", "carpet", "carry", "cart",
    "case", "casino", "castle", "casual", "catalog", "catch", "category", "cattle",
    "caught", "cause", "caution", "cave", "ceiling", "celery", "cement", "census",
    "century", "cereal", "certain", "chair", "chalk", "champion", "change", "chaos",
]

# Ensure we have exactly 256 words for clean byte indexing
assert len(RECOVERY_WORDLIST) == 256, f"Word list must have 256 words, got {len(RECOVERY_WORDLIST)}"


class CryptoError(Exception):
    """Base exception for cryptographic operations."""

    pass


class DecryptionError(CryptoError):
    """Raised when decryption fails (wrong key, tampered data, etc.)."""

    pass


class PasswordHashError(CryptoError):
    """Raised when password hashing/verification fails."""

    pass


@dataclass(frozen=True, slots=True)
class HashedPassword:
    """Represents a hashed password with its salt and parameters.

    Format: $argon2id$v=19$m=MEMORY,t=TIME,p=PARALLEL$SALT_B64$HASH_B64
    """

    algorithm: str
    version: int
    memory_cost: int
    time_cost: int
    parallelism: int
    salt: bytes
    hash: bytes

    def encode(self) -> str:
        """Encode to PHC string format for storage."""
        salt_b64 = base64.b64encode(self.salt).decode("ascii").rstrip("=")
        hash_b64 = base64.b64encode(self.hash).decode("ascii").rstrip("=")
        return (
            f"${self.algorithm}$v={self.version}$"
            f"m={self.memory_cost},t={self.time_cost},p={self.parallelism}$"
            f"{salt_b64}${hash_b64}"
        )

    @classmethod
    def decode(cls, encoded: str) -> "HashedPassword":
        """Decode from PHC string format."""
        try:
            parts = encoded.split("$")
            if len(parts) != 6 or parts[0] != "":
                raise ValueError("Invalid PHC format")

            algorithm = parts[1]
            if algorithm != "argon2id":
                raise ValueError(f"Unsupported algorithm: {algorithm}")

            version_part = parts[2]
            if not version_part.startswith("v="):
                raise ValueError("Missing version")
            version = int(version_part[2:])

            params_part = parts[3]
            params = {}
            for param in params_part.split(","):
                key, val = param.split("=")
                params[key] = int(val)

            # Restore base64 padding
            salt_b64 = parts[4]
            hash_b64 = parts[5]
            salt_b64 += "=" * (-len(salt_b64) % 4)
            hash_b64 += "=" * (-len(hash_b64) % 4)

            return cls(
                algorithm=algorithm,
                version=version,
                memory_cost=params["m"],
                time_cost=params["t"],
                parallelism=params["p"],
                salt=base64.b64decode(salt_b64),
                hash=base64.b64decode(hash_b64),
            )
        except Exception as e:
            raise PasswordHashError(f"Failed to decode password hash: {e}") from e


@dataclass(frozen=True, slots=True)
class EncryptedData:
    """Represents encrypted data with nonce and authentication tag.

    Format: VERSION (1 byte) || NONCE (12 bytes) || CIPHERTEXT+TAG
    """

    version: int
    nonce: bytes
    ciphertext: bytes  # Includes authentication tag

    def encode(self) -> bytes:
        """Encode to bytes for storage."""
        return bytes([self.version]) + self.nonce + self.ciphertext

    def encode_base64(self) -> str:
        """Encode to base64 string for JSON storage."""
        return base64.b64encode(self.encode()).decode("ascii")

    @classmethod
    def decode(cls, data: bytes) -> "EncryptedData":
        """Decode from bytes."""
        if len(data) < 1 + CHACHA20_NONCE_LENGTH + 16:  # version + nonce + min tag
            raise DecryptionError("Encrypted data too short")

        version = data[0]
        if version != 1:
            raise DecryptionError(f"Unsupported encryption version: {version}")

        nonce = data[1 : 1 + CHACHA20_NONCE_LENGTH]
        ciphertext = data[1 + CHACHA20_NONCE_LENGTH :]

        return cls(version=version, nonce=nonce, ciphertext=ciphertext)

    @classmethod
    def decode_base64(cls, data: str) -> "EncryptedData":
        """Decode from base64 string."""
        try:
            return cls.decode(base64.b64decode(data))
        except Exception as e:
            raise DecryptionError(f"Failed to decode encrypted data: {e}") from e


@dataclass(frozen=True, slots=True)
class DerivedKeys:
    """Keys derived from a master secret for different purposes."""

    encryption_key: bytes
    auth_key: bytes


def generate_salt(length: int = ARGON2_SALT_LENGTH) -> bytes:
    """Generate cryptographically secure random salt."""
    return os.urandom(length)


def generate_nonce(length: int = CHACHA20_NONCE_LENGTH) -> bytes:
    """Generate cryptographically secure random nonce."""
    return os.urandom(length)


def _argon2id_hash(
    password: bytes,
    salt: bytes,
    memory_cost: int = ARGON2_MEMORY_COST,
    time_cost: int = ARGON2_TIME_COST,
    parallelism: int = ARGON2_PARALLELISM,
    hash_length: int = ARGON2_HASH_LENGTH,
) -> bytes:
    """Compute Argon2id hash using the argon2-cffi library."""
    try:
        from argon2.low_level import Type, hash_secret_raw

        return hash_secret_raw(
            secret=password,
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_length,
            type=Type.ID,
        )
    except ImportError as e:
        raise CryptoError(
            "argon2-cffi library not installed. Run: pip install argon2-cffi"
        ) from e


def hash_password(password: str, salt: bytes | None = None) -> HashedPassword:
    """Hash a password using Argon2id.

    Args:
        password: The plaintext password to hash
        salt: Optional salt (generated if not provided)

    Returns:
        HashedPassword object containing the hash and parameters
    """
    if not password:
        raise PasswordHashError("Password cannot be empty")

    if salt is None:
        salt = generate_salt()

    password_bytes = password.encode("utf-8")
    hash_bytes = _argon2id_hash(password_bytes, salt)

    return HashedPassword(
        algorithm="argon2id",
        version=19,  # Argon2 version 1.3
        memory_cost=ARGON2_MEMORY_COST,
        time_cost=ARGON2_TIME_COST,
        parallelism=ARGON2_PARALLELISM,
        salt=salt,
        hash=hash_bytes,
    )


def verify_password(password: str, hashed: HashedPassword) -> bool:
    """Verify a password against a hash.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        password: The plaintext password to verify
        hashed: The HashedPassword to verify against

    Returns:
        True if the password matches, False otherwise
    """
    if not password:
        return False

    try:
        password_bytes = password.encode("utf-8")
        computed_hash = _argon2id_hash(
            password_bytes,
            hashed.salt,
            memory_cost=hashed.memory_cost,
            time_cost=hashed.time_cost,
            parallelism=hashed.parallelism,
            hash_length=len(hashed.hash),
        )
        return hmac.compare_digest(computed_hash, hashed.hash)
    except Exception:
        return False


def _hkdf_expand(key: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-Expand using SHA-256.

    Simplified HKDF for key derivation from already-strong key material.
    """
    hash_len = 32  # SHA-256 output length
    n = (length + hash_len - 1) // hash_len

    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac.new(key, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t

    return okm[:length]


def derive_keys_from_password(password: str, salt: bytes) -> DerivedKeys:
    """Derive encryption and authentication keys from a password.

    Uses Argon2id for initial key derivation, then HKDF for key separation.

    Args:
        password: The user's password
        salt: A unique salt for this user (stored with user record)

    Returns:
        DerivedKeys containing separate encryption and auth keys
    """
    # First, derive a master key using Argon2id
    master_key = _argon2id_hash(password.encode("utf-8"), salt)

    # Then derive separate keys using HKDF
    encryption_key = _hkdf_expand(master_key, HKDF_INFO_ENCRYPTION, CHACHA20_KEY_LENGTH)
    auth_key = _hkdf_expand(master_key, HKDF_INFO_AUTH, CHACHA20_KEY_LENGTH)

    return DerivedKeys(encryption_key=encryption_key, auth_key=auth_key)


def _chacha20_poly1305_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Encrypt using ChaCha20-Poly1305 AEAD."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        cipher = ChaCha20Poly1305(key)
        return cipher.encrypt(nonce, plaintext, aad)
    except ImportError as e:
        raise CryptoError(
            "cryptography library not installed. Run: pip install cryptography"
        ) from e


def _chacha20_poly1305_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    """Decrypt using ChaCha20-Poly1305 AEAD."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        cipher = ChaCha20Poly1305(key)
        return cipher.decrypt(nonce, ciphertext, aad)
    except ImportError as e:
        raise CryptoError(
            "cryptography library not installed. Run: pip install cryptography"
        ) from e
    except Exception as e:
        raise DecryptionError(f"Decryption failed: {e}") from e


def encrypt(plaintext: str | bytes, key: bytes, aad: bytes = b"") -> EncryptedData:
    """Encrypt data using ChaCha20-Poly1305.

    Args:
        plaintext: Data to encrypt (string will be UTF-8 encoded)
        key: 32-byte encryption key
        aad: Additional authenticated data (optional)

    Returns:
        EncryptedData containing nonce and ciphertext
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    if len(key) != CHACHA20_KEY_LENGTH:
        raise CryptoError(f"Key must be {CHACHA20_KEY_LENGTH} bytes")

    nonce = generate_nonce()
    ciphertext = _chacha20_poly1305_encrypt(key, nonce, plaintext, aad)

    return EncryptedData(version=1, nonce=nonce, ciphertext=ciphertext)


def decrypt(encrypted: EncryptedData, key: bytes, aad: bytes = b"") -> bytes:
    """Decrypt data using ChaCha20-Poly1305.

    Args:
        encrypted: EncryptedData to decrypt
        key: 32-byte encryption key
        aad: Additional authenticated data (must match encryption)

    Returns:
        Decrypted plaintext bytes

    Raises:
        DecryptionError: If decryption fails (wrong key, tampered data)
    """
    if len(key) != CHACHA20_KEY_LENGTH:
        raise CryptoError(f"Key must be {CHACHA20_KEY_LENGTH} bytes")

    return _chacha20_poly1305_decrypt(key, encrypted.nonce, encrypted.ciphertext, aad)


def decrypt_string(encrypted: EncryptedData, key: bytes, aad: bytes = b"") -> str:
    """Decrypt data and decode as UTF-8 string."""
    plaintext = decrypt(encrypted, key, aad)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DecryptionError(f"Decrypted data is not valid UTF-8: {e}") from e


def generate_recovery_passphrase(word_count: int = 8) -> str:
    """Generate a random recovery passphrase using BIP39-style words.

    Args:
        word_count: Number of words (8 = 64 bits entropy, 12 = 96 bits)

    Returns:
        Space-separated recovery passphrase
    """
    if word_count < 6:
        raise CryptoError("Recovery passphrase must have at least 6 words")

    # Generate random bytes (1 byte per word for 256-word list)
    random_bytes = os.urandom(word_count)

    # Map bytes to words
    words = [RECOVERY_WORDLIST[b] for b in random_bytes]

    return " ".join(words)


def hash_recovery_passphrase(passphrase: str) -> str:
    """Hash a recovery passphrase for storage verification.

    Uses SHA-256 for fast verification (passphrase already has high entropy).

    Args:
        passphrase: The recovery passphrase

    Returns:
        Hex-encoded SHA-256 hash
    """
    normalized = " ".join(passphrase.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_recovery_passphrase(passphrase: str, stored_hash: str) -> bool:
    """Verify a recovery passphrase against its stored hash.

    Uses constant-time comparison to prevent timing attacks.
    """
    computed_hash = hash_recovery_passphrase(passphrase)
    return hmac.compare_digest(computed_hash, stored_hash)


def derive_keys_from_recovery_passphrase(passphrase: str, salt: bytes) -> DerivedKeys:
    """Derive encryption keys from a recovery passphrase.

    This allows users to recover their encrypted data using their recovery phrase.

    Args:
        passphrase: The recovery passphrase
        salt: The user's unique salt

    Returns:
        DerivedKeys for decrypting user data
    """
    # Normalize passphrase
    normalized = " ".join(passphrase.lower().split())

    # Use Argon2id with the passphrase (less iterations since passphrase has high entropy)
    master_key = _argon2id_hash(
        normalized.encode("utf-8"),
        salt,
        memory_cost=32768,  # 32 MiB (lower since passphrase has ~64 bits entropy)
        time_cost=2,
        parallelism=4,
    )

    # Derive separate keys
    encryption_key = _hkdf_expand(master_key, HKDF_INFO_ENCRYPTION, CHACHA20_KEY_LENGTH)
    auth_key = _hkdf_expand(master_key, HKDF_INFO_AUTH, CHACHA20_KEY_LENGTH)

    return DerivedKeys(encryption_key=encryption_key, auth_key=auth_key)


def generate_user_id() -> str:
    """Generate a cryptographically secure user ID.

    Format: usr_XXXXXXXXXXXXXXXXXXXX (20 random hex chars = 80 bits)
    """
    random_bytes = os.urandom(10)
    return f"usr_{random_bytes.hex()}"


def secure_compare(a: str | bytes, b: str | bytes) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if isinstance(a, str):
        a = a.encode("utf-8")
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hmac.compare_digest(a, b)
