"""
Encryption utilities for multi-user support.
- Password hashing for user login (bcrypt-style with PBKDF2)
- Reversible encryption for sensitive data (AES) so coordinator can view
"""

import os
import base64
import hashlib
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Salt for coordinator key derivation (fixed, stored in code)
COORDINATOR_SALT = b'quantum_messaging_coordinator_v1'

# Salt file for user passwords
PASSWORD_SALT_LENGTH = 16


def _get_coordinator_key(coordinator_password: str) -> bytes:
    """Derive encryption key from coordinator password."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=COORDINATOR_SALT,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(coordinator_password.encode()))
    return key


def _get_fernet(coordinator_password: str) -> Fernet:
    """Get Fernet instance for encryption/decryption."""
    key = _get_coordinator_key(coordinator_password)
    return Fernet(key)


# Default coordinator password - loaded from environment or config
_coordinator_password = None


def set_coordinator_password(password: str):
    """Set the coordinator password for encryption operations."""
    global _coordinator_password
    _coordinator_password = password


def get_coordinator_password() -> str:
    """Get the coordinator password."""
    global _coordinator_password
    if _coordinator_password is None:
        # Try environment variable
        _coordinator_password = os.environ.get('QM_COORDINATOR_PASSWORD')
    return _coordinator_password


def encrypt_value(value: str, coordinator_password: str = None) -> str:
    """Encrypt a value using coordinator password."""
    if not value:
        return ''
    password = coordinator_password or get_coordinator_password()
    if not password:
        raise ValueError("Coordinator password not set")
    f = _get_fernet(password)
    encrypted = f.encrypt(value.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_value(encrypted_value: str, coordinator_password: str = None) -> str:
    """Decrypt a value using coordinator password."""
    if not encrypted_value:
        return ''
    password = coordinator_password or get_coordinator_password()
    if not password:
        raise ValueError("Coordinator password not set")
    try:
        f = _get_fernet(password)
        encrypted = base64.urlsafe_b64decode(encrypted_value.encode())
        decrypted = f.decrypt(encrypted)
        return decrypted.decode()
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


def hash_password(password: str) -> str:
    """Hash a password for storage (one-way, for user login)."""
    salt = secrets.token_bytes(PASSWORD_SALT_LENGTH)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against stored hash."""
    try:
        decoded = base64.b64decode(stored_hash.encode())
        salt = decoded[:PASSWORD_SALT_LENGTH]
        stored_key = decoded[PASSWORD_SALT_LENGTH:]
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        return secrets.compare_digest(key, stored_key)
    except Exception:
        return False


def hash_coordinator_password(password: str) -> str:
    """Hash coordinator password for storage in config."""
    return hash_password(password)


def verify_coordinator_password(password: str, stored_hash: str) -> bool:
    """Verify coordinator password."""
    return verify_password(password, stored_hash)
