#!/usr/bin/env python3
"""
Telegram Message Monitor
Runs 24/7 to capture messages and online status changes.
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime

import aiohttp

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (
    UserStatusOnline,
    UserStatusOffline,
    UserStatusRecently,
    PeerUser,
    MessageMediaPhoto,
    MessageMediaDocument,
    ReactionEmoji,
    ReactionCustomEmoji,
)

import config
import database


def get_local_ip():
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


# Dashboard processes
dashboard_processes = []


def start_dashboards():
    """Start both dashboard servers."""
    global dashboard_processes

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Start v3 dashboard (Home Assistant style)
    v3_path = os.path.join(script_dir, "dashboard_v3.py")
    if os.path.exists(v3_path):
        p1 = subprocess.Popen(
            [sys.executable, v3_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        dashboard_processes.append(p1)
        logger.info("Started Dashboard v3 (Home Assistant)")

    # Start v5 dashboard (Blog style)
    v5_path = os.path.join(script_dir, "dashboard_v5.py")
    if os.path.exists(v5_path):
        p2 = subprocess.Popen(
            [sys.executable, v5_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        dashboard_processes.append(p2)
        logger.info("Started Dashboard v5 (Blog)")

    # Start v6 dashboard (Hourly)
    v6_path = os.path.join(script_dir, "dashboard_v6.py")
    if os.path.exists(v6_path):
        p3 = subprocess.Popen(
            [sys.executable, v6_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        dashboard_processes.append(p3)
        logger.info("Started Dashboard v6 (Hourly)")


def stop_dashboards():
    """Stop dashboard servers."""
    for p in dashboard_processes:
        try:
            p.terminate()
        except:
            pass

# Ensure media folder exists
os.makedirs(config.MEDIA_PATH, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create client (use StringSession for cloud deployment)
SESSION_STRING = os.getenv("SESSION_STRING")
if SESSION_STRING:
    client = TelegramClient(
        StringSession(SESSION_STRING),
        config.API_ID,
        config.API_HASH
    )
else:
    client = TelegramClient(
        config.SESSION_NAME,
        config.API_ID,
        config.API_HASH
    )

# Store target user info once resolved
target_user_id = None
target_chat_id = None


async def resolve_target_user():
    """Resolve target user from username or ID."""
    global target_user_id, target_chat_id

    target = config.TARGET_USER

    try:
        # Try to get entity (works with username or ID)
        if target.isdigit():
            entity = await client.get_entity(int(target))
        else:
            entity = await client.get_entity(target)

        target_user_id = entity.id
        target_chat_id = entity.id  # For private chats, chat_id = user_id

        logger.info(f"Monitoring user: {getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')} (ID: {target_user_id})")
        return entity

    except Exception as e:
        logger.error(f"Could not resolve target user '{target}': {e}")
        logger.info("You can find user ID by forwarding their message to @userinfobot on Telegram")
        return None


def get_media_type(message):
    """Determine media type from message."""
    if message.media is None:
        return None
    if isinstance(message.media, MessageMediaPhoto):
        return "photo"
    if isinstance(message.media, MessageMediaDocument):
        # Check for video_note (circles) first
        if message.video_note:
            return "video_note"
        # Check for voice messages
        if message.voice:
            return "audio"

        mime = getattr(message.media.document, 'mime_type', '')
        if 'video' in mime:
            return "video"
        if 'audio' in mime or 'voice' in mime:
            return "audio"
        if 'sticker' in mime or message.sticker:
            return "sticker"
        return "document"
    return "other"


def get_reactions(message):
    """Extract reactions from a message as JSON string."""
    if not message.reactions:
        return None

    reactions = []
    try:
        for result in message.reactions.results:
            reaction = result.reaction
            emoji = None
            if isinstance(reaction, ReactionEmoji):
                emoji = reaction.emoticon
            elif isinstance(reaction, ReactionCustomEmoji):
                emoji = f"custom:{reaction.document_id}"

            if emoji:
                reactions.append({
                    'emoji': emoji,
                    'count': result.count
                })
    except Exception as e:
        logger.debug(f"Error extracting reactions: {e}")
        return None

    return json.dumps(reactions) if reactions else None


async def download_media(message):
    """Download media from message and return the file path."""
    if not message.media:
        return None

    try:
        # Generate filename based on message id and timestamp
        timestamp = message.date.strftime("%Y%m%d_%H%M%S") if message.date else "unknown"

        # Determine extension based on media type
        if isinstance(message.media, MessageMediaPhoto):
            ext = "jpg"
            prefix = "photo"
        elif isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            mime = getattr(doc, 'mime_type', '')

            # Check for video_note (circles) first
            if message.video_note:
                ext = "mp4"
                prefix = "circle"
            # Check for voice messages
            elif message.voice or 'audio' in mime or 'voice' in mime or 'ogg' in mime:
                ext = "ogg"
                prefix = "voice"
            # Check for stickers
            elif 'webp' in mime or message.sticker:
                ext = "webp"
                prefix = "sticker"
            # Check for regular videos
            elif 'video' in mime:
                ext = "mp4"
                prefix = "video"
            else:
                ext = mime.split('/')[-1] if '/' in mime else "bin"
                prefix = "file"
        else:
            ext = "bin"
            prefix = "media"

        filename = f"{prefix}_{message.id}_{timestamp}.{ext}"
        filepath = os.path.join(config.MEDIA_PATH, filename)

        # Download the file
        await message.download_media(file=filepath)
        logger.info(f"Media saved: {filename}")

        return filename

    except Exception as e:
        logger.error(f"Failed to download media: {e}")
        return None


async def trigger_push_notification(sender_name, message_text=None, has_media=False):
    """
    Trigger a push notification for incoming messages.
    This sends a Home Assistant branded notification directly via Web Push.
    """
    try:
        import push_notifications

        # Obfuscate message content for privacy
        if has_media:
            preview = "Movement"
        else:
            # Count characters in the message
            char_count = len(message_text) if message_text else 0
            preview = f"Light switch ({char_count} characters)"

        # Send push notification with obfuscated message content
        result = push_notifications.send_new_message_notification(
            sender_name=sender_name,
            message_preview=preview
        )

        if result["success"] > 0:
            logger.debug(f"Push notification sent to {result['success']} subscribers")
        elif result["total"] == 0:
            logger.debug("No push subscribers registered")
        else:
            logger.warning(f"Push notification failed for all {result['failed']} subscribers")

    except Exception as e:
        logger.warning(f"Failed to trigger push notification: {e}")


@client.on(events.NewMessage)
async def handle_new_message(event):
    """Handle new incoming messages."""
    message = event.message

    # Check if message is from target user (in private chat)
    if target_user_id:
        # Private chat with target
        if event.is_private and event.sender_id == target_user_id:
            pass  # This is our target
        # Or we sent a message to target
        elif event.is_private and event.chat_id == target_user_id:
            pass  # Message in target chat (from us)
        else:
            return  # Not from/to target user

    sender = await event.get_sender()
    sender_name = f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip()

    media_type = get_media_type(message)
    media_path = None
    reactions = get_reactions(message)

    # Download media if present
    if message.media:
        media_path = await download_media(message)

    database.save_message(
        message_id=message.id,
        chat_id=event.chat_id,
        sender_id=event.sender_id,
        sender_name=sender_name or "Unknown",
        text=message.text or message.message or "[Media]",
        media_type=media_type,
        media_path=media_path,
        timestamp=message.date,
        reactions=reactions
    )

    logger.info(f"Message saved: [{sender_name}] {(message.text or '[Media]')[:50]}...")

    # Trigger push notification for incoming messages (from target user)
    if event.is_private and event.sender_id == target_user_id:
        asyncio.create_task(trigger_push_notification(
            sender_name,
            message.text or message.message,
            has_media=bool(media_type)
        ))

    # Generate snapshots for videos immediately after saving
    if media_type in ['video', 'video_note', 'circle'] and media_path:
        try:
            import media_processor
            # Mark as processing first so UI can show spinner
            database.update_media_metadata(
                message.id, event.chat_id,
                snapshots='processing'
            )

            full_path = os.path.join(config.MEDIA_PATH, media_path)
            metadata = media_processor.process_media_file(full_path, media_type)
            if metadata:
                snapshots_str = ','.join(metadata.get('snapshots', [])) if metadata.get('snapshots') else ''
                database.update_media_metadata(
                    message.id, event.chat_id,
                    duration=metadata.get('duration'),
                    width=metadata.get('width'),
                    height=metadata.get('height'),
                    size=metadata.get('size'),
                    thumbnail=metadata.get('thumbnail'),
                    snapshots=snapshots_str
                )
                logger.info(f"Generated {len(metadata.get('snapshots', []))} snapshots for {media_path}")
            else:
                # Clear processing state if failed
                database.update_media_metadata(message.id, event.chat_id, snapshots='')
        except Exception as e:
            logger.warning(f"Failed to generate snapshots for {media_path}: {e}")
            # Clear processing state on error
            try:
                database.update_media_metadata(message.id, event.chat_id, snapshots='')
            except:
                pass

    # Transcribe voice/video_note using Telegram's built-in transcription
    # Note: Only voice messages and video_note (circles) are supported, NOT regular videos
    is_transcribable = message.voice or message.video_note
    if is_transcribable:
        try:
            import transcriber
            logger.info(f"Requesting Telegram transcription for: {media_type}")
            # Set status to pending before starting
            database.set_transcript_status(message.id, event.chat_id, 'pending')

            transcript = await transcriber.transcribe_with_telegram(client, message)
            if transcript:
                database.update_message_transcript(message.id, event.chat_id, transcript, 'completed')
                logger.info(f"Transcript saved: {transcript[:50]}...")
            else:
                database.set_transcript_status(message.id, event.chat_id, 'failed')
                logger.warning(f"Transcription returned empty for message {message.id}")
        except Exception as e:
            database.set_transcript_status(message.id, event.chat_id, 'failed')
            logger.error(f"Transcription failed: {e}")

    # IMPORTANT: Do NOT mark as read - this keeps it unread on sender's side
    # Telethon doesn't auto-mark as read by default, but we ensure it here
    # by not calling event.mark_read()


@client.on(events.MessageDeleted)
async def handle_deleted_message(event):
    """Handle deleted messages - mark them in our database."""
    for msg_id in event.deleted_ids:
        # Try to mark in database
        chat_id = getattr(event, 'chat_id', None) or target_chat_id

        if database.mark_message_deleted(msg_id, chat_id):
            logger.info(f"Message {msg_id} marked as deleted")
        else:
            logger.debug(f"Deleted message {msg_id} not found in database (might be from another chat)")


@client.on(events.MessageEdited)
async def handle_message_edited(event):
    """Handle message edits - update reactions if present."""
    message = event.message

    # Only track messages from/to target
    if target_user_id:
        if not (event.is_private and (event.sender_id == target_user_id or event.chat_id == target_user_id)):
            return

    # Check for reactions update
    reactions = get_reactions(message)
    if reactions:
        database.update_message_reactions(message.id, event.chat_id, reactions)
        logger.info(f"Reactions updated for message {message.id}")


@client.on(events.Raw)
async def handle_raw_update(event):
    """Handle raw updates including reaction changes."""
    from telethon.tl.types import UpdateMessageReactions

    if isinstance(event, UpdateMessageReactions):
        try:
            # Extract reactions
            reactions = []
            if event.reactions and event.reactions.results:
                for result in event.reactions.results:
                    reaction = result.reaction
                    emoji = None
                    if isinstance(reaction, ReactionEmoji):
                        emoji = reaction.emoticon
                    elif isinstance(reaction, ReactionCustomEmoji):
                        emoji = f"custom:{reaction.document_id}"

                    if emoji:
                        reactions.append({
                            'emoji': emoji,
                            'count': result.count
                        })

            reactions_json = json.dumps(reactions) if reactions else None

            # Get chat_id from the peer
            chat_id = None
            if hasattr(event, 'peer'):
                if hasattr(event.peer, 'user_id'):
                    chat_id = event.peer.user_id
                elif hasattr(event.peer, 'chat_id'):
                    chat_id = event.peer.chat_id
                elif hasattr(event.peer, 'channel_id'):
                    chat_id = event.peer.channel_id

            if chat_id and (not target_user_id or chat_id == target_user_id):
                database.update_message_reactions(event.msg_id, chat_id, reactions_json)
                logger.info(f"Reaction update: message {event.msg_id} -> {reactions_json}")

        except Exception as e:
            logger.debug(f"Error processing reaction update: {e}")


@client.on(events.UserUpdate)
async def handle_user_update(event):
    """Handle user status updates (online/offline)."""
    # Only track target user
    if target_user_id and event.user_id != target_user_id:
        return

    user = await client.get_entity(event.user_id)
    username = getattr(user, 'username', '') or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()

    status = event.status
    last_seen = None

    if isinstance(status, UserStatusOnline):
        status_text = "online"
        logger.info(f"User {username} is now ONLINE")
    elif isinstance(status, UserStatusOffline):
        status_text = "offline"
        last_seen = status.was_online
        logger.info(f"User {username} went OFFLINE (last seen: {last_seen})")
    elif isinstance(status, UserStatusRecently):
        status_text = "recently"
        logger.info(f"User {username} was recently online")
    else:
        status_text = str(type(status).__name__)
        logger.info(f"User {username} status: {status_text}")

    database.save_online_status(
        user_id=event.user_id,
        username=username,
        status=status_text,
        last_seen=last_seen
    )


async def check_user_status():
    """Periodically check target user's online status."""
    last_status = None

    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds for better accuracy

            if not target_user_id:
                continue

            user = await client.get_entity(target_user_id)
            status = user.status
            username = getattr(user, 'username', '') or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()

            # Determine status text
            if isinstance(status, UserStatusOnline):
                status_text = "online"
            elif isinstance(status, UserStatusOffline):
                status_text = "offline"
            elif isinstance(status, UserStatusRecently):
                status_text = "recently"
            else:
                status_text = str(type(status).__name__) if status else "unknown"

            # Only save if status changed
            if status_text != last_status:
                last_seen = None
                if isinstance(status, UserStatusOffline):
                    last_seen = status.was_online

                database.save_online_status(
                    user_id=target_user_id,
                    username=username,
                    status=status_text,
                    last_seen=last_seen
                )
                logger.info(f"Status check: {username} is {status_text.upper()}")
                last_status = status_text

        except Exception as e:
            logger.debug(f"Status check error: {e}")


