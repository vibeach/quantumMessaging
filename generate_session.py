#!/usr/bin/env python3
"""
Generate a Telegram session string for cloud deployment.
Run this locally once, then use the output as SESSION_STRING env var.
"""

from telethon import TelegramClient
from telethon.sessions import StringSession
import config

async def main():
    print("Generating session string for cloud deployment...")
    print()

    # Create client with StringSession
    client = TelegramClient(
        StringSession(),
        config.API_ID,
        config.API_HASH
    )

    await client.start(phone=config.PHONE_NUMBER)

    # Get the session string
    session_string = client.session.save()

    print()
    print("=" * 60)
    print("SESSION STRING (copy this entire line):")
    print("=" * 60)
    print()
    print(session_string)
    print()
    print("=" * 60)
    print()
    print("Add this as SESSION_STRING environment variable on Render")
    print("=" * 60)

    await client.disconnect()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
