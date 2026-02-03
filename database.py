import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
import config


def utc_now():
    """Get current UTC time for consistent timestamps with Telegram."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def init_db():
    """Initialize the database with required tables."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add marked_read column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN marked_read INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN marked_read_at DATETIME")
        except:
            pass

        # Add seen_by_target column for tracking if target read our messages
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN seen_by_target INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN seen_by_target_at DATETIME")
        except:
            pass

        # Add reactions column (JSON string of reactions)
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN reactions TEXT")
        except:
            pass

        # Add transcript column for audio/video transcription
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN transcript TEXT")
        except:
            pass

        # Add transcript_status column (pending, completed, failed)
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN transcript_status TEXT")
        except:
            pass

        # Add media metadata columns
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_duration INTEGER")  # seconds
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_width INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_height INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_size INTEGER")  # bytes
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_thumbnail TEXT")  # path to thumbnail
        except:
            pass
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN media_snapshots TEXT")  # comma-separated paths to snapshots
        except:
            pass

        # Online status table
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

        # Outgoing message queue
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outgoing_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                sent_at DATETIME,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                reply_to_message_id INTEGER,
                scheduled_at DATETIME
            )
        """)

        # Add missing columns if they don't exist (migration)
        try:
            cursor.execute("ALTER TABLE outgoing_messages ADD COLUMN retry_count INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE outgoing_messages ADD COLUMN last_error TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE outgoing_messages ADD COLUMN reply_to_message_id INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE outgoing_messages ADD COLUMN scheduled_at DATETIME")
        except:
            pass

        # Pending read marks queue
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_read_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)

        # Pending reactions queue
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                chat_id INTEGER,
                emoji TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)

        # Pending deletes queue
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

        # Claude requests table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claude_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                status TEXT DEFAULT 'pending',
                response TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                mode TEXT DEFAULT 'api',
                model TEXT DEFAULT 'claude-sonnet-4-20250514',
                parent_id INTEGER,
                interrupted INTEGER DEFAULT 0,
                interrupted_at DATETIME,
                restart_count INTEGER DEFAULT 0
            )
        """)

        # Add columns if they don't exist (migration)
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN mode TEXT DEFAULT 'api'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN model TEXT DEFAULT 'claude-sonnet-4-20250514'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN parent_id INTEGER")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN auto_push BOOLEAN DEFAULT 1")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN interrupted INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN interrupted_at DATETIME")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE claude_requests ADD COLUMN restart_count INTEGER DEFAULT 0")
        except:
            pass

        # Add retry tracking for pending_reactions
        try:
            cursor.execute("ALTER TABLE pending_reactions ADD COLUMN retry_count INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE pending_reactions ADD COLUMN last_error TEXT")
        except:
            pass

        # Add retry tracking for pending_deletes
        try:
            cursor.execute("ALTER TABLE pending_deletes ADD COLUMN retry_count INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE pending_deletes ADD COLUMN last_error TEXT")
        except:
            pass

        # Claude log entries table (for detailed progress)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claude_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                log_type TEXT DEFAULT 'info',
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES claude_requests(id)
            )
        """)

        # AI prompts - customizable system prompts for different tones/approaches
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                system_prompt TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # AI suggestions - generated reply suggestions for incoming messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                prompt_id INTEGER,
                suggestions TEXT,
                context_used TEXT,
                tokens_used INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prompt_id) REFERENCES ai_prompts(id)
            )
        """)

        # AI conversations - Q&A chat history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tokens_used INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Conversation summaries - compressed context for efficient token usage
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                messages_covered INTEGER,
                start_date TEXT,
                end_date TEXT,
                key_facts TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # System logs - comprehensive logging for all dashboard activity
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT DEFAULT 'info',
                message TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Incept+ improvement suggestions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incept_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                implementation_details TEXT,
                category TEXT DEFAULT 'feature',
                priority INTEGER DEFAULT 3,
                status TEXT DEFAULT 'suggested',
                context TEXT,
                estimated_effort TEXT,
                dependencies TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                accepted_at DATETIME,
                rejected_at DATETIME,
                implemented_at DATETIME
            )
        """)

        # Incept+ implemented improvements tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incept_improvements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_id INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                implementation_summary TEXT,
                commit_hash TEXT,
                files_changed TEXT,
                enabled INTEGER DEFAULT 1,
                feature_flag TEXT,
                rollback_info TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                disabled_at DATETIME,
                FOREIGN KEY (suggestion_id) REFERENCES incept_suggestions(id)
            )
        """)

        # Incept+ auto-mode sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incept_auto_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'running',
                direction TEXT,
                max_suggestions INTEGER DEFAULT 10,
                suggestions_generated INTEGER DEFAULT 0,
                suggestions_implemented INTEGER DEFAULT 0,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                stopped_at DATETIME,
                last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Incept+ settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incept_plus_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auto_mode_enabled INTEGER DEFAULT 0,
                auto_mode_interval INTEGER DEFAULT 300,
                suggestion_mode TEXT DEFAULT 'cli',
                suggestion_model TEXT DEFAULT 'claude-sonnet-4-20250514',
                max_list_length INTEGER DEFAULT 10,
                auto_implement_approved INTEGER DEFAULT 1,
                queue_paused INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # AI Assistant settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT DEFAULT 'local',
                use_tailscale INTEGER DEFAULT 1,
                tailscale_url TEXT,
                local_url TEXT DEFAULT 'http://localhost:1234/v1',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ensure there's always one row
        cursor.execute("""
            INSERT OR IGNORE INTO ai_settings (id, provider, use_tailscale)
            VALUES (1, 'local', 1)
        """)

        # Push notification subscriptions table (for Web Push / iOS PWA)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                user_agent TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_used_at DATETIME,
                active INTEGER DEFAULT 1
            )
        """)

        # Migration: add suggestion_mode if not exists
        try:
            cursor.execute("ALTER TABLE incept_plus_settings ADD COLUMN suggestion_mode TEXT DEFAULT 'cli'")
        except:
            pass

        # Migration: add queue_paused if not exists
        try:
            cursor.execute("ALTER TABLE incept_plus_settings ADD COLUMN queue_paused INTEGER DEFAULT 0")
        except:
            pass  # Column already exists

        # Add columns for improvement tracking (migration)
        try:
            cursor.execute("ALTER TABLE incept_improvements ADD COLUMN unique_id TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incept_improvements ADD COLUMN pushed INTEGER DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE incept_improvements ADD COLUMN pushed_at DATETIME")
        except:
            pass

        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_user ON online_status(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_timestamp ON online_status(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_category ON system_logs(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp)")

        conn.commit()

@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def save_message(message_id, chat_id, sender_id, sender_name, text, media_type=None, media_path=None, timestamp=None, reactions=None, media_duration=None, media_width=None, media_height=None, media_size=None, media_thumbnail=None):
    """Save a new message to the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO messages
            (message_id, chat_id, sender_id, sender_name, text, media_type, media_path, timestamp, reactions, media_duration, media_width, media_height, media_size, media_thumbnail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (message_id, chat_id, sender_id, sender_name, text, media_type, media_path, timestamp or utc_now(), reactions, media_duration, media_width, media_height, media_size, media_thumbnail))
        conn.commit()
        return cursor.lastrowid

def mark_message_deleted(message_id, chat_id):
    """Mark a message as deleted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages
            SET deleted = 1, deleted_at = ?
            WHERE message_id = ? AND chat_id = ?
        """, (utc_now(), message_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0

def save_online_status(user_id, username, status, last_seen=None):
    """Save online/offline status change."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO online_status (user_id, username, status, last_seen)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, status, last_seen))
        conn.commit()
        return cursor.lastrowid

def get_messages(chat_id=None, limit=100, offset=0, include_deleted=False, direction=None):
    """Get messages, optionally filtered by chat and direction.

    Args:
        direction: 'incoming' for messages from her, 'outgoing' for messages from me
    Note: Deleted messages are excluded by default.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM messages"
        params = []

        conditions = []
        if chat_id:
            conditions.append("chat_id = ?")
            params.append(chat_id)
        if not include_deleted:
            conditions.append("deleted = 0")
        if direction:
            my_name = config.MY_NAME if hasattr(config, 'MY_NAME') else 'Me'
            if direction == 'incoming':
                conditions.append("sender_name != ?")
                params.append(my_name)
            elif direction == 'outgoing':
                conditions.append("sender_name = ?")
                params.append(my_name)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_online_history(user_id=None, limit=100, offset=0):
    """Get online/offline history."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM online_status"
        params = []

        if user_id:
            query += " WHERE user_id = ?"
            params.append(user_id)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_message_stats():
    """Get message statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM messages")
        total = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as deleted FROM messages WHERE deleted = 1")
        deleted = cursor.fetchone()['deleted']

        return {"total": total, "deleted": deleted, "active": total - deleted}


def get_unseen_stats(my_name):
    """Get unseen message stats for home page display."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # My messages not seen by her yet
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name = ? AND seen_by_target = 0 AND deleted = 0
        """, (my_name,))
        my_unseen = cursor.fetchone()['count']

        # Her messages I haven't seen yet
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name != ? AND (marked_read IS NULL OR marked_read = 0) AND deleted = 0
        """, (my_name,))
        her_unseen = cursor.fetchone()['count']

        # Unseen media from her (not from me)
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name != ? AND media_path IS NOT NULL AND media_path != ''
            AND (marked_read IS NULL OR marked_read = 0) AND deleted = 0
        """, (my_name,))
        media_unseen_her = cursor.fetchone()['count']

        # Unseen media from me (she hasn't seen)
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name = ? AND media_path IS NOT NULL AND media_path != ''
            AND seen_by_target = 0 AND deleted = 0
        """, (my_name,))
        media_unseen_me = cursor.fetchone()['count']

        # My messages today
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name = ? AND deleted = 0
            AND date(timestamp) = date('now', 'localtime')
        """, (my_name,))
        my_today = cursor.fetchone()['count']

        # Her messages today
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE sender_name != ? AND deleted = 0
            AND date(timestamp) = date('now', 'localtime')
        """, (my_name,))
        her_today = cursor.fetchone()['count']

        # Time since last message from me
        cursor.execute("""
            SELECT timestamp FROM messages
            WHERE sender_name = ? AND deleted = 0
            ORDER BY timestamp DESC LIMIT 1
        """, (my_name,))
        row = cursor.fetchone()
        my_last_msg_time = row['timestamp'] if row else None

        # Time since last message from her
        cursor.execute("""
            SELECT timestamp FROM messages
            WHERE sender_name != ? AND deleted = 0
            ORDER BY timestamp DESC LIMIT 1
        """, (my_name,))
        row = cursor.fetchone()
        her_last_msg_time = row['timestamp'] if row else None

        # Time since oldest unseen message from me (she hasn't seen)
        cursor.execute("""
            SELECT timestamp FROM messages
            WHERE sender_name = ? AND seen_by_target = 0 AND deleted = 0
            ORDER BY timestamp ASC LIMIT 1
        """, (my_name,))
        row = cursor.fetchone()
        my_oldest_unseen_time = row['timestamp'] if row else None

        # Time since oldest unseen message from her (I haven't seen)
        cursor.execute("""
            SELECT timestamp FROM messages
            WHERE sender_name != ? AND (marked_read IS NULL OR marked_read = 0) AND deleted = 0
            ORDER BY timestamp ASC LIMIT 1
        """, (my_name,))
        row = cursor.fetchone()
        her_oldest_unseen_time = row['timestamp'] if row else None

        return {
            'my_unseen': my_unseen,
            'her_unseen': her_unseen,
            'media_unseen_her': media_unseen_her,
            'media_unseen_me': media_unseen_me,
            'my_today': my_today,
            'her_today': her_today,
            'my_last_msg_time': my_last_msg_time,
            'her_last_msg_time': her_last_msg_time,
            'my_oldest_unseen_time': my_oldest_unseen_time,
            'her_oldest_unseen_time': her_oldest_unseen_time
        }


def get_latest_status(user_id):
    """Get the latest status for a user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM online_status
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_media_messages(limit=100, offset=0, media_type=None):
    """Get messages that have media attached."""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = "SELECT * FROM messages WHERE media_path IS NOT NULL AND media_path != ''"
        params = []

        if media_type:
            query += " AND media_type = ?"
            params.append(media_type)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_media_stats():
    """Get media statistics by type."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT media_type, COUNT(*) as count
            FROM messages
            WHERE media_path IS NOT NULL AND media_path != ''
            GROUP BY media_type
        """)
        return {row['media_type']: row['count'] for row in cursor.fetchall()}

