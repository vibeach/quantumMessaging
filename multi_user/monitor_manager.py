"""
Monitor manager for multi-user Telegram monitoring.
Handles background monitoring of all users' Telegram accounts.
"""

import os
import threading
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class UserMonitor:
    """Monitors a single user's Telegram account."""

    def __init__(self, user_id: int, username: str, api_id: str, api_hash: str,
                 phone: str, target_username: str, session_path: str, db_path: str,
                 target_display_name: str = None):
        self.user_id = user_id
        self.username = username
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.target_username = target_username
        self.target_display_name = target_display_name or target_username
        self.session_path = session_path
        self.db_path = db_path

        self.client = None
        self.running = False
        self.loop = None
        self.thread = None
        self.last_error = None
        self.messages_today = 0

    async def _run_client(self):
        """Run the Telethon client."""
        from telethon import TelegramClient, events
        import sqlite3

        try:
            self.client = TelegramClient(
                self.session_path,
                int(self.api_id),
                self.api_hash
            )

            await self.client.start(phone=self.phone)
            logger.info(f"[{self.username}] Telegram client started")

            # Get target entity
            try:
                target = await self.client.get_entity(self.target_username)
                target_id = target.id
                logger.info(f"[{self.username}] Monitoring chat with {self.target_username} (ID: {target_id})")
            except Exception as e:
                logger.error(f"[{self.username}] Could not find target {self.target_username}: {e}")
                self.last_error = f"Could not find target: {e}"
                return

            # Message handler
            @self.client.on(events.NewMessage(chats=target_id))
            async def handle_new_message(event):
                try:
                    await self._save_message(event.message, target_id)
                    self.messages_today += 1
                except Exception as e:
                    logger.error(f"[{self.username}] Error handling message: {e}")

            # Message edited handler
            @self.client.on(events.MessageEdited(chats=target_id))
            async def handle_edit(event):
                try:
                    await self._update_message(event.message, target_id)
                except Exception as e:
                    logger.error(f"[{self.username}] Error handling edit: {e}")

            # Message deleted handler
            @self.client.on(events.MessageDeleted(chats=target_id))
            async def handle_delete(event):
                try:
                    await self._mark_deleted(event.deleted_ids, target_id)
                except Exception as e:
                    logger.error(f"[{self.username}] Error handling delete: {e}")

            # Message read handler
            @self.client.on(events.MessageRead(chats=target_id))
            async def handle_read(event):
                try:
                    await self._mark_read_by_target(event.max_id, target_id)
                except Exception as e:
                    logger.error(f"[{self.username}] Error handling read: {e}")

            # Run until disconnected
            self.running = True
            await self.client.run_until_disconnected()

        except Exception as e:
            logger.error(f"[{self.username}] Client error: {e}")
            self.last_error = str(e)
        finally:
            self.running = False

    async def _save_message(self, message, chat_id):
        """Save a message to user's database."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        sender = await message.get_sender()
        sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', 'Unknown')

        # Check if from me or from target
        me = await self.client.get_me()
        if sender.id == me.id:
            sender_name = self.username  # Use logged-in username as "me"
        else:
            sender_name = self.target_display_name

        text = message.text or ''
        media_type = None
        media_path = None

        if message.media:
            if hasattr(message.media, 'photo'):
                media_type = 'photo'
            elif hasattr(message.media, 'document'):
                if message.voice:
                    media_type = 'voice'
                elif message.video_note:
                    media_type = 'video_note'
                elif message.video:
                    media_type = 'video'
                elif message.audio:
                    media_type = 'audio'
                else:
                    media_type = 'document'

        timestamp = message.date.strftime('%Y-%m-%d %H:%M:%S')

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO messages
                (message_id, chat_id, sender_id, sender_name, text, media_type, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (message.id, chat_id, sender.id, sender_name, text, media_type, timestamp))
            conn.commit()
            logger.info(f"[{self.username}] Saved message {message.id}")
        except Exception as e:
            logger.error(f"[{self.username}] Error saving message: {e}")
        finally:
            conn.close()

    async def _update_message(self, message, chat_id):
        """Update an edited message."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE messages SET text = ? WHERE message_id = ? AND chat_id = ?
            """, (message.text or '', message.id, chat_id))
            conn.commit()
        except Exception as e:
            logger.error(f"[{self.username}] Error updating message: {e}")
        finally:
            conn.close()

    async def _mark_deleted(self, message_ids, chat_id):
        """Mark messages as deleted."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            for msg_id in message_ids:
                cursor.execute("""
                    UPDATE messages SET deleted = 1, deleted_at = ?
                    WHERE message_id = ? AND chat_id = ?
                """, (datetime.utcnow().isoformat(), msg_id, chat_id))
            conn.commit()
        except Exception as e:
            logger.error(f"[{self.username}] Error marking deleted: {e}")
        finally:
            conn.close()

    async def _mark_read_by_target(self, max_id, chat_id):
        """Mark messages as read by target."""
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Mark my messages as seen by target
            cursor.execute("""
                UPDATE messages
                SET seen_by_target = 1, seen_by_target_at = ?
                WHERE message_id <= ? AND chat_id = ? AND sender_name = ?
                AND (seen_by_target IS NULL OR seen_by_target = 0)
            """, (datetime.utcnow().isoformat(), max_id, chat_id, self.username))
            conn.commit()
        except Exception as e:
            logger.error(f"[{self.username}] Error marking read: {e}")
        finally:
            conn.close()

    def start(self):
        """Start the monitor in a background thread."""
        if self.running:
            return

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._run_client())
            finally:
                self.loop.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        logger.info(f"[{self.username}] Monitor thread started")

    def stop(self):
        """Stop the monitor."""
        self.running = False
        if self.client and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)
            except Exception:
                pass
        logger.info(f"[{self.username}] Monitor stopped")


