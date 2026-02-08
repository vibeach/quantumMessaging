#!/usr/bin/env python3
"""
Multi-User Dashboard for Quantum Messaging.
Replaces dashboard_v6.py with full multi-user support.
"""

import os
import sys
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, g

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from multi_user import UserManager, set_coordinator_password
from multi_user.auth import login_required, get_current_user, init_auth_routes
from multi_user.monitor_manager import MonitorManager

# Configuration
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
SECRET_KEY = os.environ.get('SECRET_KEY', 'quantum-messaging-secret-key-change-me')
COORDINATOR_PASSWORD = os.environ.get('QM_COORDINATOR_PASSWORD', '')
PORT = int(os.environ.get('PORT', os.environ.get('MULTI_PORT', 5010)))

# Initialize Flask app
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=7)

# Initialize user manager
user_manager = UserManager(DATA_DIR)

# Initialize monitor manager (will be started later)
monitor_manager = None

# Set coordinator password for encryption
if COORDINATOR_PASSWORD:
    set_coordinator_password(COORDINATOR_PASSWORD)

# Initialize auth routes
init_auth_routes(app, user_manager)


def get_user_db():
    """Get database connection for current user."""
    user = get_current_user()
    if not user:
        return None

    db_path = user_manager.get_user_db_path(user['username'])
    if not os.path.exists(db_path):
        return None

    if 'user_db' not in g:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        g.user_db = conn

    return g.user_db


@app.teardown_appcontext
def close_user_db(exception):
    """Close user database connection."""
    db = g.pop('user_db', None)
    if db is not None:
        db.close()


def get_user_config():
    """Get Telegram config for current user."""
    user = get_current_user()
    if not user:
        return None
    return user_manager.get_telegram_config(user['id'])


# ==================== SETUP WIZARD ====================

@app.route('/setup')
@app.route('/setup/<int:step>')
@login_required
def setup(step=1):
    """Setup wizard for Telegram connection."""
    user = get_current_user()

    # If already set up, redirect to dashboard
    if user_manager.is_setup_complete(user['id']):
        return redirect(url_for('index'))

    return render_template('multi/setup.html', step=step)


@app.route('/setup/2', methods=['POST'])
@login_required
def setup_step2():
    """Move to step 2 (credentials entry)."""
    return render_template('multi/setup.html', step=2)


@app.route('/setup/3', methods=['POST'])
@login_required
def setup_step3():
    """Save credentials and request verification code."""
    user = get_current_user()

    api_id = request.form.get('api_id', '').strip()
    api_hash = request.form.get('api_hash', '').strip()
    phone = request.form.get('phone', '').strip()

    # Validate
    if not api_id or not api_id.isdigit():
        return render_template('multi/setup.html', step=2, error="Invalid API ID",
                             api_id=api_id, api_hash=api_hash, phone=phone)

    if not api_hash or len(api_hash) < 20:
        return render_template('multi/setup.html', step=2, error="Invalid API Hash",
                             api_id=api_id, api_hash=api_hash, phone=phone)

    if not phone or not phone.startswith('+'):
        return render_template('multi/setup.html', step=2, error="Phone must start with +",
                             api_id=api_id, api_hash=api_hash, phone=phone)

    # Save credentials
    user_manager.save_telegram_config(
        user['id'],
        api_id=api_id,
        api_hash=api_hash,
        phone=phone
    )

    # Store in session for verification step
    session['setup_api_id'] = api_id
    session['setup_api_hash'] = api_hash
    session['setup_phone'] = phone

    # Request verification code using StringSession
    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession

        string_session = StringSession()
        client = TelegramClient(string_session, int(api_id), api_hash)
        client.connect()

        if not client.is_user_authorized():
            sent_code = client.send_code_request(phone)
            # Store phone_code_hash and temp session string in Flask session
            session['setup_phone_code_hash'] = sent_code.phone_code_hash
            session['setup_temp_session'] = client.session.save()

        client.disconnect()

        return render_template('multi/setup.html', step=3)

    except Exception as e:
        logger.error(f"Error sending code: {e}")
        return render_template('multi/setup.html', step=2,
                             error=f"Could not send verification code: {e}",
                             api_id=api_id, api_hash=api_hash, phone=phone)