def queue_outgoing_message(text, reply_to_message_id=None, scheduled_at=None):
    """Add a message to the outgoing queue.

    Args:
        text: The message text or MEDIA:type:filepath
        reply_to_message_id: Optional message ID to reply to
        scheduled_at: Optional datetime string to schedule the message (ISO format)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO outgoing_messages (text, status, reply_to_message_id, scheduled_at)
            VALUES (?, 'pending', ?, ?)
        """, (text, reply_to_message_id, scheduled_at))
        conn.commit()
        return cursor.lastrowid

def get_pending_messages():
    """Get all pending outgoing messages that are ready to be sent.

    Messages with scheduled_at in the future are not returned.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM outgoing_messages
            WHERE status = 'pending'
            AND (scheduled_at IS NULL OR scheduled_at <= ?)
            ORDER BY created_at ASC
        """, (utc_now(),))
        return [dict(row) for row in cursor.fetchall()]


def get_all_pending_messages():
    """Get all pending outgoing messages including scheduled ones."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM outgoing_messages
            WHERE status = 'pending'
            ORDER BY scheduled_at ASC NULLS FIRST, created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_scheduled_messages():
    """Get pending outgoing messages that are scheduled for the future."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM outgoing_messages
            WHERE status = 'pending'
            AND scheduled_at IS NOT NULL
            AND scheduled_at > ?
            ORDER BY scheduled_at ASC
        """, (utc_now(),))
        return [dict(row) for row in cursor.fetchall()]


def cancel_scheduled_message(msg_id):
    """Cancel a scheduled message by marking it as cancelled."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE outgoing_messages
            SET status = 'cancelled'
            WHERE id = ?
            AND status = 'pending'
            AND scheduled_at IS NOT NULL
        """, (msg_id,))
        conn.commit()
        return cursor.rowcount > 0

def mark_message_sent(message_id):
    """Mark an outgoing message as sent."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE outgoing_messages
            SET status = 'sent', sent_at = ?
            WHERE id = ?
        """, (utc_now(), message_id))
        conn.commit()


def mark_message_retry(message_id, error_msg, max_retries=5):
    """Increment retry count and mark as failed if max retries exceeded."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get current retry count
        cursor.execute("SELECT retry_count FROM outgoing_messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        current_retries = (row['retry_count'] or 0) if row else 0

        if current_retries >= max_retries:
            # Mark as failed
            cursor.execute("""
                UPDATE outgoing_messages
                SET status = 'failed', last_error = ?
                WHERE id = ?
            """, (error_msg[:500], message_id))
        else:
            # Increment retry count
            cursor.execute("""
                UPDATE outgoing_messages
                SET retry_count = retry_count + 1, last_error = ?
                WHERE id = ?
            """, (error_msg[:500], message_id))
        conn.commit()
        return current_retries + 1

def get_outgoing_messages(limit=50):
    """Get recent outgoing messages."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM outgoing_messages
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def queue_mark_read(message_id, chat_id):
    """Queue a message to be marked as read on Telegram."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Add to pending queue
        cursor.execute("""
            INSERT INTO pending_read_marks (message_id, chat_id, status)
            VALUES (?, ?, 'pending')
        """, (message_id, chat_id))
        conn.commit()
        return cursor.lastrowid

def get_pending_read_marks():
    """Get pending read mark requests."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM pending_read_marks
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

def complete_read_mark(mark_id, message_id, chat_id):
    """Mark a read request as completed and update the message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Update pending_read_marks
        cursor.execute("""
            UPDATE pending_read_marks
            SET status = 'completed', completed_at = ?
            WHERE id = ?
        """, (utc_now(), mark_id))
        # Update messages table
        cursor.execute("""
            UPDATE messages
            SET marked_read = 1, marked_read_at = ?
            WHERE message_id = ? AND chat_id = ?
        """, (utc_now(), message_id, chat_id))
        conn.commit()


def mark_seen_by_target(message_id, chat_id):
    """Mark a message as seen by target (they read our message)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages
            SET seen_by_target = 1, seen_by_target_at = ?
            WHERE message_id = ? AND chat_id = ? AND seen_by_target = 0
        """, (utc_now(), message_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0


# ==================== REACTIONS ====================

def queue_reaction(message_id, chat_id, emoji):
    """Queue a reaction to be sent on Telegram."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pending_reactions (message_id, chat_id, emoji, status)
            VALUES (?, ?, ?, 'pending')
        """, (message_id, chat_id, emoji))
        conn.commit()
        return cursor.lastrowid


def get_pending_reactions(max_retries=3):
    """Get pending reaction requests (excluding those that failed too many times)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM pending_reactions
            WHERE status = 'pending' AND (retry_count IS NULL OR retry_count < ?)
            ORDER BY created_at ASC
        """, (max_retries,))
        return [dict(row) for row in cursor.fetchall()]


def complete_reaction(react_id):
    """Mark a reaction request as completed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pending_reactions
            SET status = 'completed', completed_at = ?
            WHERE id = ?
        """, (utc_now(), react_id))
        conn.commit()


def fail_reaction(react_id, error_message=None):
    """Increment retry count for a failed reaction. After 3 retries, marks as failed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get current retry count
        cursor.execute("SELECT retry_count FROM pending_reactions WHERE id = ?", (react_id,))
        row = cursor.fetchone()
        current_retry = (row['retry_count'] or 0) if row else 0

        if current_retry >= 2:  # After 3 attempts (0, 1, 2), mark as failed
            cursor.execute("""
                UPDATE pending_reactions
                SET status = 'failed', retry_count = ?, last_error = ?, completed_at = ?
                WHERE id = ?
            """, (current_retry + 1, error_message, utc_now(), react_id))
        else:
            cursor.execute("""
                UPDATE pending_reactions
                SET retry_count = ?, last_error = ?
                WHERE id = ?
            """, (current_retry + 1, error_message, react_id))
        conn.commit()
        return current_retry + 1


# ==================== DELETES ====================

def queue_delete(message_id, chat_id):
    """Queue a message to be deleted on Telegram."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pending_deletes (message_id, chat_id, status)
            VALUES (?, ?, 'pending')
        """, (message_id, chat_id))
        conn.commit()
        return cursor.lastrowid


def get_pending_deletes():
    """Get pending delete requests."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM pending_deletes
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def complete_delete(delete_id, message_id, chat_id):
    """Mark a delete request as completed and update the message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pending_deletes
            SET status = 'completed', completed_at = ?
            WHERE id = ?
        """, (utc_now(), delete_id))
        # Mark message as deleted in database
        cursor.execute("""
            UPDATE messages
            SET deleted = 1
            WHERE message_id = ? AND chat_id = ?
        """, (message_id, chat_id))
        conn.commit()


def get_unseen_outgoing_messages(sender_id, chat_id, limit=100):
    """Get messages we sent that haven't been marked as seen by target."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE sender_id = ? AND chat_id = ? AND seen_by_target = 0
            ORDER BY timestamp DESC
            LIMIT ?
        """, (sender_id, chat_id, limit))
        return [dict(row) for row in cursor.fetchall()]


def get_unread_messages_from_target(my_name):
    """Get all messages from target that we haven't marked as read."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT message_id, chat_id FROM messages
            WHERE sender_name != ? AND (marked_read IS NULL OR marked_read = 0)
            ORDER BY timestamp DESC
        """, (my_name,))
        return [dict(row) for row in cursor.fetchall()]


def mark_all_messages_read(my_name):
    """Mark all messages from target as read in database and return list for Telegram."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get messages to mark
        cursor.execute("""
            SELECT message_id, chat_id FROM messages
            WHERE sender_name != ? AND (marked_read IS NULL OR marked_read = 0)
        """, (my_name,))
        messages = [dict(row) for row in cursor.fetchall()]

        # Queue them all for read marks
        for msg in messages:
            cursor.execute("""
                INSERT INTO pending_read_marks (message_id, chat_id, status)
                VALUES (?, ?, 'pending')
            """, (msg['message_id'], msg['chat_id']))

        conn.commit()
        return len(messages)


def update_message_reactions(message_id, chat_id, reactions_json):
    """Update reactions for a message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages
            SET reactions = ?
            WHERE message_id = ? AND chat_id = ?
        """, (reactions_json, message_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0


def update_message_transcript(message_id, chat_id, transcript, status='completed'):
    """Update transcript for a media message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages
            SET transcript = ?, transcript_status = ?
            WHERE message_id = ? AND chat_id = ?
        """, (transcript, status, message_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0


def set_transcript_status(message_id, chat_id, status):
    """Set transcript status (pending, completed, failed)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE messages
            SET transcript_status = ?
            WHERE message_id = ? AND chat_id = ?
        """, (status, message_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0


def get_messages_needing_transcript(limit=10):
    """Get messages with media that don't have transcripts yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE media_type IN ('video', 'audio', 'video_note', 'voice', 'circle')
            AND media_path IS NOT NULL
            AND (transcript IS NULL OR transcript = '')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def sync_read_status_from_telegram(my_name, chat_id, read_inbox_max_id):
    """Sync read status - mark messages as read if Telegram says we read them."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Mark all messages from target (not from me) with id <= read_inbox_max_id as read
        cursor.execute("""
            UPDATE messages
            SET marked_read = 1, marked_read_at = ?
            WHERE chat_id = ? AND sender_name != ?
            AND message_id <= ? AND (marked_read IS NULL OR marked_read = 0)
        """, (utc_now(), chat_id, my_name, read_inbox_max_id))
        conn.commit()
        return cursor.rowcount


# ==================== DATABASE SYNC FUNCTIONS ====================

def export_all_data():
    """Export all data from database as dictionary for syncing."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Export messages
        cursor.execute("SELECT * FROM messages ORDER BY timestamp")
        messages = [dict(row) for row in cursor.fetchall()]

        # Export online status
        cursor.execute("SELECT * FROM online_status ORDER BY timestamp")
        online_status = [dict(row) for row in cursor.fetchall()]

        return {
            'messages': messages,
            'online_status': online_status,
            'exported_at': utc_now().isoformat(),
            'stats': get_sync_stats()
        }


