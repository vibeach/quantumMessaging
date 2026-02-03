"""
Multi-user support module for Quantum Messaging.
Handles user authentication, per-user databases, and Telegram session management.
"""

from .encryption import encrypt_value, decrypt_value, hash_password, verify_password, set_coordinator_password
from .user_manager import UserManager
from .auth import init_auth_routes

__all__ = [
    'encrypt_value',
    'decrypt_value',
    'hash_password',
    'verify_password',
    'set_coordinator_password',
    'UserManager',
    'init_auth_routes'
]