async def process_outgoing_messages():
    """Check for and send pending outgoing messages (text and media)."""
    # Get our own info for sender name
    me = None
    my_name = None

    while True:
        try:
            await asyncio.sleep(3)  # Check every 3 seconds

            if not target_user_id:
                continue

            # Get our info once
            if me is None:
                me = await client.get_me()
                my_name = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip()

            pending = database.get_pending_messages()

            # Process one at a time with delay for reliability
            for msg in pending[:1]:  # Only process first pending message
                try:
                    text = msg['text']

                    # Check if this is a media message
                    if text.startswith('MEDIA:'):
                        # Format: MEDIA:type:filepath
                        parts = text.split(':', 2)
                        if len(parts) >= 3:
                            media_type = parts[1]
                            filepath = parts[2]

                            if media_type == 'circle':
                                # Send as video note (circle video)
                                # Video notes must be square - process with ffmpeg
                                import subprocess
                                import uuid
                                import time

                                # Check file exists
                                if not os.path.exists(filepath):
                                    logger.error(f"Circle video file not found: {filepath}")
                                    database.add_system_log('media', 'send_failed', 'error',
                                                          f'Circle video file not found: {filepath}',
                                                          f'Queue ID: {msg["id"]}')
                                    database.mark_message_retry(msg['id'], f"File not found: {filepath}")
                                    continue

                                # Use unique filename to avoid conflicts
                                unique_id = uuid.uuid4().hex[:8]
                                processed_path = filepath.rsplit('.', 1)[0] + f'_circle_{unique_id}.mp4'
                                send_path = filepath  # Default to original

                                logger.info(f"Processing circle video: {filepath}")
                                database.add_system_log('media', 'process_start', 'info',
                                                      f'Processing circle video: {os.path.basename(filepath)}',
                                                      f'Output: {os.path.basename(processed_path)}')

                                try:
                                    # Less aggressive crop: scale to fit 480x480 then pad to square
                                    result = subprocess.run([
                                        'ffmpeg', '-y', '-i', filepath,
                                        '-vf', 'scale=480:480:force_original_aspect_ratio=increase,crop=480:480,scale=384:384',
                                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                                        '-c:a', 'aac', '-b:a', '128k', '-t', '60',
                                        '-movflags', '+faststart',
                                        processed_path
                                    ], capture_output=True, text=True, timeout=180)

                                    if result.returncode == 0 and os.path.exists(processed_path):
                                        send_path = processed_path
                                        file_size = os.path.getsize(processed_path)
                                        logger.info(f"Processed video circle: {processed_path} ({file_size} bytes)")
                                        database.add_system_log('media', 'process_complete', 'success',
                                                              f'Circle video processed: {os.path.basename(processed_path)}',
                                                              f'Size: {file_size} bytes')
                                    else:
                                        error_details = result.stderr[:300] if result.stderr else 'no error'
                                        logger.warning(f"ffmpeg failed (code {result.returncode}): {error_details}")
                                        database.add_system_log('media', 'process_warning', 'warning',
                                                              f'ffmpeg processing issue (code {result.returncode})',
                                                              error_details)
                                except subprocess.TimeoutExpired:
                                    logger.warning("ffmpeg timed out after 180s")
                                    database.add_system_log('media', 'process_timeout', 'error',
                                                          'ffmpeg processing timed out after 180s',
                                                          f'File: {os.path.basename(filepath)}')
                                except Exception as e:
                                    logger.warning(f"ffmpeg processing failed: {e}")
                                    database.add_system_log('media', 'process_error', 'error',
                                                          f'ffmpeg processing failed: {str(e)}',
                                                          f'File: {os.path.basename(filepath)}')

                                # Small delay before sending
                                await asyncio.sleep(1)

                                try:
                                    logger.info(f"Sending circle video: {send_path}")
                                    database.add_system_log('media', 'send_start', 'info',
                                                          f'Sending circle video to Telegram',
                                                          f'File: {os.path.basename(send_path)}, Queue ID: {msg["id"]}')
                                    sent_msg = await client.send_file(
                                        target_user_id,
                                        send_path,
                                        video_note=True
                                    )
                                    display_type = 'video_note'
                                    logger.info(f"Circle video sent successfully: msg_id={sent_msg.id}")
                                    database.add_system_log('media', 'send_success', 'success',
                                                          f'Circle video sent successfully',
                                                          f'Telegram msg_id: {sent_msg.id}, File: {os.path.basename(send_path)}')
                                except Exception as send_err:
                                    error_str = str(send_err)
                                    logger.error(f"Failed to send video circle: {error_str}")
                                    database.add_system_log('media', 'send_failed', 'error',
                                                          f'Failed to send circle video: {error_str}',
                                                          f'File: {os.path.basename(send_path)}, Queue ID: {msg["id"]}')
                                    retry_count = database.mark_message_retry(msg['id'], error_str)
                                    logger.info(f"Retry count: {retry_count}/5")
                                    # Clean up processed file on failure
                                    if send_path != filepath and os.path.exists(send_path):
                                        try:
                                            os.remove(send_path)
                                        except:
                                            pass
                                    continue  # Skip to next iteration, will retry

                                # Clean up processed file after successful send
                                if send_path != filepath and os.path.exists(send_path):
                                    try:
                                        os.remove(send_path)
                                        logger.debug(f"Cleaned up: {send_path}")
                                    except Exception as cleanup_err:
                                        logger.debug(f"Cleanup failed: {cleanup_err}")
                            elif media_type == 'video':
                                logger.info(f"Sending video: {filepath}")
                                database.add_system_log('media', 'send_start', 'info',
                                                      f'Sending video to Telegram',
                                                      f'File: {os.path.basename(filepath)}, Queue ID: {msg["id"]}')
                                try:
                                    sent_msg = await client.send_file(
                                        target_user_id,
                                        filepath,
                                        video_note=False
                                    )
                                    display_type = 'video'
                                    logger.info(f"Video sent successfully: msg_id={sent_msg.id}")
                                    database.add_system_log('media', 'send_success', 'success',
                                                          f'Video sent successfully',
                                                          f'Telegram msg_id: {sent_msg.id}, File: {os.path.basename(filepath)}')
                                except Exception as e:
                                    error_str = str(e)
                                    logger.error(f"Failed to send video: {error_str}")
                                    database.add_system_log('media', 'send_failed', 'error',
                                                          f'Failed to send video: {error_str}',
                                                          f'File: {os.path.basename(filepath)}, Queue ID: {msg["id"]}')
                                    retry_count = database.mark_message_retry(msg['id'], error_str)
                                    logger.info(f"Retry count: {retry_count}/5")
                                    continue
                            else:  # photo
                                logger.info(f"Sending photo: {filepath}")
                                database.add_system_log('media', 'send_start', 'info',
                                                      f'Sending photo to Telegram',
                                                      f'File: {os.path.basename(filepath)}, Queue ID: {msg["id"]}')
                                try:
                                    sent_msg = await client.send_file(
                                        target_user_id,
                                        filepath
                                    )
                                    display_type = 'photo'
                                    logger.info(f"Photo sent successfully: msg_id={sent_msg.id}")
                                    database.add_system_log('media', 'send_success', 'success',
                                                          f'Photo sent successfully',
                                                          f'Telegram msg_id: {sent_msg.id}, File: {os.path.basename(filepath)}')
                                except Exception as e:
                                    error_str = str(e)
                                    logger.error(f"Failed to send photo: {error_str}")
                                    database.add_system_log('media', 'send_failed', 'error',
                                                          f'Failed to send photo: {error_str}',
                                                          f'File: {os.path.basename(filepath)}, Queue ID: {msg["id"]}')
                                    retry_count = database.mark_message_retry(msg['id'], error_str)
                                    logger.info(f"Retry count: {retry_count}/5")
                                    continue

                            database.mark_message_sent(msg['id'])

                            # Save to messages table
                            database.save_message(
                                message_id=sent_msg.id,
                                chat_id=target_user_id,
                                sender_id=me.id,
                                sender_name=my_name,
                                text=f"[{display_type}]",
                                media_type=display_type,
                                media_path=os.path.basename(filepath),
                                timestamp=sent_msg.date
                            )

                            # Generate snapshots for sent videos
                            if display_type in ['video', 'video_note']:
                                try:
                                    import media_processor
                                    metadata = media_processor.process_media_file(filepath, display_type)
                                    if metadata:
                                        snapshots_str = ','.join(metadata.get('snapshots', [])) if metadata.get('snapshots') else None
                                        database.update_media_metadata(
                                            sent_msg.id, target_user_id,
                                            duration=metadata.get('duration'),
                                            width=metadata.get('width'),
                                            height=metadata.get('height'),
                                            size=metadata.get('size'),
                                            thumbnail=metadata.get('thumbnail'),
                                            snapshots=snapshots_str
                                        )
                                        logger.info(f"Generated snapshots for sent {display_type}")
                                except Exception as e:
                                    logger.warning(f"Failed to generate snapshots for sent video: {e}")

                            logger.info(f"Sent {display_type}: {filepath}")
                        continue

                    # Regular text message
                    # Check if this is a reply
                    reply_to = msg.get('reply_to_message_id')
                    sent_msg = await client.send_message(target_user_id, text, reply_to=reply_to)
                    database.mark_message_sent(msg['id'])

                    # Save to messages table so it shows in dashboard
                    database.save_message(
                        message_id=sent_msg.id,
                        chat_id=target_user_id,
                        sender_id=me.id,
                        sender_name=my_name,
                        text=text,
                        media_type=None,
                        media_path=None,
                        timestamp=sent_msg.date
                    )

                    logger.info(f"Sent message: {text[:50]}...")
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"Failed to send message {msg['id']}: {error_str}")
                    retry_count = database.mark_message_retry(msg['id'], error_str)
                    logger.info(f"Message {msg['id']} retry count: {retry_count}/5")

                # Small delay between messages for rate limiting
                await asyncio.sleep(1)

        except Exception as e:
            logger.debug(f"Outgoing message check error: {e}")


