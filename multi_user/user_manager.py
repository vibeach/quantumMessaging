"""
User management for multi-user Quantum Messaging.
Handles user accounts, Telegram configurations, and per-user databases.
"""

import os
import sqlite3
import shutil
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

from .encryption import (
    encrypt_value, decrypt_value,
    hash_password, verify_password,
    get_coordinator_password
)


class UserManager:
    """Manages users, their configs, and databases."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.master_db_path = os.path.join(data_dir, 'master.db')
        self.users_dir = os.path.join(data_dir, 'users')

        # Ensure directories exist
        os.makedirs(self.users_dir, exist_ok=True)

        # Initialize master database
        self._init_master_db()

    @contextmanager
    def _get_master_connection(self):
        """Get connection to master database."""
        conn = sqlite3.connect(self.master_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_master_db(self):
        """Initialize master database schema."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_encrypted TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Telegram configuration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telegram_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    api_id_encrypted TEXT,
                    api_hash_encrypted TEXT,
                    phone_encrypted TEXT,
                    target_username TEXT,
                    target_display_name TEXT,
                    session_created INTEGER DEFAULT 0,
                    setup_complete INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # Monitor status
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitor_status (
                    user_id INTEGER PRIMARY KEY,
                    is_running INTEGER DEFAULT 0,
                    last_heartbeat DATETIME,
                    last_error TEXT,
                    messages_today INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # Migration: Add session_string_encrypted column if not exists
            try:
                cursor.execute("ALTER TABLE telegram_config ADD COLUMN session_string_encrypted TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()

    def create_user(self, username: str, password: str) -> Optional[int]:
        """Create a new user account."""
        username = username.lower().strip()

        if not username or not password:
            return None

        # Validate username (alphanumeric + underscore only)
        if not username.replace('_', '').isalnum():
            return None

        coordinator_pwd = get_coordinator_password()

        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            try:
                # Hash password for login verification
                pwd_hash = hash_password(password)

                # Also encrypt password so coordinator can see it
                pwd_encrypted = encrypt_value(password, coordinator_pwd) if coordinator_pwd else ''

                cursor.execute("""
                    INSERT INTO users (username, password_hash, password_encrypted)
                    VALUES (?, ?, ?)
                """, (username, pwd_hash, pwd_encrypted))

                user_id = cursor.lastrowid

                # Create telegram_config entry
                cursor.execute("""
                    INSERT INTO telegram_config (user_id)
                    VALUES (?)
                """, (user_id,))

                # Create monitor_status entry
                cursor.execute("""
                    INSERT INTO monitor_status (user_id)
                    VALUES (?)
                """, (user_id,))

                conn.commit()

                # Create user's data directory
                user_dir = os.path.join(self.users_dir, username)
                os.makedirs(user_dir, exist_ok=True)

                # Initialize user's database
                self._init_user_db(username)

                return user_id

            except sqlite3.IntegrityError:
                # Username already exists
                return None

    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user and return user info if valid."""
        username = username.lower().strip()

        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, password_hash, is_active
                FROM users WHERE username = ?
            """, (username,))
            row = cursor.fetchone()

            if not row:
                return None

            if not row['is_active']:
                return None

            if not verify_password(password, row['password_hash']):
                return None

            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = ? WHERE id = ?
            """, (datetime.utcnow().isoformat(), row['id']))
            conn.commit()

            return {
                'id': row['id'],
                'username': row['username']
            }

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate a user account (soft delete)."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET is_active = 0 WHERE id = ?
            """, (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, created_at, last_login, is_active
                FROM users WHERE id = ?
            """, (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username."""
        username = username.lower().strip()
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, created_at, last_login, is_active
                FROM users WHERE username = ?
            """, (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> List[Dict]:
        """Get all users."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.created_at, u.last_login, u.is_active,
                       tc.setup_complete, ms.is_running, ms.last_heartbeat
                FROM users u
                LEFT JOIN telegram_config tc ON u.id = tc.user_id
                LEFT JOIN monitor_status ms ON u.id = ms.user_id
                ORDER BY u.created_at
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_telegram_config(self, user_id: int, decrypt: bool = False) -> Optional[Dict]:
        """Get user's Telegram configuration."""
        coordinator_pwd = get_coordinator_password() if decrypt else None

        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM telegram_config WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()

            if not row:
                return None

            config = dict(row)

            if decrypt and coordinator_pwd:
                try:
                    config['api_id'] = decrypt_value(config.get('api_id_encrypted', ''), coordinator_pwd)
                    config['api_hash'] = decrypt_value(config.get('api_hash_encrypted', ''), coordinator_pwd)
                    config['phone'] = decrypt_value(config.get('phone_encrypted', ''), coordinator_pwd)
                except Exception:
                    pass

            return config

    def save_telegram_config(self, user_id: int, api_id: str, api_hash: str,
                            phone: str, target_username: str = None,
                            target_display_name: str = None) -> bool:
        """Save user's Telegram configuration (encrypted)."""
        coordinator_pwd = get_coordinator_password()
        if not coordinator_pwd:
            raise ValueError("Coordinator password not set")

        with self._get_master_connection() as conn:
            cursor = conn.cursor()

            # Encrypt sensitive values
            api_id_enc = encrypt_value(api_id, coordinator_pwd)
            api_hash_enc = encrypt_value(api_hash, coordinator_pwd)
            phone_enc = encrypt_value(phone, coordinator_pwd)

            cursor.execute("""
                UPDATE telegram_config
                SET api_id_encrypted = ?,
                    api_hash_encrypted = ?,
                    phone_encrypted = ?,
                    target_username = ?,
                    target_display_name = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (api_id_enc, api_hash_enc, phone_enc,
                  target_username, target_display_name,
                  datetime.utcnow().isoformat(), user_id))

            conn.commit()
            return cursor.rowcount > 0

    def mark_session_created(self, user_id: int) -> bool:
        """Mark that Telegram session has been created."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE telegram_config
                SET session_created = 1, updated_at = ?
                WHERE user_id = ?
            """, (datetime.utcnow().isoformat(), user_id))
            conn.commit()
            return cursor.rowcount > 0

    def save_session_string(self, user_id: int, session_string: str) -> bool:
        """Save encrypted session string for a user."""
        coordinator_pwd = get_coordinator_password()
        if not coordinator_pwd:
            raise ValueError("Coordinator password not set")

        with self._get_master_connection() as conn:
            cursor = conn.cursor()

            session_enc = encrypt_value(session_string, coordinator_pwd)

            cursor.execute("""
                UPDATE telegram_config
                SET session_string_encrypted = ?, session_created = 1, updated_at = ?
                WHERE user_id = ?
            """, (session_enc, datetime.utcnow().isoformat(), user_id))

            conn.commit()
            return cursor.rowcount > 0

    def get_session_string(self, user_id: int) -> Optional[str]:
        """Get decrypted session string for a user."""
        coordinator_pwd = get_coordinator_password()

        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_string_encrypted FROM telegram_config WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()

            if not row or not row['session_string_encrypted']:
                return None

            if coordinator_pwd:
                try:
                    return decrypt_value(row['session_string_encrypted'], coordinator_pwd)
                except Exception:
                    return None
            return None

    def mark_setup_complete(self, user_id: int) -> bool:
        """Mark that user setup is complete."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE telegram_config
                SET setup_complete = 1, updated_at = ?
                WHERE user_id = ?
            """, (datetime.utcnow().isoformat(), user_id))
            conn.commit()
            return cursor.rowcount > 0

    def is_setup_complete(self, user_id: int) -> bool:
        """Check if user has completed setup."""
        config = self.get_telegram_config(user_id)
        return config and config.get('setup_complete', 0) == 1

    def get_user_data_dir(self, username: str) -> str:
        """Get path to user's data directory."""
        return os.path.join(self.users_dir, username.lower())

    def get_user_db_path(self, username: str) -> str:
        """Get path to user's database."""
        return os.path.join(self.get_user_data_dir(username), 'telegram.db')

    def get_user_session_path(self, username: str) -> str:
        """Get path to user's Telegram session file."""
        return os.path.join(self.get_user_data_dir(username), f'{username.lower()}')

    def _init_user_db(self, username: str):
        """Initialize a user's message database."""
        db_path = self.get_user_db_path(username)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Messages table (same schema as original)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                sender_id INTEGER,
                sender_name TEXT,
                text TEXT,
                media_type TEXT,
                media_path TEXT,
                timestamp DATETIME,
                deleted INTEGER DEFAULT 0,
                deleted_at DATETIME,
                marked_read INTEGER DEFAULT 0,
                marked_read_at DATETIME,
                seen_by_target INTEGER DEFAULT 0,
                seen_by_target_at DATETIME,
                reactions TEXT,
                media_duration REAL,
                media_width INTEGER,
                media_height INTEGER,
                media_size INTEGER,
                media_thumbnail TEXT,
                transcript TEXT,
                transcript_status TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, chat_id)
            )
        """)

        # Online status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT,
                last_seen DATETIME,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pending actions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                reply_to_message_id INTEGER,
                media_path TEXT,
                media_type TEXT,
                scheduled_at DATETIME,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                sent_at DATETIME,
                message_id INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_reads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_deletes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")

        conn.commit()
        conn.close()

    def update_monitor_status(self, user_id: int, is_running: bool = None,
                             last_error: str = None, messages_today: int = None):
        """Update monitor status for a user."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()

            updates = ["last_heartbeat = ?"]
            params = [datetime.utcnow().isoformat()]

            if is_running is not None:
                updates.append("is_running = ?")
                params.append(1 if is_running else 0)

            if last_error is not None:
                updates.append("last_error = ?")
                params.append(last_error)

            if messages_today is not None:
                updates.append("messages_today = ?")
                params.append(messages_today)

            params.append(user_id)

            cursor.execute(f"""
                UPDATE monitor_status
                SET {', '.join(updates)}
                WHERE user_id = ?
            """, params)

            conn.commit()

    def get_users_for_monitoring(self) -> List[Dict]:
        """Get all users with complete setup for monitoring."""
        coordinator_pwd = get_coordinator_password()

        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username,
                       tc.api_id_encrypted, tc.api_hash_encrypted, tc.phone_encrypted,
                       tc.target_username, tc.target_display_name, tc.session_string_encrypted
                FROM users u
                JOIN telegram_config tc ON u.id = tc.user_id
                WHERE u.is_active = 1 AND tc.setup_complete = 1
            """)

            users = []
            for row in cursor.fetchall():
                user = dict(row)
                if coordinator_pwd:
                    try:
                        user['api_id'] = decrypt_value(user.get('api_id_encrypted', ''), coordinator_pwd)
                        user['api_hash'] = decrypt_value(user.get('api_hash_encrypted', ''), coordinator_pwd)
                        user['phone'] = decrypt_value(user.get('phone_encrypted', ''), coordinator_pwd)
                        if user.get('session_string_encrypted'):
                            user['session_string'] = decrypt_value(user['session_string_encrypted'], coordinator_pwd)
                    except Exception:
                        continue
                users.append(user)

            return users

    def get_all_credentials(self, coordinator_password: str) -> List[Dict]:
        """Get all users with decrypted credentials (for admin script)."""
        with self._get_master_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.password_encrypted, u.created_at, u.last_login,
                       tc.api_id_encrypted, tc.api_hash_encrypted, tc.phone_encrypted,
                       tc.target_username, tc.target_display_name, tc.setup_complete,
                       tc.session_string_encrypted,
                       ms.is_running, ms.last_heartbeat, ms.messages_today
                FROM users u
                LEFT JOIN telegram_config tc ON u.id = tc.user_id
                LEFT JOIN monitor_status ms ON u.id = ms.user_id
                ORDER BY u.created_at
            """)

            users = []
            for row in cursor.fetchall():
                user = dict(row)
                try:
                    user['password'] = decrypt_value(user.get('password_encrypted', ''), coordinator_password)
                    user['api_id'] = decrypt_value(user.get('api_id_encrypted', ''), coordinator_password)
                    user['api_hash'] = decrypt_value(user.get('api_hash_encrypted', ''), coordinator_password)
                    user['phone'] = decrypt_value(user.get('phone_encrypted', ''), coordinator_password)
                    if user.get('session_string_encrypted'):
                        user['session_string'] = decrypt_value(user['session_string_encrypted'], coordinator_password)
                except Exception as e:
                    user['decrypt_error'] = str(e)
                users.append(user)

            return users