def import_and_merge_data(data):
    """Import and merge data from another database. Uses INSERT OR IGNORE for deduplication."""
    with get_connection() as conn:
        cursor = conn.cursor()

        messages_added = 0
        messages_updated = 0
        status_added = 0

        # Import messages
        for msg in data.get('messages', []):
            # Check if message exists (by message_id and chat_id)
            cursor.execute(
                "SELECT id, deleted, marked_read, seen_by_target, reactions FROM messages WHERE message_id = ? AND chat_id = ?",
                (msg.get('message_id'), msg.get('chat_id'))
            )
            existing = cursor.fetchone()

            if existing:
                # Update if new data has more info (deleted, read status, reactions)
                updates = []
                params = []

                if msg.get('deleted') and not existing['deleted']:
                    updates.append("deleted = ?")
                    params.append(msg['deleted'])
                    updates.append("deleted_at = ?")
                    params.append(msg.get('deleted_at'))

                if msg.get('marked_read') and not existing['marked_read']:
                    updates.append("marked_read = ?")
                    params.append(msg['marked_read'])
                    updates.append("marked_read_at = ?")
                    params.append(msg.get('marked_read_at'))

                if msg.get('seen_by_target') and not existing['seen_by_target']:
                    updates.append("seen_by_target = ?")
                    params.append(msg['seen_by_target'])
                    updates.append("seen_by_target_at = ?")
                    params.append(msg.get('seen_by_target_at'))

                if msg.get('reactions') and not existing['reactions']:
                    updates.append("reactions = ?")
                    params.append(msg['reactions'])

                if updates:
                    params.append(existing['id'])
                    cursor.execute(f"UPDATE messages SET {', '.join(updates)} WHERE id = ?", params)
                    messages_updated += 1
            else:
                # Insert new message
                cursor.execute("""
                    INSERT INTO messages (
                        message_id, chat_id, sender_id, sender_name, text,
                        media_type, media_path, timestamp, deleted, deleted_at,
                        marked_read, marked_read_at, seen_by_target, seen_by_target_at, reactions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    msg.get('message_id'), msg.get('chat_id'), msg.get('sender_id'),
                    msg.get('sender_name'), msg.get('text'), msg.get('media_type'),
                    msg.get('media_path'), msg.get('timestamp'), msg.get('deleted', 0),
                    msg.get('deleted_at'), msg.get('marked_read', 0), msg.get('marked_read_at'),
                    msg.get('seen_by_target', 0), msg.get('seen_by_target_at'), msg.get('reactions')
                ))
                messages_added += 1

        # Import online status (use timestamp + user_id for deduplication)
        for status in data.get('online_status', []):
            cursor.execute(
                "SELECT id FROM online_status WHERE user_id = ? AND timestamp = ?",
                (status.get('user_id'), status.get('timestamp'))
            )
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO online_status (user_id, username, status, last_seen, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    status.get('user_id'), status.get('username'), status.get('status'),
                    status.get('last_seen'), status.get('timestamp')
                ))
                status_added += 1

        conn.commit()

        return {
            'messages_added': messages_added,
            'messages_updated': messages_updated,
            'status_added': status_added
        }


def get_sync_stats():
    """Get database statistics for sync comparison."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count, MAX(timestamp) as latest FROM messages")
        msg_stats = dict(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) as count, MAX(timestamp) as latest FROM online_status")
        status_stats = dict(cursor.fetchone())

        cursor.execute("SELECT MIN(timestamp) as oldest, MAX(timestamp) as newest FROM messages")
        time_range = dict(cursor.fetchone())

        return {
            'messages_count': msg_stats['count'],
            'messages_latest': msg_stats['latest'],
            'status_count': status_stats['count'],
            'status_latest': status_stats['latest'],
            'time_range': time_range
        }


def get_daily_message_stats(my_name):
    """Get daily message counts grouped by sender."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                sender_name,
                COUNT(*) as count
            FROM messages
            GROUP BY DATE(timestamp), sender_name
            ORDER BY date DESC
            LIMIT 500
        """)
        rows = cursor.fetchall()

        # Organize by date
        daily = {}
        for row in rows:
            date = row['date']
            if date not in daily:
                daily[date] = {'from_me': 0, 'from_them': 0, 'total': 0}
            if row['sender_name'] == my_name:
                daily[date]['from_me'] = row['count']
            else:
                daily[date]['from_them'] = row['count']
            daily[date]['total'] += row['count']

        # Convert to list with balance calculation
        result = []
        for date, counts in sorted(daily.items(), reverse=True):
            balance = counts['from_me'] - counts['from_them']
            result.append({
                'date': date,
                'from_me': counts['from_me'],
                'from_them': counts['from_them'],
                'total': counts['total'],
                'balance': balance
            })
        return result


def get_online_sessions(days=7):
    """Get online sessions with duration calculations."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM online_status
            WHERE timestamp >= datetime('now', ? || ' days')
            ORDER BY timestamp DESC
        """, (f'-{days}',))

        rows = [dict(r) for r in cursor.fetchall()]

        # Calculate sessions (pair online with following offline)
        sessions = []
        for i, row in enumerate(rows):
            if row['status'] == 'offline' and i + 1 < len(rows):
                # Look for previous online
                prev = rows[i + 1]
                if prev['status'] == 'online':
                    start = prev['timestamp']
                    end = row['timestamp']
                    # Calculate duration in minutes
                    from datetime import datetime
                    try:
                        start_dt = datetime.fromisoformat(start.replace(' ', 'T'))
                        end_dt = datetime.fromisoformat(end.replace(' ', 'T'))
                        duration_mins = int((end_dt - start_dt).total_seconds() / 60)
                        sessions.append({
                            'start': start,
                            'end': end,
                            'duration_mins': duration_mins,
                            'date': start[:10]
                        })
                    except:
                        pass

        return sessions


def get_status_summary(days=7):
    """Get summary of online status for the last N days."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Count by status type
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM online_status
            WHERE timestamp >= datetime('now', ? || ' days')
            GROUP BY status
        """, (f'-{days}',))
        by_status = {row['status']: row['count'] for row in cursor.fetchall()}

        # Count by day
        cursor.execute("""
            SELECT DATE(timestamp) as date, status, COUNT(*) as count
            FROM online_status
            WHERE timestamp >= datetime('now', ? || ' days')
            GROUP BY DATE(timestamp), status
            ORDER BY date DESC
        """, (f'-{days}',))

        by_day = {}
        for row in cursor.fetchall():
            date = row['date']
            if date not in by_day:
                by_day[date] = {'online': 0, 'offline': 0, 'recently': 0}
            by_day[date][row['status']] = row['count']

        return {
            'by_status': by_status,
            'by_day': [{'date': k, **v} for k, v in sorted(by_day.items(), reverse=True)]
        }


def get_hourly_activity_heatmap(my_name, days=7):
    """Get hourly activity data for heatmap visualization."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                sender_name,
                COUNT(*) as count
            FROM messages
            WHERE timestamp >= datetime('now', ? || ' days')
            GROUP BY DATE(timestamp), strftime('%H', timestamp), sender_name
            ORDER BY date DESC, hour
        """, (f'-{days}',))

        rows = cursor.fetchall()

        # Organize by date and hour
        by_date = {}
        for row in rows:
            date = row['date']
            hour = row['hour']
            if date not in by_date:
                by_date[date] = {h: {'me': 0, 'them': 0} for h in range(24)}
            if row['sender_name'] == my_name:
                by_date[date][hour]['me'] = row['count']
            else:
                by_date[date][hour]['them'] = row['count']

        # Convert to list format
        result = []
        for date in sorted(by_date.keys(), reverse=True):
            hours_data = []
            for h in range(24):
                hours_data.append({
                    'hour': h,
                    'me': by_date[date][h]['me'],
                    'them': by_date[date][h]['them'],
                    'total': by_date[date][h]['me'] + by_date[date][h]['them']
                })
            result.append({
                'date': date,
                'hours': hours_data,
                'total': sum(hd['total'] for hd in hours_data)
            })

        return result


def get_daily_activity_trend(my_name, days=14):
    """Get daily message activity split by sender for last N days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                sender_name,
                COUNT(*) as count
            FROM messages
            WHERE timestamp >= datetime('now', ? || ' days')
            GROUP BY DATE(timestamp), sender_name
            ORDER BY date DESC
        """, (f'-{days}',))

        rows = cursor.fetchall()

        # Organize by date
        by_date = {}
        for row in rows:
            date = row['date']
            if date not in by_date:
                by_date[date] = {'date': date, 'from_me': 0, 'from_them': 0}
            if row['sender_name'] == my_name:
                by_date[date]['from_me'] = row['count']
            else:
                by_date[date]['from_them'] = row['count']

        result = []
        for date in sorted(by_date.keys(), reverse=True):
            d = by_date[date]
            d['total'] = d['from_me'] + d['from_them']
            result.append(d)

        return result