async def process_read_marks():
    """Process pending read mark requests - marks messages as read on Telegram."""
    while True:
        try:
            await asyncio.sleep(2)  # Check every 2 seconds

            if not target_user_id:
                continue

            pending = database.get_pending_read_marks()
            for mark in pending:
                try:
                    # Mark the message as read on Telegram
                    # This sends read receipt to sender
                    await client.send_read_acknowledge(
                        entity=mark['chat_id'],
                        max_id=mark['message_id']
                    )

                    # Update database
                    database.complete_read_mark(mark['id'], mark['message_id'], mark['chat_id'])
                    logger.info(f"Marked message {mark['message_id']} as read")

                except Exception as e:
                    logger.error(f"Failed to mark message {mark['id']} as read: {e}")

        except Exception as e:
            logger.debug(f"Read mark check error: {e}")


async def process_reactions():
    """Process pending reaction requests - sends reactions on Telegram."""
    while True:
        try:
            await asyncio.sleep(2)  # Check every 2 seconds

            if not target_user_id:
                continue

            pending = database.get_pending_reactions()
            for react in pending:
                try:
                    from telethon.tl.functions.messages import SendReactionRequest
                    from telethon.tl.types import ReactionEmoji

                    # Map emoji name to actual emoji
                    emoji_map = {
                        'fire': '🔥',
                        'heart': '❤️',
                        'unicorn': '🦄',
                        'thumbsup': '👍',
                        'thumbsdown': '👎',
                        'laugh': '😂',
                        'sad': '😢',
                        'wow': '😮',
                    }
                    emoji = emoji_map.get(react['emoji'], react['emoji'])

                    await client(SendReactionRequest(
                        peer=react['chat_id'],
                        msg_id=react['message_id'],
                        reaction=[ReactionEmoji(emoticon=emoji)]
                    ))

                    database.complete_reaction(react['id'])
                    logger.info(f"Sent reaction {emoji} to message {react['message_id']}")

                except Exception as e:
                    retry_count = database.fail_reaction(react['id'], str(e)[:200])
                    logger.error(f"Failed to send reaction {react['id']} (attempt {retry_count}/3): {e}")

        except Exception as e:
            logger.debug(f"Reaction check error: {e}")


