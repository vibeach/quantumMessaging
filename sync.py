#!/usr/bin/env python3
"""
Database Sync Tool
Bidirectional sync between local and Render databases.

Usage:
    python sync.py                    # Interactive menu
    python sync.py push               # Push local → Render
    python sync.py pull               # Pull Render → local
    python sync.py both               # Full bidirectional sync
    python sync.py status             # Show sync status
"""

import json
import os
import sys
import requests
from urllib.parse import urljoin

import config
import database

# Render URL - update this with your Render URL
RENDER_URL = os.getenv("RENDER_URL", "https://telegram-monitor-9exr.onrender.com")

# Session for authenticated requests
session = requests.Session()


def get_password():
    """Get dashboard password."""
    return os.getenv("DASHBOARD_PASSWORD", config.DASHBOARD_PASSWORD)


def login_to_render():
    """Login to Render dashboard and get session cookie."""
    login_url = urljoin(RENDER_URL, "/login")

    try:
        # First check if Render is up
        health_check = session.get(login_url, timeout=10)
        if health_check.status_code >= 500:
            print(f"✗ Render is down or deploying (HTTP {health_check.status_code})")
            print("  Wait for deployment to complete and try again.")
            return False

        # POST login with redirect follow
        response = session.post(login_url, data={"password": get_password()}, allow_redirects=True, timeout=10)

        # Check if we got redirected to messages (success) or stayed on login (failure)
        if '/messages' in response.url or '/login' not in response.url:
            print("✓ Logged in to Render")
            return True
        elif response.status_code == 200 and 'Invalid' in response.text:
            print("✗ Login failed: Invalid password")
            return False
        else:
            print(f"✗ Login failed: {response.status_code}")
            return False

    except requests.exceptions.Timeout:
        print("✗ Render timed out - service may be starting up")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"✗ Cannot connect to Render: {e}")
        return False


def get_local_stats():
    """Get local database statistics."""
    return database.get_sync_stats()


def get_render_stats():
    """Get Render database statistics."""
    url = urljoin(RENDER_URL, "/api/db/stats")
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    return None


def export_local():
    """Export local database."""
    return database.export_all_data()


def export_render():
    """Export Render database."""
    url = urljoin(RENDER_URL, "/api/db/export")
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    print(f"✗ Export from Render failed: {response.status_code}")
    return None


def import_to_local(data):
    """Import data to local database."""
    return database.import_and_merge_data(data)


def import_to_render(data):
    """Import data to Render database."""
    url = urljoin(RENDER_URL, "/api/db/import")
    response = session.post(url, json=data)
    if response.status_code == 200:
        return response.json()
    print(f"✗ Import to Render failed: {response.status_code}")
    return None


def show_status():
    """Show sync status comparison."""
    print("\n" + "="*60)
    print("  DATABASE SYNC STATUS")
    print("="*60)

    local = get_local_stats()
    print(f"\n  LOCAL DATABASE:")
    print(f"    Messages: {local['messages_count']}")
    print(f"    Latest:   {local['messages_latest']}")
    print(f"    Status:   {local['status_count']} entries")

    if not login_to_render():
        return

    render = get_render_stats()
    if render:
        print(f"\n  RENDER DATABASE:")
        print(f"    Messages: {render['messages_count']}")
        print(f"    Latest:   {render['messages_latest']}")
        print(f"    Status:   {render['status_count']} entries")

        # Show diff
        local_msgs = local['messages_count']
        render_msgs = render['messages_count']
        diff = local_msgs - render_msgs

        print(f"\n  DIFFERENCE:")
        if diff > 0:
            print(f"    Local has {diff} more messages → use 'push'")
        elif diff < 0:
            print(f"    Render has {-diff} more messages → use 'pull'")
        else:
            print(f"    Databases appear in sync")

    print("="*60 + "\n")


def push_to_render():
    """Push local database to Render."""
    print("\n" + "="*60)
    print("  PUSH: Local → Render")
    print("="*60)

    if not login_to_render():
        return False

    print("\n  Exporting local database...")
    data = export_local()
    print(f"    {len(data['messages'])} messages")
    print(f"    {len(data['online_status'])} status entries")

    print("\n  Importing to Render...")
    result = import_to_render(data)

    if result and result.get('success'):
        print(f"\n  ✓ SUCCESS:")
        print(f"    Messages added:   {result.get('messages_added', 0)}")
        print(f"    Messages updated: {result.get('messages_updated', 0)}")
        print(f"    Status added:     {result.get('status_added', 0)}")
        return True
    else:
        print(f"\n  ✗ FAILED")
        return False


def pull_from_render():
    """Pull Render database to local."""
    print("\n" + "="*60)
    print("  PULL: Render → Local")
    print("="*60)

    if not login_to_render():
        return False

    print("\n  Exporting from Render...")
    data = export_render()

    if not data:
        return False

    print(f"    {len(data['messages'])} messages")
    print(f"    {len(data['online_status'])} status entries")

    print("\n  Importing to local...")
    result = import_to_local(data)

    print(f"\n  ✓ SUCCESS:")
    print(f"    Messages added:   {result.get('messages_added', 0)}")
    print(f"    Messages updated: {result.get('messages_updated', 0)}")
    print(f"    Status added:     {result.get('status_added', 0)}")
    return True


def sync_both():
    """Full bidirectional sync."""
    print("\n" + "="*60)
    print("  BIDIRECTIONAL SYNC")
    print("="*60)

    # Pull first (get Render data)
    print("\n  Step 1: Pull from Render...")
    pull_from_render()

    # Then push (send merged data back)
    print("\n  Step 2: Push to Render...")
    push_to_render()

    print("\n  ✓ Bidirectional sync complete!")
    print("="*60 + "\n")


def interactive_menu():
    """Show interactive menu."""
    print("\n" + "="*60)
    print("  TELEGRAM DATABASE SYNC")
    print("="*60)
    print(f"  Render URL: {RENDER_URL}")
    print("="*60)
    print("\n  Commands:")
    print("    1. status  - Show sync status")
    print("    2. push    - Push local → Render")
    print("    3. pull    - Pull Render → local")
    print("    4. both    - Full bidirectional sync")
    print("    5. quit    - Exit")
    print()

    while True:
        choice = input("  Enter choice (1-5): ").strip().lower()

        if choice in ['1', 'status']:
            show_status()
        elif choice in ['2', 'push']:
            push_to_render()
        elif choice in ['3', 'pull']:
            pull_from_render()
        elif choice in ['4', 'both', 'sync']:
            sync_both()
        elif choice in ['5', 'quit', 'q', 'exit']:
            print("\n  Goodbye!\n")
            break
        else:
            print("  Invalid choice. Try again.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == 'push':
            push_to_render()
        elif cmd == 'pull':
            pull_from_render()
        elif cmd == 'both' or cmd == 'sync':
            sync_both()
        elif cmd == 'status':
            show_status()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python sync.py [push|pull|both|status]")
    else:
        interactive_menu()
