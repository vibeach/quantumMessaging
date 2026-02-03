#!/usr/bin/env python3
"""
Web Dashboard for Telegram Monitor
View messages and online status history from any device.
"""

from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

import config
import database

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


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
        error = 'Invalid password'
    return render_template('login.html', error=error)


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


@app.route('/messages')
@login_required
def messages():
    """View message history."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()

    return render_template('messages.html',
                         messages=msgs,
                         stats=stats,
                         page=page,
                         has_more=len(msgs) == per_page)


@app.route('/status')
@login_required
def status():
    """View online/offline history."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    history = database.get_online_history(limit=per_page, offset=offset)

    return render_template('status.html',
                         history=history,
                         page=page,
                         has_more=len(history) == per_page)


@app.route('/api/messages')
@login_required
def api_messages():
    """JSON API for messages."""
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    msgs = database.get_messages(limit=limit, offset=offset)
    return jsonify(msgs)


@app.route('/api/status')
@login_required
def api_status():
    """JSON API for status history."""
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    history = database.get_online_history(limit=limit, offset=offset)
    return jsonify(history)


@app.route('/api/stats')
@login_required
def api_stats():
    """JSON API for statistics."""
    return jsonify(database.get_message_stats())


if __name__ == '__main__':
    print(f"Dashboard running at http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    print(f"Password: {config.DASHBOARD_PASSWORD}")
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=True
    )