async def process_deletes():
    """Process pending delete requests - deletes messages on Telegram."""
    while True:
        try:
            await asyncio.sleep(2)  # Check every 2 seconds

            if not target_user_id:
                continue

            pending = database.get_pending_deletes()
            for delete in pending:
                try:
                    # Delete the message on Telegram
                    await client.delete_messages(
                        entity=delete['chat_id'],
                        message_ids=[delete['message_id']]
                    )

                    database.complete_delete(delete['id'], delete['message_id'], delete['chat_id'])
                    logger.info(f"Deleted message {delete['message_id']}")

                except Exception as e:
                    logger.error(f"Failed to delete message {delete['id']}: {e}")

        except Exception as e:
            logger.debug(f"Delete check error: {e}")


async def sync_read_status():
    """Sync read status in both directions:
    1. Check if target has read our messages (outbox)
    2. Check if we have read target's messages (inbox) - e.g. from phone app
    """
    me = None
    my_name = None

    while True:
        try:
            await asyncio.sleep(15)  # Check every 15 seconds

            if not target_user_id:
                continue

            # Get our info once
            if me is None:
                me = await client.get_me()
                my_name = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip()

            try:
                # Get dialog info for target
                async for d in client.iter_dialogs():
                    if d.entity.id == target_user_id:
                        # 1. Check outbox - messages WE sent that TARGET has read
                        read_outbox_max_id = d.dialog.read_outbox_max_id
                        unseen = database.get_unseen_outgoing_messages(me.id, target_user_id)
                        for msg in unseen:
                            if msg['message_id'] <= read_outbox_max_id:
                                if database.mark_seen_by_target(msg['message_id'], target_user_id):
                                    logger.info(f"Message {msg['message_id']} seen by target")

                        # 2. Check inbox - messages TARGET sent that WE have read
                        read_inbox_max_id = d.dialog.read_inbox_max_id
                        updated = database.sync_read_status_from_telegram(my_name, target_user_id, read_inbox_max_id)
                        if updated > 0:
                            logger.info(f"Synced {updated} messages as read from Telegram app")

                        break
            except Exception as e:
                logger.debug(f"Could not sync read status: {e}")

        except Exception as e:
            logger.debug(f"Read status sync error: {e}")


