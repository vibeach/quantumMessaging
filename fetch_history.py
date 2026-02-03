#!/usr/bin/env python3
"""
Fetch Message History from Telegram
One-time script to import historical messages into the database.
Run this before or alongside the monitor to backfill history.
"""

import asyncio
import json
import os
import sys
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    ReactionEmoji,
    ReactionCustomEmoji,
)

import config
import database


# How many messages to fetch (None = all available)
MESSAGE_LIMIT = None  # Set to e.g. 5000 for testing

# Whether to download media files
DOWNLOAD_MEDIA = False  # Set True if you want media, but slower


def get_media_type(message):
    """Determine media type from message."""
    if message.media is None:
        return None
    if isinstance(message.media, MessageMediaPhoto):
        return "photo"
    if isinstance(message.media, MessageMediaDocument):
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
    except Exception:
        return None

    return json.dumps(reactions) if reactions else None


async def download_media(message, client):
    """Download media from message and return the file path."""
    if not message.media or not DOWNLOAD_MEDIA:
        return None

    try:
        timestamp = message.date.strftime("%Y%m%d_%H%M%S") if message.date else "unknown"

        if isinstance(message.media, MessageMediaPhoto):
            ext = "jpg"
            prefix = "photo"
        elif isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            mime = getattr(doc, 'mime_type', '')
            if 'video' in mime:
                ext = "mp4"
                prefix = "video"
            elif 'audio' in mime or 'voice' in mime or 'ogg' in mime:
                ext = "ogg"
                prefix = "voice"
            elif 'webp' in mime or message.sticker:
                ext = "webp"
                prefix = "sticker"
            else:
                ext = mime.split('/')[-1] if '/' in mime else "bin"
                prefix = "file"
        else:
            ext = "bin"
            prefix = "media"

        filename = f"{prefix}_{message.id}_{timestamp}.{ext}"
        filepath = os.path.join(config.MEDIA_PATH, filename)

        await message.download_media(file=filepath)
        return filename

    except Exception as e:
        print(f"  Failed to download media: {e}")
        return None


async def fetch_history():
    """Fetches conversation history."""
    print("=" * 50)
    print("  Telegram History Fetcher")
    print("=" * 50)

    # Create client
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

    phone = config.PHONE_NUMBER if config.PHONE_NUMBER != "YOUR_PHONE_NUMBER" else None
    await client.start(phone=phone)
    print("Connected to Telegram")

    me = await client.get_me()
    my_name = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip()
    print(f"Logged in as: {me.first_name} (@{me.username})")

    # Resolve target
    target = config.TARGET_USER
    try:
        if target.isdigit():
            entity = await client.get_entity(int(target))
        else:
            entity = await client.get_entity(target)
        target_name = f"{getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')}".strip()
        print(f"Target user: {target_name} (ID: {entity.id})")
    except Exception as e:
        print(f"Could not resolve target user '{target}': {e}")
        await client.disconnect()
        return

    # Count existing messages
    existing = database.get_sync_stats()
    print(f"Existing messages in database: {existing['messages_count']}")

    # Fetch history
    print("")
    print(f"Fetching message history (limit: {MESSAGE_LIMIT or 'all'})...")
    print("This may take a while for large histories...")
    print("")

    count = 0
    new_count = 0
    skipped = 0

    async for message in client.iter_messages(entity, limit=MESSAGE_LIMIT):
        count += 1

        # Get sender info
        sender = await message.get_sender()
        if sender:
            sender_name = f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip()
            sender_id = sender.id
        else:
            sender_name = "Unknown"
            sender_id = None

        # Check if message already exists
        with database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM messages WHERE message_id = ? AND chat_id = ?",
                (message.id, entity.id)
            )
            if cursor.fetchone():
                skipped += 1
                if count % 100 == 0:
                    print(f"  Processed {count} messages ({new_count} new, {skipped} existing)...")
                continue

        # Get message content
        media_type = get_media_type(message)
        media_path = await download_media(message, client) if DOWNLOAD_MEDIA else None
        reactions = get_reactions(message)
        text = message.text or message.message or ("[Media]" if media_type else "")

        # Save to database
        database.save_message(
            message_id=message.id,
            chat_id=entity.id,
            sender_id=sender_id,
            sender_name=sender_name or "Unknown",
            text=text,
            media_type=media_type,
            media_path=media_path,
            timestamp=message.date,
            reactions=reactions
        )
        new_count += 1

        if count % 100 == 0:
            print(f"  Processed {count} messages ({new_count} new, {skipped} existing)...")

    print("")
    print("=" * 50)
    print(f"  Done! Processed {count} messages")
    print(f"  New messages added: {new_count}")
    print(f"  Already existed: {skipped}")
    print("=" * 50)

    # Final stats
    final = database.get_sync_stats()
    print(f"Total messages in database: {final['messages_count']}")
    if final['time_range']['oldest']:
        print(f"Date range: {final['time_range']['oldest'][:10]} to {final['time_range']['newest'][:10]}")

    await client.disconnect()


if __name__ == "__main__":
    print("")
    print("This script will fetch your message history with the target user.")
    print("It uses the same session as the monitor, so make sure monitor is stopped.")
    print("")

    if len(sys.argv) > 1 and sys.argv[1] == "--yes":
        pass
    else:
        response = input("Continue? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    asyncio.run(fetch_history())