def get_activity_summary():
    """Get activity summary including online status patterns."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Total messages
        cursor.execute("SELECT COUNT(*) as total FROM messages")
        total_messages = cursor.fetchone()['total']

        # Messages this week
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE timestamp >= datetime('now', '-7 days')
        """)
        week_messages = cursor.fetchone()['count']

        # Online sessions (pairs of online->offline)
        cursor.execute("""
            SELECT COUNT(*) as count FROM online_status
            WHERE status = 'online'
        """)
        online_count = cursor.fetchone()['count']

        # Average response time (simplified: time between their message and our next message)
        cursor.execute("""
            SELECT AVG(response_time) as avg_time FROM (
                SELECT
                    (julianday(m2.timestamp) - julianday(m1.timestamp)) * 24 * 60 as response_time
                FROM messages m1
                JOIN messages m2 ON m2.timestamp > m1.timestamp
                    AND m2.sender_name != m1.sender_name
                    AND julianday(m2.timestamp) - julianday(m1.timestamp) < 1
                WHERE m1.sender_name != (SELECT sender_name FROM messages LIMIT 1)
                GROUP BY m1.id
                HAVING m2.id = (
                    SELECT MIN(id) FROM messages
                    WHERE timestamp > m1.timestamp AND sender_name != m1.sender_name
                )
            )
        """)
        avg_response_raw = cursor.fetchone()['avg_time']
        avg_response = round(avg_response_raw, 1) if avg_response_raw else None

        # Peak hours
        cursor.execute("""
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as count
            FROM messages
            GROUP BY hour
            ORDER BY count DESC
            LIMIT 3
        """)
        peak_hours = [{'hour': row['hour'], 'count': row['count']} for row in cursor.fetchall()]

        # Activity by day of week
        cursor.execute("""
            SELECT
                CASE CAST(strftime('%w', timestamp) AS INTEGER)
                    WHEN 0 THEN 'Sun'
                    WHEN 1 THEN 'Mon'
                    WHEN 2 THEN 'Tue'
                    WHEN 3 THEN 'Wed'
                    WHEN 4 THEN 'Thu'
                    WHEN 5 THEN 'Fri'
                    WHEN 6 THEN 'Sat'
                END as day,
                COUNT(*) as count
            FROM messages
            GROUP BY strftime('%w', timestamp)
            ORDER BY CAST(strftime('%w', timestamp) AS INTEGER)
        """)
        by_weekday = [{'day': row['day'], 'count': row['count']} for row in cursor.fetchall()]

        # Recent activity trend (messages per day for last 14 days, split by sender)
        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                sender_name,
                COUNT(*) as count
            FROM messages
            WHERE timestamp >= datetime('now', '-14 days')
            GROUP BY DATE(timestamp), sender_name
            ORDER BY date
        """)
        trend_rows = cursor.fetchall()

        # Organize trend by date with both senders
        trend_by_date = {}
        for row in trend_rows:
            date = row['date']
            if date not in trend_by_date:
                trend_by_date[date] = {'date': date, 'me': 0, 'them': 0, 'total': 0}
            # We can't know who is "me" here, so we'll use the first sender as reference
            trend_by_date[date]['total'] += row['count']

        recent_trend = list(trend_by_date.values())

        # Inferred activity from messages (when they're active based on message times)
        cursor.execute("""
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as count
            FROM messages
            WHERE sender_name != (SELECT sender_name FROM messages ORDER BY id LIMIT 1)
            GROUP BY hour
            ORDER BY hour
        """)
        their_active_hours = [{'hour': row['hour'], 'count': row['count']} for row in cursor.fetchall()]

        return {
            'total_messages': total_messages,
            'week_messages': week_messages,
            'online_count': online_count,
            'avg_response_mins': avg_response,
            'peak_hours': peak_hours,
            'by_weekday': by_weekday,
            'recent_trend': recent_trend,
            'their_active_hours': their_active_hours
        }


def get_ignore_events(my_name, days=14):
    """
    Detect when target went online while having unread messages from me,
    but went offline without reading them. This indicates intentional ignoring.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get all online sessions with their start/end times
        sessions = get_online_sessions(days=days)

        # Get my messages that were unseen at some point
        cursor.execute("""
            SELECT message_id, timestamp, seen_by_target, seen_by_target_at, text
            FROM messages
            WHERE sender_name = ?
            AND timestamp >= datetime('now', ? || ' days')
            ORDER BY timestamp
        """, (my_name, f'-{days}'))
        my_messages = [dict(r) for r in cursor.fetchall()]

        ignore_events = []

        for session in sessions:
            session_start = session['start']
            session_end = session['end']

            # Find messages I sent BEFORE this session started that were still unread
            for msg in my_messages:
                msg_ts = msg['timestamp']
                seen_at = msg['seen_by_target_at']

                # Message was sent before session
                if msg_ts < session_start:
                    # Check if it was still unread when session started
                    if not msg['seen_by_target']:
                        # Never seen - definitely ignored during this session
                        ignore_events.append({
                            'session_start': session_start,
                            'session_end': session_end,
                            'session_duration': session['duration_mins'],
                            'message_timestamp': msg_ts,
                            'message_preview': (msg['text'] or '')[:50],
                            'still_unread': True
                        })
                    elif seen_at and seen_at > session_end:
                        # Seen, but AFTER this session ended - ignored during this session
                        ignore_events.append({
                            'session_start': session_start,
                            'session_end': session_end,
                            'session_duration': session['duration_mins'],
                            'message_timestamp': msg_ts,
                            'message_preview': (msg['text'] or '')[:50],
                            'seen_later_at': seen_at,
                            'still_unread': False
                        })

        return ignore_events


def get_activity_timeline(my_name, days=7):
    """
    Get combined timeline of status changes, messages, and ignore events.
    This gives a complete picture of activity.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        timeline = []

        # Get status events
        cursor.execute("""
            SELECT 'status' as type, timestamp, status as detail, NULL as sender
            FROM online_status
            WHERE timestamp >= datetime('now', ? || ' days')
        """, (f'-{days}',))
        for row in cursor.fetchall():
            timeline.append({
                'type': 'status',
                'timestamp': row['timestamp'],
                'detail': row['detail'],
                'sender': None
            })

        # Get messages (to show when messages correlate with status)
        cursor.execute("""
            SELECT 'message' as type, timestamp,
                   CASE WHEN sender_name = ? THEN 'sent' ELSE 'received' END as detail,
                   sender_name as sender,
                   seen_by_target, seen_by_target_at
            FROM messages
            WHERE timestamp >= datetime('now', ? || ' days')
        """, (my_name, f'-{days}'))
        for row in cursor.fetchall():
            timeline.append({
                'type': 'message',
                'timestamp': row['timestamp'],
                'detail': row['detail'],
                'sender': row['sender'],
                'seen': row['seen_by_target'],
                'seen_at': row['seen_by_target_at']
            })

        # Sort by timestamp descending
        timeline.sort(key=lambda x: x['timestamp'], reverse=True)

        return timeline


def get_status_with_inferred(my_name, days=7):
    """
    Get status events with inferred online times from messages.
    When they send a message, they must be online at that moment.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get actual status events
        cursor.execute("""
            SELECT timestamp, status, 'logged' as source
            FROM online_status
            WHERE timestamp >= datetime('now', ? || ' days')
            ORDER BY timestamp DESC
        """, (f'-{days}',))
        status_events = [dict(r) for r in cursor.fetchall()]

        # Get message timestamps from target (they must be online when sending)
        cursor.execute("""
            SELECT timestamp, 'online' as status, 'inferred_from_message' as source
            FROM messages
            WHERE sender_name != ?
            AND timestamp >= datetime('now', ? || ' days')
        """, (my_name, f'-{days}'))
        inferred = [dict(r) for r in cursor.fetchall()]

        # Combine and sort
        all_events = status_events + inferred
        all_events.sort(key=lambda x: x['timestamp'], reverse=True)

        # Find gaps: times when we have inferred online but no logged status
        gaps = []
        for inf in inferred:
            inf_ts = inf['timestamp']
            # Check if there's a logged 'online' status within 5 minutes
            has_logged = False
            for evt in status_events:
                if evt['status'] == 'online':
                    try:
                        from datetime import datetime
                        evt_dt = datetime.fromisoformat(evt['timestamp'].replace(' ', 'T'))
                        inf_dt = datetime.fromisoformat(inf_ts.replace(' ', 'T'))
                        diff_mins = abs((evt_dt - inf_dt).total_seconds() / 60)
                        if diff_mins < 5:
                            has_logged = True
                            break
                    except:
                        pass
            if not has_logged:
                gaps.append(inf_ts)

        return {
            'events': all_events,
            'gaps': gaps,
            'gap_count': len(gaps)
        }


def get_unseen_during_sessions(my_name, days=14):
    """
    For each online session, count how many of my messages were unseen.
    This shows pattern of ignoring.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        sessions = get_online_sessions(days=days)

        results = []
        for session in sessions:
            # Count my messages sent before session that were still unseen
            cursor.execute("""
                SELECT COUNT(*) as unseen_count
                FROM messages
                WHERE sender_name = ?
                AND timestamp < ?
                AND (seen_by_target = 0 OR seen_by_target_at > ?)
            """, (my_name, session['start'], session['end']))

            unseen = cursor.fetchone()['unseen_count']

            if unseen > 0:
                results.append({
                    'date': session['date'],
                    'start': session['start'],
                    'end': session['end'],
                    'duration_mins': session['duration_mins'],
                    'unseen_messages': unseen
                })

        return results


def queue_outgoing_media(file_path, media_type):
    """Add a media file to the outgoing queue."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO outgoing_messages (text, status)
            VALUES (?, 'pending')
        """, (f"MEDIA:{media_type}:{file_path}",))
        conn.commit()
        return cursor.lastrowid


def get_monthly_stats(my_name, days=None):
    """Get message counts grouped by month."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if days:
            cursor.execute("""
                SELECT
                    strftime('%Y-%m', timestamp) as month,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                WHERE timestamp >= datetime('now', ? || ' days')
                GROUP BY strftime('%Y-%m', timestamp), sender_name
                ORDER BY month DESC
            """, (f'-{days}',))
        else:
            cursor.execute("""
                SELECT
                    strftime('%Y-%m', timestamp) as month,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                GROUP BY strftime('%Y-%m', timestamp), sender_name
                ORDER BY month DESC
            """)
        rows = cursor.fetchall()

        by_month = {}
        for row in rows:
            month = row['month']
            if month not in by_month:
                by_month[month] = {'month': month, 'me': 0, 'them': 0, 'total': 0}
            if row['sender_name'] == my_name:
                by_month[month]['me'] = row['count']
            else:
                by_month[month]['them'] = row['count']
            by_month[month]['total'] += row['count']

        result = []
        for month in sorted(by_month.keys(), reverse=True):
            d = by_month[month]
            d['balance'] = d['me'] - d['them']
            d['ratio'] = round(d['me'] / d['them'], 2) if d['them'] > 0 else 0
            result.append(d)
        return result