class MonitorManager:
    """Manages monitors for all users."""

    def __init__(self, user_manager):
        self.user_manager = user_manager
        self.monitors: Dict[int, UserMonitor] = {}
        self.watchdog_thread = None
        self.running = False

    def start_all(self):
        """Start monitors for all users with complete setup."""
        users = self.user_manager.get_users_for_monitoring()

        for user in users:
            self.start_user_monitor(user)

        # Start watchdog
        self.running = True
        self.watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self.watchdog_thread.start()

        logger.info(f"MonitorManager started with {len(self.monitors)} monitors")

    def start_user_monitor(self, user: dict):
        """Start monitor for a specific user."""
        user_id = user['id']

        if user_id in self.monitors and self.monitors[user_id].running:
            return  # Already running

        username = user['username']
        session_path = self.user_manager.get_user_session_path(username)
        db_path = self.user_manager.get_user_db_path(username)

        monitor = UserMonitor(
            user_id=user_id,
            username=username,
            api_id=user.get('api_id', ''),
            api_hash=user.get('api_hash', ''),
            phone=user.get('phone', ''),
            target_username=user.get('target_username', ''),
            target_display_name=user.get('target_display_name'),
            session_path=session_path,
            db_path=db_path
        )

        self.monitors[user_id] = monitor
        monitor.start()

        self.user_manager.update_monitor_status(user_id, is_running=True)

    def stop_user_monitor(self, user_id: int):
        """Stop monitor for a specific user."""
        if user_id in self.monitors:
            self.monitors[user_id].stop()
            del self.monitors[user_id]
            self.user_manager.update_monitor_status(user_id, is_running=False)

    def restart_user_monitor(self, user_id: int):
        """Restart monitor for a specific user."""
        self.stop_user_monitor(user_id)

        user = self.user_manager.get_user(user_id)
        if user:
            config = self.user_manager.get_telegram_config(user_id, decrypt=True)
            if config and config.get('setup_complete'):
                user_data = {
                    'id': user_id,
                    'username': user['username'],
                    'api_id': config.get('api_id', ''),
                    'api_hash': config.get('api_hash', ''),
                    'phone': config.get('phone', ''),
                    'target_username': config.get('target_username', ''),
                    'target_display_name': config.get('target_display_name')
                }
                self.start_user_monitor(user_data)

    def _watchdog(self):
        """Watchdog thread to restart dead monitors."""
        while self.running:
            try:
                for user_id, monitor in list(self.monitors.items()):
                    # Update heartbeat
                    self.user_manager.update_monitor_status(
                        user_id,
                        is_running=monitor.running,
                        last_error=monitor.last_error,
                        messages_today=monitor.messages_today
                    )

                    # Restart if not running
                    if not monitor.running and not monitor.last_error:
                        logger.warning(f"[{monitor.username}] Monitor died, restarting...")
                        self.restart_user_monitor(user_id)

                # Check for new users
                users = self.user_manager.get_users_for_monitoring()
                for user in users:
                    if user['id'] not in self.monitors:
                        logger.info(f"[{user['username']}] New user detected, starting monitor...")
                        self.start_user_monitor(user)

            except Exception as e:
                logger.error(f"Watchdog error: {e}")

            time.sleep(60)  # Check every 60 seconds

    def stop_all(self):
        """Stop all monitors."""
        self.running = False
        for user_id in list(self.monitors.keys()):
            self.stop_user_monitor(user_id)

    def get_status(self) -> Dict:
        """Get status of all monitors."""
        return {
            user_id: {
                'username': m.username,
                'running': m.running,
                'last_error': m.last_error,
                'messages_today': m.messages_today
            }
            for user_id, m in self.monitors.items()
        }