async def main():
    """Main entry point."""
    logger.info("Starting Telegram Monitor...")

    # Start client with phone from config
    phone = config.PHONE_NUMBER if config.PHONE_NUMBER != "YOUR_PHONE_NUMBER" else None
    await client.start(phone=phone)
    logger.info("Connected to Telegram")

    # Get current user info
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username})")

    # Resolve target user
    target = await resolve_target_user()
    if not target:
        logger.warning("Running without target filter - will capture ALL messages")

    # Start periodic status checker
    asyncio.create_task(check_user_status())
    logger.info("Status checker started (checks every 30s)")

    # Start outgoing message processor
    asyncio.create_task(process_outgoing_messages())
    logger.info("Outgoing message processor started (checks every 2s)")

    # Start read marks processor
    asyncio.create_task(process_read_marks())
    logger.info("Read marks processor started (checks every 2s)")

    # Start read status sync (checks both directions)
    asyncio.create_task(sync_read_status())
    logger.info("Read status sync started (checks every 15s)")

    # Start reactions processor
    asyncio.create_task(process_reactions())
    logger.info("Reactions processor started (checks every 2s)")

    # Start deletes processor
    asyncio.create_task(process_deletes())
    logger.info("Deletes processor started (checks every 2s)")

    # Start dashboards (skip on Render where we use gunicorn separately)
    if not os.getenv("RENDER"):
        start_dashboards()

    # Print dashboard URLs
    local_ip = get_local_ip()
    port = config.DASHBOARD_PORT
    blog_port = port + 1
    hourly_port = port + 2

    logger.info("")
    logger.info("="*50)
    logger.info("  MONITOR RUNNING - Press Ctrl+C to stop")
    logger.info("="*50)
    logger.info("")
    logger.info("  Dashboard v3 (Home Assistant):")
    logger.info(f"    http://localhost:{port}")
    logger.info("")
    logger.info("  Dashboard v5 (Blog):")
    logger.info(f"    http://localhost:{blog_port}")
    logger.info("")
    logger.info("  Dashboard v6 (Hourly):")
    logger.info(f"    http://localhost:{hourly_port}")
    logger.info("")
    logger.info(f"  Remote: http://{local_ip}:{port} / {blog_port} / {hourly_port}")
    logger.info(f"  Password: {config.DASHBOARD_PASSWORD}")
    logger.info("="*50)

    # Run forever
    await client.run_until_disconnected()


if __name__ == "__main__":
    import time

    RETRY_DELAY = 300  # 5 minutes

    while True:
        try:
            client.loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
            if not os.getenv("RENDER"):
                stop_dashboards()
                logger.info("Dashboards stopped")
            break
        except Exception as e:
            logger.error(f"Monitor crashed: {e}")
            if not os.getenv("RENDER"):
                stop_dashboards()
            logger.info(f"Restarting in {RETRY_DELAY // 60} minutes...")
            time.sleep(RETRY_DELAY)
            # Recreate client for fresh connection
            if SESSION_STRING:
                client = TelegramClient(
                    StringSession(SESSION_STRING),
                    config.API_ID,
                    config.API_HASH
                )
            else:
                client = TelegramClient(
                    config.SESSION_NAME,
                    config.API_ID,
                    config.API_HASH
                )
            logger.info("Retrying...")