def get_all_time_stats(my_name, days=None):
    """Get comprehensive all-time statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()

        date_filter = f"WHERE timestamp >= datetime('now', '-{days} days')" if days else ""

        # Total counts by sender
        cursor.execute(f"""
            SELECT sender_name, COUNT(*) as count
            FROM messages
            {date_filter}
            GROUP BY sender_name
        """)
        counts = {row['sender_name']: row['count'] for row in cursor.fetchall()}
        my_count = counts.get(my_name, 0)
        their_count = sum(c for n, c in counts.items() if n != my_name)

        # Date range
        cursor.execute(f"SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM messages {date_filter}")
        dates = cursor.fetchone()
        first_msg = dates['first']
        last_msg = dates['last']

        # Days with messages
        cursor.execute(f"SELECT COUNT(DISTINCT DATE(timestamp)) as days FROM messages {date_filter}")
        active_days = cursor.fetchone()['days']

        # Total days in range
        if first_msg and last_msg:
            cursor.execute("""
                SELECT julianday(?) - julianday(?) as total_days
            """, (last_msg, first_msg))
            total_days = int(cursor.fetchone()['total_days'] or 0) + 1
        else:
            total_days = 0

        # Average messages per day
        avg_per_day = round((my_count + their_count) / active_days, 1) if active_days > 0 else 0

        # Longest streak
        cursor.execute(f"""
            SELECT DATE(timestamp) as date FROM messages {date_filter} GROUP BY DATE(timestamp) ORDER BY date
        """)
        dates_list = [row['date'] for row in cursor.fetchall()]
        max_streak = 0
        current_streak = 1
        for i in range(1, len(dates_list)):
            from datetime import datetime, timedelta
            try:
                d1 = datetime.strptime(dates_list[i-1], '%Y-%m-%d')
                d2 = datetime.strptime(dates_list[i], '%Y-%m-%d')
                if (d2 - d1).days == 1:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 1
            except:
                pass
        max_streak = max(max_streak, current_streak)

        # Deleted messages
        deleted_filter = f"AND timestamp >= datetime('now', '-{days} days')" if days else ""
        cursor.execute(f"SELECT COUNT(*) as count FROM messages WHERE deleted = 1 {deleted_filter}")
        deleted_count = cursor.fetchone()['count']

        # Media stats
        media_filter = f"AND timestamp >= datetime('now', '-{days} days')" if days else ""
        cursor.execute(f"""
            SELECT media_type, COUNT(*) as count
            FROM messages WHERE media_type IS NOT NULL {media_filter}
            GROUP BY media_type
        """)
        media_stats = {row['media_type']: row['count'] for row in cursor.fetchall()}

        # Average message length
        text_filter = f"AND timestamp >= datetime('now', '-{days} days')" if days else ""
        cursor.execute(f"""
            SELECT sender_name, AVG(LENGTH(text)) as avg_len
            FROM messages WHERE text IS NOT NULL AND text != '' {text_filter}
            GROUP BY sender_name
        """)
        avg_lens = {row['sender_name']: round(row['avg_len'] or 0) for row in cursor.fetchall()}

        return {
            'my_count': my_count,
            'their_count': their_count,
            'total': my_count + their_count,
            'balance': my_count - their_count,
            'ratio': round(my_count / their_count, 2) if their_count > 0 else 0,
            'first_message': first_msg,
            'last_message': last_msg,
            'active_days': active_days,
            'total_days': total_days,
            'avg_per_day': avg_per_day,
            'max_streak': max_streak,
            'deleted_count': deleted_count,
            'media_stats': media_stats,
            'my_avg_length': avg_lens.get(my_name, 0),
            'their_avg_length': sum(v for k, v in avg_lens.items() if k != my_name) // max(1, len([k for k in avg_lens if k != my_name]))
        }


def get_hourly_pattern(my_name, days=None):
    """Get hourly message distribution for both users."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if days:
            cursor.execute("""
                SELECT
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                WHERE timestamp >= datetime('now', ? || ' days')
                GROUP BY hour, sender_name
                ORDER BY hour
            """, (f'-{days}',))
        else:
            cursor.execute("""
                SELECT
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                GROUP BY hour, sender_name
                ORDER BY hour
            """)
        rows = cursor.fetchall()

        hours = {h: {'hour': h, 'me': 0, 'them': 0} for h in range(24)}
        for row in rows:
            h = row['hour']
            if row['sender_name'] == my_name:
                hours[h]['me'] = row['count']
            else:
                hours[h]['them'] = row['count']

        return [hours[h] for h in range(24)]


def get_weekday_pattern(my_name, days=None):
    """Get weekday message distribution for both users."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if days:
            cursor.execute("""
                SELECT
                    CAST(strftime('%w', timestamp) AS INTEGER) as weekday,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                WHERE timestamp >= datetime('now', ? || ' days')
                GROUP BY weekday, sender_name
                ORDER BY weekday
            """, (f'-{days}',))
        else:
            cursor.execute("""
                SELECT
                    CAST(strftime('%w', timestamp) AS INTEGER) as weekday,
                    sender_name,
                    COUNT(*) as count
                FROM messages
                GROUP BY weekday, sender_name
                ORDER BY weekday
            """)
        rows = cursor.fetchall()

        day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        weekdays = {i: {'day': day_names[i], 'me': 0, 'them': 0} for i in range(7)}
        for row in rows:
            d = row['weekday']
            if row['sender_name'] == my_name:
                weekdays[d]['me'] = row['count']
            else:
                weekdays[d]['them'] = row['count']

        return [weekdays[i] for i in range(7)]


def get_view_time_stats(my_name, days=None):
    """Get statistics about how long it takes for target to view our messages."""
    with get_connection() as conn:
        cursor = conn.cursor()

        date_filter = f"AND timestamp >= datetime('now', '-{days} days')" if days else ""

        # Get messages we sent that have been seen, with the time difference
        cursor.execute(f"""
            SELECT
                DATE(timestamp) as date,
                timestamp,
                seen_by_target_at,
                (julianday(seen_by_target_at) - julianday(timestamp)) * 24 * 60 as view_time_mins
            FROM messages
            WHERE sender_name = ?
            AND seen_by_target = 1
            AND seen_by_target_at IS NOT NULL
            {date_filter}
            ORDER BY timestamp DESC
        """, (my_name,))

        rows = cursor.fetchall()

        if not rows:
            return {'daily_avg': [], 'overall_avg': None, 'total_seen': 0}

        # Group by date for daily averages
        by_date = {}
        total_time = 0
        valid_count = 0

        for row in rows:
            view_mins = row['view_time_mins']
            if view_mins is not None and view_mins >= 0 and view_mins < 10080:  # < 1 week
                date = row['date']
                if date not in by_date:
                    by_date[date] = {'times': [], 'date': date}
                by_date[date]['times'].append(view_mins)
                total_time += view_mins
                valid_count += 1

        # Calculate daily averages
        daily_avg = []
        for date in sorted(by_date.keys(), reverse=True)[:30]:
            times = by_date[date]['times']
            avg = sum(times) / len(times) if times else 0
            daily_avg.append({
                'date': date,
                'avg_mins': round(avg, 1),
                'count': len(times)
            })

        overall_avg = round(total_time / valid_count, 1) if valid_count > 0 else None

        return {
            'daily_avg': daily_avg,
            'overall_avg': overall_avg,
            'total_seen': valid_count
        }


def get_message_timeline(my_name, hours=4):
    """Get messages from last N hours for timeline visualization."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                message_id,
                sender_name,
                timestamp,
                LENGTH(text) as msg_length,
                marked_read_at,
                seen_by_target_at
            FROM messages
            WHERE timestamp >= datetime('now', 'localtime', ? || ' hours')
            ORDER BY timestamp ASC
        """, (f'-{hours}',))

        messages = []
        for row in cursor.fetchall():
            messages.append({
                'id': row['message_id'],
                'from_me': row['sender_name'] == my_name,
                'timestamp': row['timestamp'],
                'length': row['msg_length'] or 0,
                'read_at': row['marked_read_at'],
                'seen_at': row['seen_by_target_at']
            })

        return messages


# ==================== CLAUDE REQUESTS ====================

def add_claude_request(text, mode='api', model='claude-sonnet-4-20250514', parent_id=None, auto_push=True):
    """Add a new request for Claude."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO claude_requests (text, status, mode, model, parent_id, auto_push)
            VALUES (?, 'pending', ?, ?, ?, ?)
        """, (text, mode, model, parent_id, 1 if auto_push else 0))
        conn.commit()
        return cursor.lastrowid


def get_claude_requests(limit=50):
    """Get recent Claude requests."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM claude_requests
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_pending_claude_requests():
    """Get pending Claude requests."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM claude_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def claim_pending_request():
    """Atomically claim a pending request for processing.

    This prevents race conditions when multiple processors run simultaneously.
    Returns the claimed request or None if no pending requests.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        # First get the oldest pending request
        cursor.execute("""
            SELECT id FROM claude_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None

        req_id = row['id']

        # Atomically claim it (check status again to prevent race)
        cursor.execute("""
            UPDATE claude_requests
            SET status = 'claimed', updated_at = datetime('now')
            WHERE id = ? AND status = 'pending'
        """, (req_id,))
        conn.commit()

        # Check if we actually claimed it
        if cursor.rowcount == 0:
            return None  # Another process claimed it

        # Return the full request
        cursor.execute("SELECT * FROM claude_requests WHERE id = ?", (req_id,))
        return dict(cursor.fetchone())


def update_claude_request(req_id, status, response=None):
    """Update a Claude request status and response."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE claude_requests
            SET status = ?, response = ?, completed_at = ?
            WHERE id = ?
        """, (status, response, utc_now() if status != 'pending' else None, req_id))
        conn.commit()


def get_claude_request(req_id):
    """Get a single Claude request by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM claude_requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def add_claude_log(request_id, message, log_type='info'):
    """Add a log entry for a Claude request."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO claude_logs (request_id, log_type, message)
            VALUES (?, ?, ?)
        """, (request_id, log_type, message))
        conn.commit()
        return cursor.lastrowid


def get_claude_logs(request_id):
    """Get all log entries for a Claude request."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM claude_logs
            WHERE request_id = ?
            ORDER BY timestamp ASC
        """, (request_id,))
        return [dict(row) for row in cursor.fetchall()]


# ==================== AI ASSISTANT ====================

def get_ai_prompts(active_only=True):
    """Get all AI prompts."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if active_only:
            cursor.execute("SELECT * FROM ai_prompts WHERE is_active = 1 ORDER BY is_default DESC, name")
        else:
            cursor.execute("SELECT * FROM ai_prompts ORDER BY is_default DESC, name")
        return [dict(row) for row in cursor.fetchall()]


def get_ai_prompt(prompt_id):
    """Get a single AI prompt by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_prompts WHERE id = ?", (prompt_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_default_prompt():
    """Get the default AI prompt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_prompts WHERE is_default = 1 AND is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None


def save_ai_prompt(name, system_prompt, description=None, is_default=False):
    """Save a new AI prompt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # If setting as default, unset other defaults
        if is_default:
            cursor.execute("UPDATE ai_prompts SET is_default = 0")
        cursor.execute("""
            INSERT INTO ai_prompts (name, description, system_prompt, is_default)
            VALUES (?, ?, ?, ?)
        """, (name, description, system_prompt, 1 if is_default else 0))
        conn.commit()
        return cursor.lastrowid


def update_ai_prompt(prompt_id, name=None, system_prompt=None, description=None, is_active=None, is_default=None):
    """Update an AI prompt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if is_default:
            cursor.execute("UPDATE ai_prompts SET is_default = 0")
        updates = []
        values = []
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if system_prompt is not None:
            updates.append("system_prompt = ?")
            values.append(system_prompt)
        if description is not None:
            updates.append("description = ?")
            values.append(description)
        if is_active is not None:
            updates.append("is_active = ?")
            values.append(1 if is_active else 0)
        if is_default is not None:
            updates.append("is_default = ?")
            values.append(1 if is_default else 0)
        if updates:
            values.append(prompt_id)
            cursor.execute(f"UPDATE ai_prompts SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()


def delete_ai_prompt(prompt_id):
    """Delete an AI prompt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_prompts WHERE id = ?", (prompt_id,))
        conn.commit()


