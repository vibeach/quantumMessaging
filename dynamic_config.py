#!/usr/bin/env python3
"""
Dynamic Configuration Module
Stores editable config on persistent disk (/data on Render).
Allows runtime updates without redeploy.
"""

import os
import json
from datetime import datetime

import config

# Config files stored on persistent disk
CONFIG_DIR = os.path.join(config.DATA_DIR, 'dynamic_config')
PROMPTS_FILE = os.path.join(CONFIG_DIR, 'prompts.json')
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.json')

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)


# ==================== DEFAULT VALUES ====================

DEFAULT_INCEPT_SYSTEM_PROMPT = """You are an expert Python/Flask developer with the ability to read and modify files.
You are working on a Telegram monitoring dashboard project.

Project structure:
- dashboard_v6.py: Main Flask app with routes
- database.py: SQLite database functions
- config.py: Configuration settings
- templates/: Jinja2 HTML templates (base_v6.html, messages_v6.html, etc.)
- monitor.py: Telegram message monitoring
- ai_assistant.py: AI features

IMPORTANT: You have tools to ACTUALLY make changes to files. Use them!
1. First, use read_file to examine relevant files
2. Use edit_file for small targeted changes (preferred) or write_file for new files
3. Use log_progress to communicate what you're doing
4. Make all necessary changes to fully implement the request

Always read a file before editing it to understand its current state.

CRITICAL GIT RULES:
- DO NOT run any git commands (git add, git commit, git push, etc.)
- DO NOT use subprocess to run git commands
- The system will handle git operations separately based on user preferences
- Your job is ONLY to make file changes, not to manage version control"""

DEFAULT_PROMPTS = {
    'incept_system': {
        'content': DEFAULT_INCEPT_SYSTEM_PROMPT,
        'description': 'System prompt for Incept API processor',
        'updated_at': None
    }
}

DEFAULT_SETTINGS = {
    # Incept Settings
    'incept_max_iterations': 50,
    'incept_max_tokens': 4096,
    'incept_auto_push': True,
    'incept_notify_on_complete': False,

    # Security & Privacy
    'fake_page_timeout_seconds': 180,  # Time before real page switches to fake (3 minutes default)
    'password_timeout_seconds': 900,   # Time before password required again (15 minutes default)
    'require_medi_password': True,     # Whether to require separate password for medi page
    'session_timeout_minutes': 15,     # Overall session timeout

    # UI/UX Settings
    'enable_dark_mode': True,          # Enable dark mode toggle
    'default_theme': 'light',          # Default theme (light/dark)
    'show_tutorial_on_timeout': True,  # Show tutorial page on inactivity timeout
    'enable_smart_widget_decoy': True, # Enable smart home widget decoy feature

    # Dashboard Behavior
    'auto_refresh_enabled': False,     # Auto-refresh pages
    'auto_refresh_interval': 30,       # Seconds between auto-refreshes
    'show_notification_count': True,   # Show unread count in tab title
    'messages_per_page': 100,          # Messages per page
    'locked_history_message_limit': 10,  # Messages visible when history is locked
    'locked_history_media_limit': 5,     # Media items visible when history is locked

    # Notifications
    'notifications_enabled': True,     # Enable push notifications

    # Media Settings
    'auto_generate_thumbnails': True,  # Auto-generate thumbnails
    'default_snapshot_count': 6,       # Video snapshots to generate
    'compress_images': False,          # Compress uploaded images

    # Message Send Settings
    'refresh_after_send_delay': 2,     # Seconds to wait before refreshing page after sending message (default 2)

    'updated_at': None
}


# ==================== FILE I/O ====================

def _read_json(filepath, default):
    """Read JSON file, return default if not exists or invalid."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Error reading {filepath}: {e}")
    return default.copy()


def _write_json(filepath, data):
    """Write data to JSON file."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except IOError as e:
        print(f"Error writing {filepath}: {e}")
        return False


# ==================== PROMPTS ====================

def get_prompts():
    """Get all prompts from disk (with defaults for missing)."""
    prompts = _read_json(PROMPTS_FILE, DEFAULT_PROMPTS)
    # Merge with defaults to ensure all keys exist
    for key, value in DEFAULT_PROMPTS.items():
        if key not in prompts:
            prompts[key] = value
    return prompts


def get_prompt(name, default=None):
    """Get a specific prompt by name."""
    prompts = get_prompts()
    prompt_data = prompts.get(name)
    if prompt_data:
        return prompt_data.get('content', default)
    return default


def set_prompt(name, content, description=None):
    """Set/update a prompt."""
    prompts = get_prompts()
    prompts[name] = {
        'content': content,
        'description': description or prompts.get(name, {}).get('description', ''),
        'updated_at': datetime.now().isoformat()
    }
    return _write_json(PROMPTS_FILE, prompts)


def delete_prompt(name):
    """Delete a prompt (can't delete defaults, just resets them)."""
    prompts = get_prompts()
    if name in DEFAULT_PROMPTS:
        # Reset to default
        prompts[name] = DEFAULT_PROMPTS[name].copy()
        prompts[name]['updated_at'] = datetime.now().isoformat()
    elif name in prompts:
        del prompts[name]
    return _write_json(PROMPTS_FILE, prompts)


# ==================== SETTINGS ====================

def get_settings():
    """Get all settings from disk (with defaults for missing)."""
    settings = _read_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    # Merge with defaults
    for key, value in DEFAULT_SETTINGS.items():
        if key not in settings:
            settings[key] = value
    return settings


def get_setting(name, default=None):
    """Get a specific setting by name."""
    settings = get_settings()
    return settings.get(name, default)


def set_setting(name, value):
    """Set/update a setting."""
    settings = get_settings()
    settings[name] = value
    settings['updated_at'] = datetime.now().isoformat()
    return _write_json(SETTINGS_FILE, settings)


def set_settings(new_settings):
    """Update multiple settings at once."""
    settings = get_settings()
    settings.update(new_settings)
    settings['updated_at'] = datetime.now().isoformat()
    return _write_json(SETTINGS_FILE, settings)


# ==================== CONVENIENCE ====================

def get_incept_system_prompt():
    """Get the Incept system prompt (most commonly needed)."""
    return get_prompt('incept_system', DEFAULT_INCEPT_SYSTEM_PROMPT)


def set_incept_system_prompt(content):
    """Set the Incept system prompt."""
    return set_prompt('incept_system', content, 'System prompt for Incept API processor')


def get_all_config():
    """Get all dynamic config for display/export."""
    return {
        'prompts': get_prompts(),
        'settings': get_settings(),
        'config_dir': CONFIG_DIR,
        'prompts_file': PROMPTS_FILE,
        'settings_file': SETTINGS_FILE
    }


def reset_to_defaults():
    """Reset all config to defaults."""
    _write_json(PROMPTS_FILE, DEFAULT_PROMPTS)
    _write_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    return True