@app.route('/setup/4', methods=['POST'])
@login_required
def setup_step4():
    """Verify code and create session."""
    user = get_current_user()
    code = request.form.get('code', '').strip()
    twofa_password = request.form.get('twofa_password', '').strip()

    api_id = session.get('setup_api_id')
    api_hash = session.get('setup_api_hash')
    phone = session.get('setup_phone')
    phone_code_hash = session.get('setup_phone_code_hash')
    temp_session = session.get('setup_temp_session')

    if not all([api_id, api_hash, phone]):
        return redirect(url_for('setup', step=2))

    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import SessionPasswordNeededError

        # Resume from temp session
        client = TelegramClient(StringSession(temp_session), int(api_id), api_hash)
        client.connect()

        try:
            # If we have 2FA password, use it
            if twofa_password:
                client.sign_in(password=twofa_password)
            else:
                # Try to sign in with code
                client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            # 2FA is enabled, need password
            # Update temp session and store code for re-use
            session['setup_temp_session'] = client.session.save()
            session['setup_code'] = code
            client.disconnect()
            return render_template('multi/setup.html', step='3_2fa', code=code)

        # Success! Save the session string to database
        final_session_string = client.session.save()
        client.disconnect()

        # Save session string to database
        user_manager.save_session_string(user['id'], final_session_string)
        user_manager.mark_session_created(user['id'])

        return render_template('multi/setup.html', step=4)

    except Exception as e:
        logger.error(f"Error verifying code: {e}")
        # Determine which step to return to
        if twofa_password:
            return render_template('multi/setup.html', step='3_2fa',
                                 code=session.get('setup_code', code),
                                 error=f"2FA verification failed: {e}")
        return render_template('multi/setup.html', step=3,
                             error=f"Verification failed: {e}")


@app.route('/setup/complete', methods=['POST'])
@login_required
def setup_complete():
    """Complete setup with target user."""
    user = get_current_user()

    target_username = request.form.get('target_username', '').strip()
    target_name = request.form.get('target_name', '').strip()

    if not target_username:
        return render_template('multi/setup.html', step=4,
                             error="Target username is required")

    # Ensure @ prefix
    if not target_username.startswith('@'):
        target_username = '@' + target_username

    # Update config with target
    config = user_manager.get_telegram_config(user['id'], decrypt=True)
    if config:
        user_manager.save_telegram_config(
            user['id'],
            api_id=config.get('api_id', ''),
            api_hash=config.get('api_hash', ''),
            phone=config.get('phone', ''),
            target_username=target_username,
            target_display_name=target_name or target_username.replace('@', '')
        )

    # Mark setup complete
    user_manager.mark_setup_complete(user['id'])

    # Clear session setup data
    session.pop('setup_api_id', None)
    session.pop('setup_api_hash', None)
    session.pop('setup_phone', None)

    # Start monitor for this user if monitor manager is running
    if monitor_manager:
        users = user_manager.get_users_for_monitoring()
        for u in users:
            if u['id'] == user['id']:
                monitor_manager.start_user_monitor(u)
                break

    return redirect(url_for('index'))


# ==================== MAIN DASHBOARD ====================

@app.route('/')
@login_required
def index():
    """Main dashboard - message view."""
    user = get_current_user()

    # Check if setup is complete
    if not user_manager.is_setup_complete(user['id']):
        return redirect(url_for('setup'))

    db = get_user_db()
    if not db:
        return render_template('multi/setup.html', step=1,
                             error="Database not found. Please complete setup.")

    cursor = db.cursor()

    # Get messages
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    cursor.execute("""
        SELECT * FROM messages
        WHERE deleted = 0
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    messages = [dict(row) for row in cursor.fetchall()]

    # Get config for display names
    config = get_user_config()
    my_name = user['username']
    target_name = config.get('target_display_name', 'Them') if config else 'Them'

    # Mark all messages as read
    cursor.execute("""
        UPDATE messages
        SET marked_read = 1, marked_read_at = ?
        WHERE sender_name != ? AND (marked_read IS NULL OR marked_read = 0)
    """, (datetime.utcnow().isoformat(), my_name))
    db.commit()

    # Get stats
    cursor.execute("SELECT COUNT(*) as total FROM messages WHERE deleted = 0")
    total = cursor.fetchone()['total']

    return render_template('multi/messages.html',
                         messages=messages,
                         my_name=my_name,
                         target_name=target_name,
                         page=page,
                         has_more=len(messages) == per_page,
                         total=total,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


# ==================== API ENDPOINTS ====================

@app.route('/api/send-message', methods=['POST'])
@login_required
def api_send_message():
    """Queue a message to be sent."""
    user = get_current_user()
    data = request.get_json() or {}

    text = data.get('text', '').strip()
    reply_to = data.get('reply_to')

    if not text:
        return jsonify({'success': False, 'error': 'Text is required'}), 400

    db = get_user_db()
    if not db:
        return jsonify({'success': False, 'error': 'Database not found'}), 500

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO pending_messages (text, reply_to_message_id, status)
        VALUES (?, ?, 'pending')
    """, (text, reply_to))
    db.commit()

    return jsonify({'success': True, 'id': cursor.lastrowid})