def save_ai_suggestion(message_id, prompt_id, suggestions, context_used=None, tokens_used=None):
    """Save AI-generated suggestions for a message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_suggestions (message_id, prompt_id, suggestions, context_used, tokens_used)
            VALUES (?, ?, ?, ?, ?)
        """, (message_id, prompt_id, suggestions, context_used, tokens_used))
        conn.commit()
        return cursor.lastrowid


def get_ai_suggestions(message_id=None, limit=20):
    """Get AI suggestions, optionally filtered by message_id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if message_id:
            cursor.execute("""
                SELECT s.*, p.name as prompt_name
                FROM ai_suggestions s
                LEFT JOIN ai_prompts p ON s.prompt_id = p.id
                WHERE s.message_id = ?
                ORDER BY s.created_at DESC
            """, (message_id,))
        else:
            cursor.execute("""
                SELECT s.*, p.name as prompt_name
                FROM ai_suggestions s
                LEFT JOIN ai_prompts p ON s.prompt_id = p.id
                ORDER BY s.created_at DESC
                LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_messages_without_suggestions(limit=10):
    """Get recent messages from her that don't have AI suggestions yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.* FROM messages m
            LEFT JOIN ai_suggestions s ON m.message_id = s.message_id
            WHERE s.id IS NULL
            AND m.sender_name != ?
            ORDER BY m.timestamp DESC
            LIMIT ?
        """, (config.MY_NAME if hasattr(config, 'MY_NAME') else 'Me', limit))
        return [dict(row) for row in cursor.fetchall()]


def save_ai_conversation(role, content, tokens_used=None):
    """Save a message in the AI Q&A conversation."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_conversations (role, content, tokens_used)
            VALUES (?, ?, ?)
        """, (role, content, tokens_used))
        conn.commit()
        return cursor.lastrowid


def get_ai_conversation(limit=50):
    """Get recent AI Q&A conversation history."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM ai_conversations
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(row) for row in cursor.fetchall()]
        return list(reversed(rows))  # Return in chronological order


def clear_ai_conversation():
    """Clear the AI Q&A conversation history."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_conversations")
        conn.commit()


def save_conversation_summary(summary, messages_covered, start_date, end_date, key_facts=None):
    """Save a conversation summary."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversation_summaries (summary, messages_covered, start_date, end_date, key_facts)
            VALUES (?, ?, ?, ?, ?)
        """, (summary, messages_covered, start_date, end_date, key_facts))
        conn.commit()
        return cursor.lastrowid


def get_conversation_summaries(limit=10):
    """Get recent conversation summaries."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM conversation_summaries
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_latest_summary():
    """Get the most recent conversation summary."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversation_summaries ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None


def get_context_messages(limit=50, before_timestamp=None):
    """Get messages for AI context, with optional timestamp filter."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if before_timestamp:
            cursor.execute("""
                SELECT * FROM messages
                WHERE timestamp < ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (before_timestamp, limit))
        else:
            cursor.execute("""
                SELECT * FROM messages
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        rows = [dict(row) for row in cursor.fetchall()]
        return list(reversed(rows))  # Return in chronological order


def get_context_messages_by_days(days: int):
    """Get messages from the last N days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE timestamp >= datetime('now', ? || ' days')
            ORDER BY timestamp ASC
        """, (f'-{days}',))
        return [dict(row) for row in cursor.fetchall()]


def get_context_preview(mode: str = 'messages', value: int = 50):
    """
    Get preview stats for context selection.

    Args:
        mode: 'messages' or 'days'
        value: number of messages or days

    Returns:
        dict with message_count, token_estimate, memory_mb, kv_cache_gb
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        if mode == 'days':
            cursor.execute("""
                SELECT COUNT(*) as count,
                       COALESCE(SUM(LENGTH(COALESCE(text, ''))), 0) as total_chars
                FROM messages
                WHERE timestamp >= datetime('now', ? || ' days')
            """, (f'-{value}',))
        else:
            # mode == 'messages'
            cursor.execute("""
                SELECT COUNT(*) as count,
                       COALESCE(SUM(LENGTH(COALESCE(text, ''))), 0) as total_chars
                FROM (
                    SELECT text FROM messages
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
            """, (value,))

        row = cursor.fetchone()
        message_count = row['count'] or 0
        total_chars = row['total_chars'] or 0

        # Get total messages available in database
        cursor.execute("SELECT COUNT(*) as total FROM messages")
        total_available = cursor.fetchone()['total']

        # Estimate tokens (rough: ~4 chars per token for English)
        # Add overhead for message formatting (~30 tokens per message for timestamp, sender, etc.)
        token_estimate = (total_chars // 4) + (message_count * 30)

        # KV cache memory estimate for LLM inference:
        # Typical 7B model: ~2MB per 1K tokens for KV cache
        # 32B model: ~8MB per 1K tokens
        # Using 32B estimate since user is using larger models
        kv_cache_mb = (token_estimate / 1000) * 8
        kv_cache_gb = kv_cache_mb / 1024

        # Base model memory (assume 8GB for quantized model)
        base_model_gb = 8.0
        total_ram_gb = base_model_gb + kv_cache_gb

        return {
            'message_count': message_count,
            'total_available': total_available,
            'token_estimate': token_estimate,
            'kv_cache_gb': round(kv_cache_gb, 2),
            'total_ram_gb': round(total_ram_gb, 1),
            'mode': mode,
            'value': value
        }


# ==================== CLAUDE REQUEST MANAGEMENT ====================

def cancel_claude_request(req_id):
    """Cancel a pending or processing request."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE claude_requests
            SET status = 'cancelled', completed_at = ?
            WHERE id = ? AND status IN ('pending', 'processing')
        """, (utc_now(), req_id))
        conn.commit()
        return cursor.rowcount > 0


def restart_claude_request(req_id, new_text=None, mode=None, model=None, auto_push=None):
    """Create a new request based on an existing one (restart)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get original request
        cursor.execute("SELECT text, mode, model, auto_push, restart_count FROM claude_requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        if not row:
            return None
        text = new_text or row['text']
        # Use provided mode/model or fall back to original
        use_mode = mode or row['mode'] or 'api'
        use_model = model or row['model'] or 'claude-sonnet-4-20250514'
        use_auto_push = auto_push if auto_push is not None else (row['auto_push'] if row['auto_push'] is not None else 1)
        # Increment restart count
        new_restart_count = (row['restart_count'] or 0) + 1
        # Create new request linked to parent
        cursor.execute("""
            INSERT INTO claude_requests (text, status, mode, model, parent_id, auto_push, restart_count)
            VALUES (?, 'pending', ?, ?, ?, ?, ?)
        """, (text, use_mode, use_model, req_id, use_auto_push, new_restart_count))
        conn.commit()
        return cursor.lastrowid


def mark_request_interrupted(req_id):
    """Mark a request as interrupted (e.g., due to server restart)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE claude_requests
            SET interrupted = 1, interrupted_at = ?
            WHERE id = ? AND status = 'processing'
        """, (utc_now(), req_id))
        conn.commit()
        return cursor.rowcount > 0


def get_interrupted_requests():
    """Get all interrupted requests that need to be restarted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM claude_requests
            WHERE interrupted = 1 AND status = 'processing'
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_request_context(req_id):
    """Get the full context of a request including parent chain and logs."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get the request
        cursor.execute("SELECT * FROM claude_requests WHERE id = ?", (req_id,))
        req = cursor.fetchone()
        if not req:
            return None

        req = dict(req)

        # Get logs for this request
        cursor.execute("""
            SELECT * FROM claude_logs
            WHERE request_id = ?
            ORDER BY timestamp ASC
        """, (req_id,))
        req['logs'] = [dict(row) for row in cursor.fetchall()]

        # Get parent chain if exists
        parent_chain = []
        current_parent_id = req.get('parent_id')
        while current_parent_id:
            cursor.execute("SELECT * FROM claude_requests WHERE id = ?", (current_parent_id,))
            parent = cursor.fetchone()
            if not parent:
                break
            parent = dict(parent)
            # Get parent's logs
            cursor.execute("""
                SELECT * FROM claude_logs
                WHERE request_id = ?
                ORDER BY timestamp ASC
            """, (current_parent_id,))
            parent['logs'] = [dict(row) for row in cursor.fetchall()]
            parent_chain.append(parent)
            current_parent_id = parent.get('parent_id')

        req['parent_chain'] = parent_chain
        return req


def delete_claude_request(req_id):
    """Delete a request and its logs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM claude_logs WHERE request_id = ?", (req_id,))
        cursor.execute("DELETE FROM claude_requests WHERE id = ?", (req_id,))
        conn.commit()
        return cursor.rowcount > 0


# ==================== INCEPT SETTINGS ====================

def _ensure_incept_settings_schema(cursor):
    """Ensure incept_settings table has all required columns."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incept_settings (
            id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'api',
            model TEXT DEFAULT 'claude-sonnet-4-20250514',
            batch_mode INTEGER DEFAULT 0,
            push_queue_at_end INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add columns if they don't exist (migration)
    for column, default in [('batch_mode', 0), ('push_queue_at_end', 0)]:
        try:
            cursor.execute(f"ALTER TABLE incept_settings ADD COLUMN {column} INTEGER DEFAULT {default}")
        except:
            pass  # Column already exists


def get_incept_settings():
    """Get Incept processor settings."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_incept_settings_schema(cursor)
        conn.commit()

        cursor.execute("SELECT * FROM incept_settings LIMIT 1")
        row = cursor.fetchone()
        if row:
            result = dict(row)
            # Ensure defaults for new columns
            result.setdefault('batch_mode', 0)
            result.setdefault('push_queue_at_end', 0)
            return result
        return {'mode': 'api', 'model': 'claude-sonnet-4-20250514', 'batch_mode': 0, 'push_queue_at_end': 0}


def save_incept_settings(mode, model, batch_mode=None):
    """Save Incept processor settings."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_incept_settings_schema(cursor)

        # Get current batch_mode if not provided
        if batch_mode is None:
            cursor.execute("SELECT batch_mode FROM incept_settings LIMIT 1")
            row = cursor.fetchone()
            batch_mode = row['batch_mode'] if row and 'batch_mode' in row.keys() else 0

        # Delete existing and insert new
        cursor.execute("DELETE FROM incept_settings")
        cursor.execute("""
            INSERT INTO incept_settings (mode, model, batch_mode, updated_at)
            VALUES (?, ?, ?, ?)
        """, (mode, model, batch_mode, utc_now()))
        conn.commit()


def set_incept_batch_mode(enabled: bool):
    """Enable or disable batch mode for improvements."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_incept_settings_schema(cursor)

        cursor.execute("SELECT * FROM incept_settings LIMIT 1")
        row = cursor.fetchone()

        if row:
            cursor.execute("""
                UPDATE incept_settings SET batch_mode = ?, updated_at = ?
            """, (1 if enabled else 0, utc_now()))
        else:
            cursor.execute("""
                INSERT INTO incept_settings (mode, model, batch_mode, updated_at)
                VALUES ('api', 'claude-sonnet-4-20250514', ?, ?)
            """, (1 if enabled else 0, utc_now()))
        conn.commit()


def is_incept_batch_mode():
    """Check if batch mode is enabled."""
    settings = get_incept_settings()
    return bool(settings.get('batch_mode', 0))


def set_push_queue_at_end(enabled: bool):
    """Enable or disable 'push queue at end' mode."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_incept_settings_schema(cursor)

        cursor.execute("SELECT * FROM incept_settings LIMIT 1")
        row = cursor.fetchone()

        if row:
            cursor.execute("""
                UPDATE incept_settings SET push_queue_at_end = ?, updated_at = ?
            """, (1 if enabled else 0, utc_now()))
        else:
            cursor.execute("""
                INSERT INTO incept_settings (mode, model, push_queue_at_end, updated_at)
                VALUES ('api', 'claude-sonnet-4-20250514', ?, ?)
            """, (1 if enabled else 0, utc_now()))
        conn.commit()


def is_push_queue_at_end():
    """Check if 'push queue at end' mode is enabled."""
    settings = get_incept_settings()
    return bool(settings.get('push_queue_at_end', 0))


# ==================== SYSTEM LOGS ====================

def add_system_log(category, action, status='info', message=None, details=None):
    """Add a system log entry.

    Categories: media, message, status, ai, claude, sync, auth, error
    Status: info, success, warning, error, pending, progress
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO system_logs (category, action, status, message, details)
            VALUES (?, ?, ?, ?, ?)
        """, (category, action, status, message, details))
        conn.commit()
        return cursor.lastrowid


def get_system_logs(limit=100, category=None, status=None, offset=0):
    """Get system logs with optional filtering."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM system_logs WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_system_log_stats():
    """Get statistics for system logs."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Count by category
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM system_logs
            GROUP BY category
        """)
        by_category = {row['category']: row['count'] for row in cursor.fetchall()}

        # Count by status
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM system_logs
            GROUP BY status
        """)
        by_status = {row['status']: row['count'] for row in cursor.fetchall()}

        # Recent errors
        cursor.execute("""
            SELECT * FROM system_logs
            WHERE status = 'error'
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        recent_errors = [dict(row) for row in cursor.fetchall()]

        # Total count
        cursor.execute("SELECT COUNT(*) as total FROM system_logs")
        total = cursor.fetchone()['total']

        return {
            'total': total,
            'by_category': by_category,
            'by_status': by_status,
            'recent_errors': recent_errors
        }


