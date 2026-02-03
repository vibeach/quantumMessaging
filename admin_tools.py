#!/usr/bin/env python3
"""
Coordinator Admin Tools for Quantum Messaging.
Password-protected CLI to view all users and their credentials.
"""

import os
import sys
import getpass
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from multi_user.user_manager import UserManager
from multi_user.encryption import hash_coordinator_password, verify_coordinator_password

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'coordinator.json')


def load_config():
    """Load coordinator config."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save coordinator config."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def setup_coordinator_password():
    """Set up coordinator password for first time."""
    print("\n=== First Time Setup ===")
    print("You need to set a coordinator password.")
    print("This password will be required to:")
    print("  - Run this admin script")
    print("  - Encrypt/decrypt user credentials")
    print()

    while True:
        password = getpass.getpass("Enter new coordinator password: ")
        if len(password) < 6:
            print("Password must be at least 6 characters.")
            continue

        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match. Try again.")
            continue

        break

    config = load_config()
    config['password_hash'] = hash_coordinator_password(password)
    save_config(config)

    print("\nCoordinator password set successfully!")
    return password


def authenticate():
    """Authenticate coordinator."""
    config = load_config()

    if 'password_hash' not in config:
        return setup_coordinator_password()

    print("\n=== Quantum Messaging Admin ===")
    password = getpass.getpass("Enter coordinator password: ")

    if not verify_coordinator_password(password, config['password_hash']):
        print("Invalid password.")
        sys.exit(1)

    return password


def format_time_ago(timestamp_str):
    """Format timestamp as time ago."""
    if not timestamp_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now()
        diff = now - dt.replace(tzinfo=None)
        seconds = diff.total_seconds()

        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        else:
            return f"{int(seconds // 86400)}d ago"
    except:
        return timestamp_str


def cmd_list(user_manager):
    """List all users."""
    users = user_manager.get_all_users()

    if not users:
        print("\nNo users found.")
        return

    print(f"\nUsers ({len(users)} total):")
    print("-" * 60)

    for user in users:
        status = "Complete" if user.get('setup_complete') else "Pending"
        monitor = "Running" if user.get('is_running') else "Stopped"
        last_login = format_time_ago(user.get('last_login'))

        print(f"  {user['username']:<15} Setup: {status:<10} Monitor: {monitor:<8} Last login: {last_login}")


def cmd_show(user_manager, coordinator_password, username=None):
    """Show user details with credentials."""
    if username:
        users = [u for u in user_manager.get_all_credentials(coordinator_password)
                 if u['username'] == username.lower()]
        if not users:
            print(f"\nUser '{username}' not found.")
            return
    else:
        users = user_manager.get_all_credentials(coordinator_password)

    if not users:
        print("\nNo users found.")
        return

    for user in users:
        print(f"\n{'=' * 50}")
        print(f"User: {user['username']}")
        print(f"{'=' * 50}")

        print(f"\nCreated: {user.get('created_at', 'Unknown')}")
        print(f"Last Login: {user.get('last_login') or 'Never'}")

        print("\nLogin Credentials:")
        if user.get('decrypt_error'):
            print(f"  [Decrypt Error: {user['decrypt_error']}]")
        else:
            print(f"  Password: {user.get('password', '[not set]')}")

        print("\nTelegram Config:")
        if user.get('setup_complete'):
            print(f"  Phone: {user.get('phone', '[not set]')}")
            print(f"  API ID: {user.get('api_id', '[not set]')}")
            print(f"  API Hash: {user.get('api_hash', '[not set]')}")
            print(f"  Target: {user.get('target_username', '[not set]')} ({user.get('target_display_name', '')})")
        else:
            print("  [Setup not complete]")

        print("\nMonitor Status:")
        status = "Running" if user.get('is_running') else "Stopped"
        heartbeat = format_time_ago(user.get('last_heartbeat'))
        print(f"  Status: {status}")
        print(f"  Last heartbeat: {heartbeat}")
        print(f"  Messages today: {user.get('messages_today', 0)}")


def cmd_status(user_manager):
    """Show monitor status for all users."""
    users = user_manager.get_all_users()

    print("\nMonitor Status:")
    print("-" * 60)

    for user in users:
        status = "Running" if user.get('is_running') else "Stopped"
        heartbeat = format_time_ago(user.get('last_heartbeat'))
        setup = "Yes" if user.get('setup_complete') else "No"

        print(f"  {user['username']:<15} [{status:<8}] Heartbeat: {heartbeat:<10} Setup: {setup}")


def cmd_help():
    """Show help."""
    print("""
Available commands:
  list              - List all users
  show              - Show all users with credentials
  show <username>   - Show specific user with credentials
  status            - Show monitor status for all users
  help              - Show this help
  quit / exit       - Exit the program
""")


def main():
    """Main entry point."""
    coordinator_password = authenticate()

    # Initialize user manager
    user_manager = UserManager(DATA_DIR)

    # Set coordinator password for encryption operations
    from multi_user.encryption import set_coordinator_password
    set_coordinator_password(coordinator_password)

    print("\nAuthenticated successfully!")
    print("Type 'help' for available commands.\n")

    while True:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            parts = cmd.split()
            command = parts[0].lower()
            args = parts[1:]

            if command in ('quit', 'exit', 'q'):
                print("Goodbye!")
                break
            elif command == 'list':
                cmd_list(user_manager)
            elif command == 'show':
                username = args[0] if args else None
                cmd_show(user_manager, coordinator_password, username)
            elif command == 'show-all':
                cmd_show(user_manager, coordinator_password)
            elif command == 'status':
                cmd_status(user_manager)
            elif command == 'help':
                cmd_help()
            else:
                print(f"Unknown command: {command}")
                cmd_help()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == '__main__':
    main()