@app.route('/api/mark-read', methods=['POST'])
@login_required
def api_mark_read():
    """Queue a message to be marked as read."""
    data = request.get_json() or {}
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')

    if not message_id or not chat_id:
        return jsonify({'success': False, 'error': 'message_id and chat_id required'}), 400

    db = get_user_db()
    if not db:
        return jsonify({'success': False, 'error': 'Database not found'}), 500

    cursor = db.cursor()

    # Mark in local DB
    cursor.execute("""
        UPDATE messages SET marked_read = 1, marked_read_at = ?
        WHERE message_id = ? AND chat_id = ?
    """, (datetime.utcnow().isoformat(), message_id, chat_id))

    # Queue for Telegram
    cursor.execute("""
        INSERT INTO pending_reads (message_id, chat_id, status)
        VALUES (?, ?, 'pending')
    """, (message_id, chat_id))

    db.commit()

    return jsonify({'success': True})


@app.route('/api/delete', methods=['POST'])
@login_required
def api_delete():
    """Queue a message to be deleted."""
    data = request.get_json() or {}
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')

    if not message_id or not chat_id:
        return jsonify({'success': False, 'error': 'message_id and chat_id required'}), 400

    db = get_user_db()
    if not db:
        return jsonify({'success': False, 'error': 'Database not found'}), 500

    cursor = db.cursor()

    # Queue for Telegram deletion
    cursor.execute("""
        INSERT INTO pending_deletes (message_id, chat_id, status)
        VALUES (?, ?, 'pending')
    """, (message_id, chat_id))

    db.commit()

    return jsonify({'success': True})


@app.route('/api/messages', methods=['GET'])
@login_required
def api_messages():
    """Get messages as JSON."""
    db = get_user_db()
    if not db:
        return jsonify({'success': False, 'error': 'Database not found'}), 500

    cursor = db.cursor()

    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    cursor.execute("""
        SELECT * FROM messages
        WHERE deleted = 0
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))

    messages = [dict(row) for row in cursor.fetchall()]

    return jsonify({'success': True, 'messages': messages})


# ==================== STATIC FILES ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files."""
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    return send_from_directory(static_path, filename)


# ==================== STARTUP ====================

def start_monitors():
    """Start background monitors for all users."""
    global monitor_manager

    if not COORDINATOR_PASSWORD:
        logger.warning("COORDINATOR_PASSWORD not set - monitors will not start")
        return

    monitor_manager = MonitorManager(user_manager)

    # Start in background thread after short delay
    def delayed_start():
        import time
        time.sleep(3)
        logger.info("Starting monitors for all users...")
        monitor_manager.start_all()

    thread = threading.Thread(target=delayed_start, daemon=True)
    thread.start()


if __name__ == '__main__':
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    # Check for coordinator password
    if not COORDINATOR_PASSWORD:
        print("\n" + "=" * 60)
        print("WARNING: QM_COORDINATOR_PASSWORD environment variable not set!")
        print("User credentials cannot be encrypted without it.")
        print("Set it with: export QM_COORDINATOR_PASSWORD='your-password'")
        print("=" * 60 + "\n")

    # Start monitors
    start_monitors()

    # Run Flask app
    print(f"\nStarting Quantum Messaging on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