def clear_old_logs(days=30):
    """Clear system logs older than specified days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM system_logs
            WHERE timestamp < datetime('now', ? || ' days')
        """, (f'-{days}',))
        deleted = cursor.rowcount
        conn.commit()
        return deleted


def update_media_metadata(message_id, chat_id, duration=None, width=None, height=None, size=None, thumbnail=None, snapshots=None):
    """Update media metadata for a message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = []
        values = []

        if duration is not None:
            updates.append("media_duration = ?")
            values.append(duration)
        if width is not None:
            updates.append("media_width = ?")
            values.append(width)
        if height is not None:
            updates.append("media_height = ?")
            values.append(height)
        if size is not None:
            updates.append("media_size = ?")
            values.append(size)
        if thumbnail is not None:
            updates.append("media_thumbnail = ?")
            values.append(thumbnail)
        if snapshots is not None:
            updates.append("media_snapshots = ?")
            values.append(snapshots)

        if updates:
            values.extend([message_id, chat_id])
            cursor.execute(f"""
                UPDATE messages
                SET {', '.join(updates)}
                WHERE message_id = ? AND chat_id = ?
            """, values)
            conn.commit()
            return cursor.rowcount > 0
        return False


def get_messages_needing_metadata():
    """Get messages with media that don't have metadata or snapshots extracted yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE media_path IS NOT NULL
            AND media_path != ''
            AND (
                media_duration IS NULL
                OR media_width IS NULL
                OR media_size IS NULL
                OR (media_type IN ('video', 'video_note', 'circle') AND (media_snapshots IS NULL OR media_snapshots = ''))
            )
            AND media_type IN ('video', 'photo', 'audio', 'voice', 'video_note', 'circle')
            ORDER BY timestamp DESC
            LIMIT 50
        """)
        return [dict(row) for row in cursor.fetchall()]


def format_media_size(bytes_size):
    """Format file size in human readable format."""
    if not bytes_size:
        return ""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def format_duration(seconds):
    """Format duration in human readable format."""
    if not seconds:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"


# ==================== INCEPT+ FUNCTIONS ====================

def add_incept_suggestion(title, description, implementation_details, category='feature',
                          priority=3, context=None, estimated_effort=None, dependencies=None):
    """Add a new Incept+ improvement suggestion."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO incept_suggestions
            (title, description, implementation_details, category, priority, context, estimated_effort, dependencies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, description, implementation_details, category, priority, context, estimated_effort, dependencies))
        conn.commit()
        return cursor.lastrowid


def get_incept_suggestions(status=None, category=None, limit=50):
    """Get Incept+ suggestions with optional filtering."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM incept_suggestions"
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_incept_suggestion(suggestion_id):
    """Get a single Incept+ suggestion by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incept_suggestions WHERE id = ?", (suggestion_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_incept_suggestion_status(suggestion_id, status):
    """Update the status of an Incept+ suggestion."""
    with get_connection() as conn:
        cursor = conn.cursor()
        timestamp_field = None
        if status == 'accepted':
            timestamp_field = 'accepted_at'
        elif status == 'rejected':
            timestamp_field = 'rejected_at'
        elif status == 'implemented':
            timestamp_field = 'implemented_at'

        if timestamp_field:
            cursor.execute(f"""
                UPDATE incept_suggestions
                SET status = ?, {timestamp_field} = ?
                WHERE id = ?
            """, (status, utc_now(), suggestion_id))
        else:
            cursor.execute("""
                UPDATE incept_suggestions
                SET status = ?
                WHERE id = ?
            """, (status, suggestion_id))
        conn.commit()


def generate_improvement_unique_id():
    """Generate a unique improvement ID like IMP-001, IMP-002, etc."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get the highest existing unique_id number
        cursor.execute("""
            SELECT unique_id FROM incept_improvements
            WHERE unique_id IS NOT NULL AND unique_id LIKE 'IMP-%'
            ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        if row and row['unique_id']:
            try:
                last_num = int(row['unique_id'].replace('IMP-', ''))
                return f"IMP-{last_num + 1:03d}"
            except ValueError:
                pass
        # Also check count as fallback
        cursor.execute("SELECT COUNT(*) as cnt FROM incept_improvements")
        count = cursor.fetchone()['cnt']
        return f"IMP-{count + 1:03d}"


def add_incept_improvement(suggestion_id, title, description, implementation_summary,
                          commit_hash=None, files_changed=None, feature_flag=None, rollback_info=None):
    """Record an implemented improvement with auto-generated unique ID."""
    unique_id = generate_improvement_unique_id()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO incept_improvements
            (suggestion_id, title, description, implementation_summary, commit_hash,
             files_changed, feature_flag, rollback_info, unique_id, pushed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (suggestion_id, title, description, implementation_summary, commit_hash,
              files_changed, feature_flag, rollback_info, unique_id))
        conn.commit()
        return cursor.lastrowid, unique_id


def get_incept_improvements(enabled_only=False, limit=100):
    """Get implemented improvements."""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM incept_improvements"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC LIMIT ?"
        cursor.execute(query, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_incept_improvement(improvement_id):
    """Get a single improvement by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incept_improvements WHERE id = ?", (improvement_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def toggle_incept_improvement(improvement_id, enabled):
    """Enable or disable an implemented improvement."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE incept_improvements
            SET enabled = ?, disabled_at = ?
            WHERE id = ?
        """, (1 if enabled else 0, None if enabled else utc_now(), improvement_id))
        conn.commit()


def get_unpushed_improvements():
    """Get all improvements that haven't been pushed yet."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM incept_improvements
            WHERE pushed = 0 OR pushed IS NULL
            ORDER BY created_at ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def mark_improvements_pushed(improvement_ids, commit_hash=None):
    """Mark multiple improvements as pushed."""
    if not improvement_ids:
        return 0
    with get_connection() as conn:
        cursor = conn.cursor()
        placeholders = ','.join(['?' for _ in improvement_ids])
        cursor.execute(f"""
            UPDATE incept_improvements
            SET pushed = 1, pushed_at = ?
            WHERE id IN ({placeholders})
        """, [utc_now()] + list(improvement_ids))
        conn.commit()
        return cursor.rowcount


def update_improvement_commit_hash(improvement_id, commit_hash):
    """Update the commit hash for an improvement."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE incept_improvements
            SET commit_hash = ?
            WHERE id = ?
        """, (commit_hash, improvement_id))
        conn.commit()


def start_incept_auto_session(direction, max_suggestions=10):
    """Start a new auto-mode session."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO incept_auto_sessions (direction, max_suggestions)
            VALUES (?, ?)
        """, (direction, max_suggestions))
        conn.commit()
        return cursor.lastrowid


def update_incept_auto_session(session_id, status=None, suggestions_generated=None,
                               suggestions_implemented=None):
    """Update auto-mode session progress."""
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)
            if status in ['stopped', 'completed', 'error']:
                updates.append("stopped_at = ?")
                params.append(utc_now())

        if suggestions_generated is not None:
            updates.append("suggestions_generated = ?")
            params.append(suggestions_generated)

        if suggestions_implemented is not None:
            updates.append("suggestions_implemented = ?")
            params.append(suggestions_implemented)

        updates.append("last_activity_at = ?")
        params.append(utc_now())
        params.append(session_id)

        query = f"UPDATE incept_auto_sessions SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()


def get_incept_auto_session(session_id):
    """Get an auto-mode session by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incept_auto_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_active_incept_auto_session():
    """Get the currently active auto-mode session if any."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM incept_auto_sessions
            WHERE status = 'running'
            ORDER BY started_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None


def get_incept_plus_settings():
    """Get Incept+ settings."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM incept_plus_settings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            result = dict(row)
            # Ensure suggestion_mode has default
            if 'suggestion_mode' not in result or not result['suggestion_mode']:
                result['suggestion_mode'] = 'cli'
            return result
        # Return defaults if no settings exist
        return {
            'auto_mode_enabled': 0,
            'auto_mode_interval': 300,
            'suggestion_mode': 'cli',
            'suggestion_model': 'claude-sonnet-4-20250514',
            'max_list_length': 10,
            'auto_implement_approved': 1
        }


def update_incept_plus_settings(auto_mode_enabled=None, auto_mode_interval=None,
                                suggestion_mode=None, suggestion_model=None,
                                max_list_length=None, auto_implement_approved=None):
    """Update Incept+ settings."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get existing settings
        settings = get_incept_plus_settings()

        # Update with new values
        if auto_mode_enabled is not None:
            settings['auto_mode_enabled'] = auto_mode_enabled
        if auto_mode_interval is not None:
            settings['auto_mode_interval'] = auto_mode_interval
        if suggestion_mode is not None:
            settings['suggestion_mode'] = suggestion_mode
        if suggestion_model is not None:
            settings['suggestion_model'] = suggestion_model
        if max_list_length is not None:
            settings['max_list_length'] = max_list_length
        if auto_implement_approved is not None:
            settings['auto_implement_approved'] = auto_implement_approved

        # Insert or replace
        cursor.execute("""
            INSERT OR REPLACE INTO incept_plus_settings
            (id, auto_mode_enabled, auto_mode_interval, suggestion_mode, suggestion_model,
             max_list_length, auto_implement_approved, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, (settings['auto_mode_enabled'], settings['auto_mode_interval'],
              settings['suggestion_mode'], settings['suggestion_model'],
              settings['max_list_length'], settings['auto_implement_approved'], utc_now()))
        conn.commit()


# ============================================================================
# AI ASSISTANT SETTINGS FUNCTIONS
# ============================================================================

def get_ai_settings():
    """Get AI assistant settings.

    Returns dict with provider, use_tailscale, tailscale_url, local_url.
    Defaults to local provider with tailscale enabled.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return dict(row)
        # Return defaults if no settings exist
        return {
            'id': 1,
            'provider': 'local',
            'use_tailscale': 1,
            'tailscale_url': None,
            'local_url': 'http://localhost:1234/v1',
            'updated_at': None
        }


def update_ai_settings(provider=None, use_tailscale=None, tailscale_url=None, local_url=None):
    """Update AI assistant settings.

    Args:
        provider: 'anthropic', 'local', 'cli', or 'cli_token'
        use_tailscale: 1 or 0 (whether to use tailscale URL for local provider)
        tailscale_url: URL for tailscale LLM endpoint
        local_url: URL for local LLM endpoint
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get existing settings
        settings = get_ai_settings()

        # Update with new values
        if provider is not None:
            settings['provider'] = provider
        if use_tailscale is not None:
            settings['use_tailscale'] = use_tailscale
        if tailscale_url is not None:
            settings['tailscale_url'] = tailscale_url
        if local_url is not None:
            settings['local_url'] = local_url

        # Insert or replace
        cursor.execute("""
            INSERT OR REPLACE INTO ai_settings
            (id, provider, use_tailscale, tailscale_url, local_url, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
        """, (settings['provider'], settings['use_tailscale'],
              settings['tailscale_url'], settings['local_url'], utc_now()))
        conn.commit()
        return settings


# ============================================================================
# PUSH NOTIFICATION SUBSCRIPTION FUNCTIONS
# ============================================================================

def save_push_subscription(endpoint, p256dh, auth, user_agent=None):
    """Save or update a push notification subscription.

    Args:
        endpoint: Push service endpoint URL
        p256dh: Public key for encryption
        auth: Authentication secret
        user_agent: Optional user agent string
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, created_at, active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                user_agent = excluded.user_agent,
                active = 1,
                last_used_at = ?
        """, (endpoint, p256dh, auth, user_agent, utc_now(), utc_now()))
        conn.commit()
        return cursor.lastrowid


def get_active_push_subscriptions():
    """Get all active push subscriptions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM push_subscriptions WHERE active = 1
        """)
        return [dict(row) for row in cursor.fetchall()]


def deactivate_push_subscription(endpoint):
    """Deactivate a push subscription (e.g., when it fails)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE push_subscriptions SET active = 0 WHERE endpoint = ?
        """, (endpoint,))
        conn.commit()
        return cursor.rowcount > 0


def delete_push_subscription(endpoint):
    """Delete a push subscription."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()
        return cursor.rowcount > 0


# ============================================================================
# IMPROVEMENTS QUEUE FUNCTIONS
# ============================================================================

def get_queued_improvements(include_implementing=True):
    """Get all improvements waiting in queue (accepted or implementing).

    Returns suggestions in order of priority and acceptance time.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        statuses = ['accepted']
        if include_implementing:
            statuses.append('implementing')

        placeholders = ','.join(['?' for _ in statuses])
        cursor.execute(f"""
            SELECT * FROM incept_suggestions
            WHERE status IN ({placeholders})
            ORDER BY priority DESC, accepted_at ASC, created_at ASC
        """, statuses)
        return [dict(row) for row in cursor.fetchall()]


def claim_next_improvement():
    """Atomically claim the next improvement from the queue.

    Returns the claimed suggestion or None if queue is empty.
    Only claims if no other improvement is currently being implemented.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Check if any improvement is already being implemented
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM incept_suggestions
            WHERE status = 'implementing'
        """)
        if cursor.fetchone()['cnt'] > 0:
            # Another improvement is being worked on
            return None

        # Get the next accepted improvement (highest priority, oldest acceptance)
        cursor.execute("""
            SELECT * FROM incept_suggestions
            WHERE status = 'accepted'
            ORDER BY priority DESC, accepted_at ASC, created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()

        if not row:
            return None

        suggestion = dict(row)

        # Atomically update status to 'implementing'
        cursor.execute("""
            UPDATE incept_suggestions
            SET status = 'implementing'
            WHERE id = ? AND status = 'accepted'
        """, (suggestion['id'],))

        if cursor.rowcount == 0:
            # Race condition - another process claimed it
            conn.rollback()
            return None

        conn.commit()
        return suggestion


def get_improvement_full_context(suggestion_id):
    """Get full context for an improvement including previous work.

    Returns suggestion details plus any related incept requests and their logs.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get the suggestion
        cursor.execute("SELECT * FROM incept_suggestions WHERE id = ?", (suggestion_id,))
        row = cursor.fetchone()
        if not row:
            return None

        suggestion = dict(row)

        # Find related incept requests (those that mention this improvement)
        cursor.execute("""
            SELECT * FROM claude_requests
            WHERE text LIKE ? OR text LIKE ?
            ORDER BY created_at DESC
        """, (f'%improvement #{suggestion_id}%', f'%suggestion #{suggestion_id}%'))
        related_requests = [dict(r) for r in cursor.fetchall()]

        # Get logs for each related request
        for req in related_requests:
            cursor.execute("""
                SELECT * FROM claude_logs
                WHERE request_id = ?
                ORDER BY timestamp ASC
            """, (req['id'],))
            req['logs'] = [dict(log) for log in cursor.fetchall()]

        suggestion['related_requests'] = related_requests

        # Check if there's an existing improvement record
        cursor.execute("""
            SELECT * FROM incept_improvements
            WHERE suggestion_id = ?
        """, (suggestion_id,))
        imp_row = cursor.fetchone()
        if imp_row:
            suggestion['improvement_record'] = dict(imp_row)

        return suggestion


def reset_stuck_improvements(timeout_minutes=30):
    """Reset improvements that have been 'implementing' for too long.

    Returns the number of reset improvements.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Find implementing suggestions that haven't been updated recently
        cursor.execute("""
            SELECT id, title FROM incept_suggestions
            WHERE status = 'implementing'
            AND (
                implemented_at IS NULL
                AND accepted_at < datetime('now', ?)
            )
        """, (f'-{timeout_minutes} minutes',))
        stuck = cursor.fetchall()

        if not stuck:
            return 0

        # Reset them back to 'accepted' so they can be re-processed
        stuck_ids = [row['id'] for row in stuck]
        placeholders = ','.join(['?' for _ in stuck_ids])
        cursor.execute(f"""
            UPDATE incept_suggestions
            SET status = 'accepted'
            WHERE id IN ({placeholders})
        """, stuck_ids)

        conn.commit()
        return len(stuck_ids)


def get_improvements_queue_status():
    """Get overview status of the improvements queue."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Count by status
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM incept_suggestions
            GROUP BY status
        """)
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Get current implementing suggestion
        cursor.execute("""
            SELECT id, title, accepted_at FROM incept_suggestions
            WHERE status = 'implementing'
            LIMIT 1
        """)
        current = cursor.fetchone()

        # Get next in queue
        cursor.execute("""
            SELECT id, title, priority FROM incept_suggestions
            WHERE status = 'accepted'
            ORDER BY priority DESC, accepted_at ASC
            LIMIT 1
        """)
        next_up = cursor.fetchone()

        return {
            'queued': status_counts.get('accepted', 0),
            'implementing': status_counts.get('implementing', 0),
            'implemented': status_counts.get('implemented', 0),
            'suggested': status_counts.get('suggested', 0),
            'rejected': status_counts.get('rejected', 0),
            'current': dict(current) if current else None,
            'next': dict(next_up) if next_up else None
        }


def pause_improvements_queue():
    """Pause all queued improvements by setting a flag."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO incept_plus_settings
            (id, auto_mode_enabled, auto_mode_interval, suggestion_mode, suggestion_model,
             max_list_length, auto_implement_approved, queue_paused, updated_at)
            SELECT 1, auto_mode_enabled, auto_mode_interval, suggestion_mode, suggestion_model,
                   max_list_length, auto_implement_approved, 1, ?
            FROM incept_plus_settings WHERE id = 1
        """, (utc_now(),))

        # If no existing settings, create with paused=1
        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO incept_plus_settings (id, queue_paused, updated_at)
                VALUES (1, 1, ?)
            """, (utc_now(),))
        conn.commit()


def resume_improvements_queue():
    """Resume the improvements queue."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE incept_plus_settings
            SET queue_paused = 0, updated_at = ?
            WHERE id = 1
        """, (utc_now(),))
        conn.commit()


def is_improvements_queue_paused():
    """Check if the improvements queue is paused."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT queue_paused FROM incept_plus_settings WHERE id = 1")
        row = cursor.fetchone()
        return bool(row and row['queue_paused'])


# App settings (general key-value store)
def _ensure_app_settings_table():
    """Ensure app_settings table exists."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def get_setting(key, default=None):
    """Get an app setting value."""
    _ensure_app_settings_table()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default


def set_setting(key, value):
    """Set an app setting value."""
    _ensure_app_settings_table()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, str(value), utc_now()))
        conn.commit()


def get_unread_count():
    """Get count of unread messages from target."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Get my_name and target_username from settings
        my_name = get_setting('my_name', '')
        target_username = get_setting('target_username', '')

        # Count only messages from the target user that are unread
        # If target_username is not set, fall back to counting messages not from my_name
        if target_username:
            cursor.execute("""
                SELECT COUNT(*) as count FROM messages
                WHERE (marked_read IS NULL OR marked_read = 0)
                AND sender_name LIKE ?
            """, (f'%{target_username}%',))
        elif my_name:
            cursor.execute("""
                SELECT COUNT(*) as count FROM messages
                WHERE (marked_read IS NULL OR marked_read = 0)
                AND sender_name NOT LIKE ?
            """, (f'%{my_name}%',))
        else:
            # If neither is set, count all unread (fallback behavior)
            cursor.execute("""
                SELECT COUNT(*) as count FROM messages
                WHERE marked_read IS NULL OR marked_read = 0
            """)

        row = cursor.fetchone()
        return row['count'] if row else 0


# Initialize database on import
init_db()
