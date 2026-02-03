#!/usr/bin/env python3
"""
Web Dashboard v6 for Telegram Monitor
Hourly grouped messages, most recent first.
"""

import os
import threading
import time
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory

import config
import database
import dynamic_config

# Embedded processor state
_embedded_processor_running = False
_embedded_processor_thread = None
_processor_lock = threading.Lock()

logger = logging.getLogger(__name__)


def time_ago(timestamp_str):
    """Convert timestamp string to human-readable 'time ago' format."""
    if not timestamp_str:
        return '--'
    try:
        # Parse the timestamp
        if 'T' in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(timestamp_str[:19], '%Y-%m-%d %H:%M:%S')

        now = datetime.now()
        diff = now - dt

        seconds = diff.total_seconds()
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h{mins}m" if mins > 0 else f"{hours}h"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d{hours}h" if hours > 0 else f"{days}d"
    except:
        return '--'


def time_in_minutes(timestamp_str):
    """Convert timestamp string to total minutes ago."""
    if not timestamp_str:
        return None
    try:
        # Parse the timestamp
        if 'T' in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(timestamp_str[:19], '%Y-%m-%d %H:%M:%S')

        now = datetime.now()
        diff = now - dt
        return int(diff.total_seconds() / 60)
    except:
        return None


app = Flask(__name__)
app.secret_key = config.SECRET_KEY + "_v6"
app.permanent_session_lifetime = timedelta(minutes=15)

# Ensure media folder exists
os.makedirs(config.MEDIA_PATH, exist_ok=True)

# Your display name
MY_NAME = getattr(config, 'MY_NAME', None) or "Me"

# v6 dashboard runs on port + 2
V6_PORT = config.DASHBOARD_PORT + 2


@app.template_filter('format_duration')
def format_duration(seconds):
    """Format duration in seconds to MM:SS or HH:MM:SS format."""
    if not seconds:
        return ''
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def api_login_required(f):
    """Decorator for API endpoints - returns JSON error instead of redirect."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'Not authenticated. Please refresh the page and login.'}), 401
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_global_unread_stats():
    """Inject global unread message counts into all templates."""
    if session.get('logged_in'):
        try:
            unseen_stats = database.get_unseen_stats(MY_NAME)
            return {
                'global_her_unread': unseen_stats.get('her_unseen', 0),
                'global_my_unread': unseen_stats.get('my_unseen', 0)
            }
        except Exception:
            return {'global_her_unread': 0, 'global_my_unread': 0}
    return {'global_her_unread': 0, 'global_my_unread': 0}


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == config.DASHBOARD_PASSWORD:
            session.permanent = True  # Enable 15-minute timeout
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = 'Invalid credentials'
    return render_template('login_v6.html', error=error)


@app.route('/logout')
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@app.route('/home')
@login_required
def index():
    """Home page with overview of all dashboard sections."""
    # Message stats
    stats = database.get_message_stats()

    # Unseen stats for quick bar
    unseen_stats = database.get_unseen_stats(MY_NAME)
    # Add time ago strings
    unseen_stats['my_last_msg_ago'] = time_ago(unseen_stats.get('my_last_msg_time'))
    unseen_stats['her_last_msg_ago'] = time_ago(unseen_stats.get('her_last_msg_time'))
    # Add time ago for unseen messages
    unseen_stats['my_oldest_unseen_ago'] = time_ago(unseen_stats.get('my_oldest_unseen_time'))
    unseen_stats['her_oldest_unseen_ago'] = time_ago(unseen_stats.get('her_oldest_unseen_time'))
    # Add minutes for homepage display
    unseen_stats['my_last_msg_minutes'] = time_in_minutes(unseen_stats.get('my_last_msg_time'))
    unseen_stats['her_last_msg_minutes'] = time_in_minutes(unseen_stats.get('her_last_msg_time'))
    unseen_stats['my_oldest_unseen_minutes'] = time_in_minutes(unseen_stats.get('my_oldest_unseen_time'))
    unseen_stats['her_oldest_unseen_minutes'] = time_in_minutes(unseen_stats.get('her_oldest_unseen_time'))

    # Get latest message for preview
    latest_messages = database.get_messages(limit=1)
    latest_message = latest_messages[0] if latest_messages else None

    # Current online status
    current_status = database.get_latest_status(user_id=None)

    # Media stats
    media_stats = database.get_media_stats()

    # All-time stats
    all_time_stats = database.get_all_time_stats(MY_NAME)

    # Incept stats
    incept_requests = database.get_claude_requests(limit=10)
    incept_stats = {
        'pending': sum(1 for r in incept_requests if r.get('status') == 'pending'),
        'processing': sum(1 for r in incept_requests if r.get('status') == 'processing'),
        'completed': sum(1 for r in incept_requests if r.get('status') == 'completed'),
    }

    # Incept+ stats
    try:
        incept_suggestions = database.get_incept_suggestions(status='pending', limit=100)
        incept_plus_stats = {'pending': len(incept_suggestions) if incept_suggestions else 0}
    except:
        incept_plus_stats = {'pending': 0}

    # AI stats
    try:
        pending_suggestions = database.get_messages_without_suggestions(limit=100)
        ai_stats = {'pending_suggestions': len(pending_suggestions) if pending_suggestions else 0}
    except:
        ai_stats = {'pending_suggestions': 0}

    # Lab connection status
    try:
        import control_room
        lab_connected = control_room.check_connection()
    except:
        lab_connected = False

    # Render status (simplified)
    render_status = None
    if config.RENDER_API_KEY and config.RENDER_SERVICE_ID:
        render_status = {'status': 'Configured', 'last_deploy': 'Check Render page'}

    # Log stats
    try:
        log_stats = database.get_system_log_stats()
    except:
        log_stats = {'total': 0, 'errors': 0, 'warnings': 0}

    # Processor status
    processor_running = is_processor_running()

    return render_template('home_v6.html',
                         stats=stats,
                         unseen_stats=unseen_stats,
                         latest_message=latest_message,
                         current_status=current_status,
                         media_stats=media_stats,
                         all_time_stats=all_time_stats,
                         incept_stats=incept_stats,
                         incept_plus_stats=incept_plus_stats,
                         ai_stats=ai_stats,
                         lab_connected=lab_connected,
                         render_status=render_status,
                         log_stats=log_stats,
                         processor_running=processor_running,
                         recent_incept_requests=incept_requests,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/messages')
@app.route('/v6/messages')
@login_required
def messages():
    """View message history grouped by hour (v6 style)."""
    page = request.args.get('page', 1, type=int)

    # Check if history is unlocked (password 0319 entered)
    history_unlocked = session.get('history_unlocked', False)
    unlock_time = session.get('history_unlock_time', 0)

    # Check if 10 minutes have passed (600 seconds)
    import time
    if history_unlocked and (time.time() - unlock_time > 600):
        session['history_unlocked'] = False
        history_unlocked = False

    # Get configurable limits from settings
    locked_limit = dynamic_config.get_setting('locked_history_message_limit', 10)
    unlocked_limit = dynamic_config.get_setting('messages_per_page', 100)

    # Limit to configured number of messages if locked, otherwise use messages_per_page setting
    per_page = unlocked_limit if history_unlocked else locked_limit
    offset = (page - 1) * per_page

    # Get messages (already sorted by timestamp DESC)
    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()

    # Get recent lab entries from control_room
    lab_entries = database.get_system_logs(limit=50, category='control_room')

    # Convert lab entries to message-like format and add lab_entry flag
    for entry in lab_entries:
        entry['lab_entry'] = True
        # Include all values from details for full lab entry display - no truncation
        details_text = ''
        if entry.get('details'):
            try:
                import ast
                details_data = ast.literal_eval(entry['details'])
                if isinstance(details_data, dict):
                    # Format all key-value pairs - include everything
                    parts = []
                    for k, v in details_data.items():
                        if v is not None and v != '':
                            parts.append(f"{k}: {v}")
                    details_text = ' | '.join(parts)
                else:
                    # Not a dict, use the full string representation
                    details_text = str(details_data)
            except:
                # If not parseable as Python literal, use the raw details string
                details_text = entry.get('details', '')

        # Also include the message field if present and different from details
        message_text = entry.get('message', '')

        action = entry.get('action', 'Unknown')
        text_parts = [f"[LAB] {action}"]
        if message_text and message_text != f'Received {action} from Control Room':
            text_parts.append(message_text)
        if details_text:
            text_parts.append(details_text)
        entry['text'] = ' - '.join(text_parts)
        entry['sender_name'] = 'Lab'

    # Merge messages and lab entries
    all_items = msgs + lab_entries

    # Sort by timestamp
    all_items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Group by hour, then reverse within each group
    # So hours are in DESC order (recent first) but messages within each hour are ASC (chronological)
    from collections import OrderedDict
    hours = OrderedDict()
    for msg in all_items:
        ts = msg.get('timestamp', '')
        if ts and len(ts) > 13:
            hour_key = ts[:10] + ' ' + ts[11:13] + ':00'
        else:
            hour_key = 'Unknown'
        if hour_key not in hours:
            hours[hour_key] = []
        hours[hour_key].append(msg)

    # Reverse messages within each hour (so earlier messages first)
    for hour_key in hours:
        hours[hour_key] = list(reversed(hours[hour_key]))

    # Flatten back: hours stay in DESC order, but messages within each hour are now ASC
    ordered_msgs = []
    for hour_key, hour_msgs in hours.items():
        ordered_msgs.extend(hour_msgs)

    # Get refresh delay setting
    refresh_delay = dynamic_config.get_setting('refresh_after_send_delay', 2)

    return render_template('messages_v6.html',
                         messages=ordered_msgs,
                         stats=stats,
                         page=page,
                         has_more=len(msgs) == per_page,
                         my_name=MY_NAME,
                         refresh_delay=refresh_delay,
                         history_unlocked=history_unlocked,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/v3/messages')
@login_required
def messages_v3():
    """View message history (v3 Home Assistant style)."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()

    return render_template('messages_v3.html',
                         messages=msgs,
                         stats=stats,
                         page=page,
                         has_more=len(msgs) == per_page,
                         my_name=MY_NAME)


@app.route('/v5/messages')
@login_required
def messages_v5():
    """View message history (v5 Blog style)."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()

    return render_template('messages_v5.html',
                         messages=msgs,
                         stats=stats,
                         page=page,
                         has_more=len(msgs) == per_page,
                         my_name=MY_NAME)


@app.route('/state')
@app.route('/v6/state')
@login_required
def state():
    """View online/offline history with ignore detection."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    history = database.get_online_history(limit=per_page, offset=offset)
    sessions = database.get_online_sessions(days=7)
    status_summary = database.get_status_summary(days=7)

    # New: ignore detection and activity timeline
    ignore_sessions = database.get_unseen_during_sessions(MY_NAME, days=14)
    activity_timeline = database.get_activity_timeline(MY_NAME, days=3)
    status_inferred = database.get_status_with_inferred(MY_NAME, days=7)

    return render_template('state_v6.html',
                         history=history,
                         sessions=sessions,
                         status_summary=status_summary,
                         ignore_sessions=ignore_sessions,
                         activity_timeline=activity_timeline,
                         status_inferred=status_inferred,
                         page=page,
                         has_more=len(history) == per_page,
                         my_name=MY_NAME,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/status')
@app.route('/v6/status')
@login_required
def status():
    """Backward compatibility redirect from /status to /state."""
    return redirect(url_for('state', **request.args))


@app.route('/v3/status')
@login_required
def status_v3():
    """View online/offline history (v3 style)."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    history = database.get_online_history(limit=per_page, offset=offset)

    return render_template('status_v3.html',
                         history=history,
                         page=page,
                         has_more=len(history) == per_page)


@app.route('/v5/status')
@login_required
def status_v5():
    """View online/offline history (v5 style)."""
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page

    history = database.get_online_history(limit=per_page, offset=offset)

    return render_template('status_v5.html',
                         history=history,
                         page=page,
                         has_more=len(history) == per_page)


@app.route('/media/<path:filename>')
@login_required
def serve_media(filename):
    """Serve media files."""
    return send_from_directory(config.MEDIA_PATH, filename)


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files (icons, etc)."""
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    return send_from_directory(static_path, filename)


@app.route('/gallery')
@app.route('/v3/gallery')
@app.route('/v5/gallery')
@login_required
def media_gallery():
    """View media gallery."""
    # Get list of media files
    media_files = []
    if os.path.exists(config.MEDIA_PATH):
        for f in os.listdir(config.MEDIA_PATH):
            filepath = os.path.join(config.MEDIA_PATH, f)
            if os.path.isfile(filepath):
                media_files.append({
                    'filename': f,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M')
                })
    media_files.sort(key=lambda x: x['modified'], reverse=True)

    # Choose template based on route
    if request.path.startswith('/v3'):
        return render_template('media_v3.html', media_files=media_files)
    elif request.path.startswith('/v5'):
        return render_template('media_v5.html', media_files=media_files)
    return render_template('media_v5.html', media_files=media_files)


@app.route('/media')
@app.route('/v6/media')
@login_required
def media():
    """Redirect to medi page for backward compatibility."""
    return redirect(url_for('medi', **request.args))


@app.route('/files')
@app.route('/v6/files')
@login_required
def files():
    """Backward compatibility redirect from old /files route to /media."""
    return redirect(url_for('media', **request.args))


@app.route('/vide')
@app.route('/v6/vide')
@login_required
def vide():
    """Redirect to medi for backward compatibility."""
    return redirect(url_for('medi', **request.args))


def medi_login_required(f):
    """Decorator to require medi-specific login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))

        # Check if medi password is required based on settings
        settings = dynamic_config.get_settings()
        require_password = settings.get('require_medi_password', True)

        if require_password and not session.get('medi_unlocked'):
            return redirect(url_for('medi_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/medi/login', methods=['GET', 'POST'])
@login_required
def medi_login():
    """Medi page login (additional password check)."""
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == config.DASHBOARD_PASSWORD:
            session['medi_unlocked'] = True
            return redirect(url_for('medi'))
        error = 'Invalid password'
    return render_template('medi_login_v6.html', error=error)


@app.route('/medi')
@app.route('/v6/medi')
@medi_login_required
def medi():
    """View media with snapshot rows (v6 style)."""
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('type', '')
    snapshot_count = request.args.get('snaps', 20, type=int)

    # Check if history is unlocked (password 0319 entered)
    history_unlocked = session.get('history_unlocked', False)
    unlock_time = session.get('history_unlock_time', 0)

    # Check if 10 minutes have passed (600 seconds)
    import time
    if history_unlocked and (time.time() - unlock_time > 600):
        session['history_unlocked'] = False
        history_unlocked = False

    # Get configurable limits from settings
    locked_limit = dynamic_config.get_setting('locked_history_media_limit', 5)

    # Limit to configured number of media items if locked, 30 if unlocked
    per_page = 30 if history_unlocked else locked_limit
    offset = (page - 1) * per_page

    # Validate snapshot count
    if snapshot_count not in [3, 6, 9, 12, 20, 30, 40]:
        snapshot_count = 20

    # Get only video types
    if filter_type:
        media_type = filter_type
    else:
        media_type = None

    # Get all media messages (video, video_note, circle, photo, audio, voice)
    with database.get_connection() as conn:
        cursor = conn.cursor()
        if media_type:
            # Special handling for audio filter to include both audio and voice
            if media_type == 'audio':
                cursor.execute("""
                    SELECT * FROM messages
                    WHERE media_path IS NOT NULL AND media_path != ''
                    AND media_type IN ('audio', 'voice')
                    ORDER BY timestamp DESC LIMIT ? OFFSET ?
                """, (per_page, offset))
            else:
                cursor.execute("""
                    SELECT * FROM messages
                    WHERE media_path IS NOT NULL AND media_path != ''
                    AND media_type = ?
                    ORDER BY timestamp DESC LIMIT ? OFFSET ?
                """, (media_type, per_page, offset))
        else:
            cursor.execute("""
                SELECT * FROM messages
                WHERE media_path IS NOT NULL AND media_path != ''
                AND media_type IN ('video', 'video_note', 'circle', 'photo', 'audio', 'voice')
                ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """, (per_page, offset))
        media_list = [dict(row) for row in cursor.fetchall()]

    # Get stats for all media types
    stats = {}
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT media_type, COUNT(*) as count
            FROM messages
            WHERE media_path IS NOT NULL AND media_path != ''
            AND media_type IN ('video', 'video_note', 'circle', 'photo', 'audio', 'voice')
            GROUP BY media_type
        """)
        stats = {row['media_type']: row['count'] for row in cursor.fetchall()}

    # Count videos without snapshots
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count FROM messages
            WHERE media_path IS NOT NULL AND media_path != ''
            AND media_type IN ('video', 'video_note', 'circle')
            AND (media_snapshots IS NULL OR media_snapshots = '')
        """)
        pending_snapshots = cursor.fetchone()['count']

    return render_template('medi_v6.html',
                         media=media_list,
                         stats=stats,
                         page=page,
                         has_more=len(media_list) == per_page,
                         filter_type=filter_type,
                         snapshot_count=snapshot_count,
                         pending_snapshots=pending_snapshots,
                         history_unlocked=history_unlocked,
                         my_name=MY_NAME)


@app.route('/api/medi/process-snapshots', methods=['POST'])
@api_login_required
def api_medi_process_snapshots():
    """Process snapshots for videos that don't have them."""
    import media_processor
    import traceback

    try:
        # Get count of pending videos before processing
        pending = database.get_messages_needing_metadata()
        pending_count = len([m for m in pending if m.get('media_type') in ('video', 'video_note', 'circle')])

        # Process and collect detailed results
        results = media_processor.process_pending_media_detailed()

        return jsonify({
            'success': True,
            'pending_before': pending_count,
            'processed': results.get('processed', 0),
            'failed': results.get('failed', 0),
            'details': results.get('details', []),
            'errors': results.get('errors', [])
        })
    except Exception as e:
        logger.error(f"Error processing snapshots: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        })


@app.route('/overview')
@app.route('/v6/overview')
@app.route('/stat')
@app.route('/v6/stat')
@login_required
def overview():
    """Stats page with messaging patterns."""
    # Get date range from query params (default: 30 days for faster load)
    days = request.args.get('days', 30, type=int)
    if days == 0:
        days = None  # None means all time

    daily_stats = database.get_daily_message_stats(MY_NAME)
    activity_data = database.get_activity_summary()
    daily_trend = database.get_daily_activity_trend(MY_NAME, days=min(days or 30, 30))
    hourly_heatmap = database.get_hourly_activity_heatmap(MY_NAME, days=7)

    # New comprehensive stats with date filter
    monthly_stats = database.get_monthly_stats(MY_NAME, days=days)
    all_time_stats = database.get_all_time_stats(MY_NAME, days=days)
    hourly_pattern = database.get_hourly_pattern(MY_NAME, days=days)
    weekday_pattern = database.get_weekday_pattern(MY_NAME, days=days)
    view_time_stats = database.get_view_time_stats(MY_NAME, days=days)
    message_timeline = database.get_message_timeline(MY_NAME, hours=24)

    return render_template('overview_v6.html',
                         daily_stats=daily_stats[:30],
                         activity_data=activity_data,
                         daily_trend=daily_trend,
                         hourly_heatmap=hourly_heatmap,
                         monthly_stats=monthly_stats,
                         all_time_stats=all_time_stats,
                         hourly_pattern=hourly_pattern,
                         weekday_pattern=weekday_pattern,
                         view_time_stats=view_time_stats,
                         message_timeline=message_timeline,
                         selected_days=days,
                         my_name=MY_NAME,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/list')
@app.route('/v6/list')
@login_required
def message_list():
    """List view of all messages with detailed info."""
    page = request.args.get('page', 1, type=int)

    # Check if history is unlocked (password 0319 entered)
    history_unlocked = session.get('history_unlocked', False)
    unlock_time = session.get('history_unlock_time', 0)

    # Check if 10 minutes have passed (600 seconds)
    import time
    if history_unlocked and (time.time() - unlock_time > 600):
        session['history_unlocked'] = False
        history_unlocked = False

    # Get configurable limits from settings
    locked_limit = dynamic_config.get_setting('locked_history_message_limit', 10)
    unlocked_limit = dynamic_config.get_setting('messages_per_page', 100)

    # Limit to configured number of messages if locked, otherwise use messages_per_page setting
    per_page = unlocked_limit if history_unlocked else locked_limit
    offset = (page - 1) * per_page

    msgs = database.get_messages(limit=per_page, offset=offset)
    stats = database.get_message_stats()
    pending = database.get_pending_messages()
    scheduled = database.get_scheduled_messages()

    return render_template('list_v6.html',
                         messages=msgs,
                         stats=stats,
                         pending=pending,
                         scheduled=scheduled,
                         page=page,
                         has_more=len(msgs) == per_page,
                         my_name=MY_NAME,
                         history_unlocked=history_unlocked,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/tutorials')
@login_required
def tutorials():
    """Tutorials page (safe mode / decoy page)."""
    return render_template('tutorials_v6.html',
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


def is_processor_running():
    """Check if incept_processor.py is running (external or embedded)."""
    global _embedded_processor_running

    # Check embedded processor first
    if _embedded_processor_running:
        return True

    # Check external process
    import subprocess
    try:
        result = subprocess.run(['pgrep', '-f', 'incept_processor.py'],
                              capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except:
        return False


def _run_embedded_processor():
    """Background thread that processes incept requests."""
    global _embedded_processor_running

    # Import processor functions
    try:
        from incept_processor import (
            process_request, get_settings, POLL_INTERVAL,
            check_and_restart_interrupted, check_and_continue_implementing_improvements,
            process_next_queued_improvement
        )
    except ImportError as e:
        logger.error(f"Failed to import incept_processor: {e}")
        _embedded_processor_running = False
        return

    logger.info("Embedded incept processor started")
    _embedded_processor_running = True

    # On startup: Resume any interrupted work from previous run
    try:
        logger.info("Checking for interrupted requests to resume...")
        check_and_restart_interrupted()
        check_and_continue_implementing_improvements()
    except Exception as e:
        logger.error(f"Error resuming interrupted work: {e}")

    while _embedded_processor_running:
        try:
            # Check for pending requests
            pending = database.get_pending_claude_requests()

            if pending:
                logger.info(f"Embedded processor: Found {len(pending)} pending request(s)")
                # Process one at a time
                process_request(pending[0])
            else:
                # No pending requests - check for queued improvements to process
                # This will create a new pending request if there's work in the queue
                process_next_queued_improvement()

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.error(f"Error in embedded processor: {e}")
            time.sleep(POLL_INTERVAL)

    logger.info("Embedded incept processor stopped")


def start_embedded_processor():
    """Start the embedded incept processor in a background thread."""
    global _embedded_processor_thread, _embedded_processor_running

    with _processor_lock:
        if _embedded_processor_running or (_embedded_processor_thread and _embedded_processor_thread.is_alive()):
            logger.info("Embedded processor already running")
            return False

        _embedded_processor_thread = threading.Thread(
            target=_run_embedded_processor,
            name="InceptProcessor",
            daemon=True  # Dies with main process
        )
        _embedded_processor_thread.start()

        # Wait briefly for thread to initialize
        time.sleep(0.2)

        logger.info("Started embedded incept processor thread")
        return True


def stop_embedded_processor():
    """Stop the embedded incept processor."""
    global _embedded_processor_running

    with _processor_lock:
        if not _embedded_processor_running:
            return False

        _embedded_processor_running = False
        logger.info("Stopping embedded processor...")
        return True


def get_incept_settings():
    """Get Incept processor settings from database."""
    settings = database.get_incept_settings()
    return settings or {
        'mode': 'api',  # 'local' or 'api'
        'model': 'claude-sonnet-4-20250514'
    }


@app.route('/incept')
@login_required
def incept_control():
    """Incept control page for self-improvement requests."""
    # Read recent requests and log
    requests_log = database.get_claude_requests(limit=50)
    processor_running = is_processor_running()
    settings = get_incept_settings()

    # Available models
    available_models = [
        {'id': 'claude-sonnet-4-20250514', 'name': 'Claude Sonnet 4', 'description': 'Best balance of speed and capability'},
        {'id': 'claude-opus-4-20250514', 'name': 'Claude Opus 4', 'description': 'Most capable, slower'},
        {'id': 'claude-3-5-sonnet-20241022', 'name': 'Claude 3.5 Sonnet', 'description': 'Previous generation'},
        {'id': 'claude-3-5-haiku-20241022', 'name': 'Claude 3.5 Haiku', 'description': 'Fast and efficient'},
    ]

    # Check auth availability
    has_api_key = bool(config.ANTHROPIC_API_KEY)
    has_oauth_token = bool(os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'))

    return render_template('incept_v6.html',
                         requests=requests_log,
                         processor_running=processor_running,
                         settings=settings,
                         available_models=available_models,
                         has_api_key=has_api_key,
                         has_oauth_token=has_oauth_token,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


# Keep old route for backward compatibility
@app.route('/claude')
@login_required
def claude_control():
    """Redirect to incept."""
    return redirect(url_for('incept_control'))


@app.route('/api/unlock-history', methods=['POST'])
@login_required
def api_unlock_history():
    """Unlock full history for 10 minutes with password 0314."""
    data = request.get_json() or {}
    password = data.get('password', '').strip()

    if password == '0319':
        import time
        session['history_unlocked'] = True
        session['history_unlock_time'] = time.time()
        return jsonify({'success': True, 'message': 'History unlocked for 10 minutes'})
    else:
        return jsonify({'success': False, 'error': 'Invalid password'}), 401


@app.route('/api/incept/request', methods=['POST'])
@login_required
def api_incept_request():
    """Submit a request to Incept."""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'error': 'Request text required'}), 400

    # Get current settings for mode and model
    settings = get_incept_settings()
    mode = data.get('mode', settings.get('mode', 'api'))
    model = data.get('model', settings.get('model', 'claude-sonnet-4-20250514'))
    auto_push = data.get('auto_push', True)  # Default to True for backwards compatibility

    req_id = database.add_claude_request(text, mode=mode, model=model, auto_push=auto_push)

    # Auto-start processor if it's not running
    if not is_processor_running():
        start_embedded_processor()

    return jsonify({'success': True, 'id': req_id, 'mode': mode, 'model': model, 'auto_push': auto_push})


# Keep old API route for compatibility
@app.route('/api/claude/request', methods=['POST'])
@login_required
def api_claude_request():
    """Submit a request (legacy route)."""
    return api_incept_request()


@app.route('/api/incept/requests', methods=['GET'])
@login_required
def api_incept_requests():
    """Get recent Incept requests."""
    requests_log = database.get_claude_requests(limit=50)
    return jsonify(requests_log)


@app.route('/api/claude/requests', methods=['GET'])
@login_required
def api_claude_requests():
    """Get recent requests (legacy route)."""
    return api_incept_requests()


@app.route('/api/incept/request/<int:req_id>/logs', methods=['GET'])
@login_required
def api_incept_logs(req_id):
    """Get logs for a specific Incept request."""
    logs = database.get_claude_logs(req_id)
    return jsonify({'logs': logs})


@app.route('/api/claude/request/<int:req_id>/logs', methods=['GET'])
@login_required
def api_claude_logs(req_id):
    """Get logs (legacy route)."""
    return api_incept_logs(req_id)


@app.route('/api/incept/settings', methods=['GET'])
@login_required
def api_incept_settings_get():
    """Get Incept settings."""
    settings = get_incept_settings()
    return jsonify(settings)


@app.route('/api/incept/settings', methods=['POST'])
@login_required
def api_incept_settings_set():
    """Update Incept settings."""
    data = request.get_json() or {}
    mode = data.get('mode', 'api')
    model = data.get('model', 'claude-sonnet-4-20250514')

    if mode not in ('local', 'api', 'cli_token'):
        return jsonify({'error': 'Invalid mode'}), 400

    database.save_incept_settings(mode, model)
    return jsonify({'success': True, 'mode': mode, 'model': model})


@app.route('/api/incept/request/<int:req_id>/cancel', methods=['POST'])
@login_required
def api_incept_cancel(req_id):
    """Cancel a pending or processing request."""
    success = database.cancel_claude_request(req_id)
    if success:
        database.add_claude_log(req_id, 'Request cancelled by user', 'warning')
        return jsonify({'success': True})
    return jsonify({'error': 'Could not cancel request (may already be completed)'}), 400


@app.route('/api/incept/request/<int:req_id>/restart', methods=['POST'])
@login_required
def api_incept_restart(req_id):
    """Restart a request with optional different mode/model."""
    data = request.get_json() or {}
    new_text = data.get('text')  # Optional: modify the request text
    mode = data.get('mode')  # Optional: use different mode
    model = data.get('model')  # Optional: use different model

    new_id = database.restart_claude_request(req_id, new_text, mode=mode, model=model)
    if new_id:
        # Log that this is a continuation
        database.add_claude_log(new_id, f'Continuation of request #{req_id}', 'info')
        return jsonify({'success': True, 'new_id': new_id, 'parent_id': req_id})
    return jsonify({'error': 'Could not restart request'}), 400


@app.route('/api/incept/request/<int:req_id>/context', methods=['GET'])
@login_required
def api_incept_context(req_id):
    """Get the full context of a request including parent chain."""
    context = database.get_request_context(req_id)
    if context:
        return jsonify(context)
    return jsonify({'error': 'Request not found'}), 404


@app.route('/api/incept/request/<int:req_id>/delete', methods=['POST'])
@login_required
def api_incept_delete(req_id):
    """Delete a request and its logs."""
    success = database.delete_claude_request(req_id)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Could not delete request'}), 400


@app.route('/api/incept/processor', methods=['GET'])
@login_required
def api_incept_processor_status():
    """Get embedded processor status."""
    return jsonify({
        'running': _embedded_processor_running,
        'embedded': True,
        'thread_alive': _embedded_processor_thread.is_alive() if _embedded_processor_thread else False
    })


@app.route('/api/incept/processor/start', methods=['POST'])
@login_required
def api_incept_processor_start():
    """Start the embedded processor."""
    started = start_embedded_processor()
    return jsonify({'success': started, 'running': _embedded_processor_running})


@app.route('/api/incept/processor/stop', methods=['POST'])
@login_required
def api_incept_processor_stop():
    """Stop the embedded processor."""
    stopped = stop_embedded_processor()
    return jsonify({'success': stopped, 'running': _embedded_processor_running})


@app.route('/api/incept/git/status', methods=['GET'])
@login_required
def api_git_status():
    """Get git status."""
    import subprocess
    try:
        # Get status
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Get branch info
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Get remote status
        remote_result = subprocess.run(
            ['git', 'status', '--porcelain', '--branch'],
            capture_output=True,
            text=True,
            timeout=5
        )

        status_lines = status_result.stdout.strip().split('\n') if status_result.stdout.strip() else []
        branch = branch_result.stdout.strip()

        # Parse status to categorize changes
        modified = []
        untracked = []
        staged = []

        for line in status_lines:
            if not line:
                continue
            status = line[:2]
            filename = line[3:]

            if status[0] in ['M', 'A', 'D', 'R', 'C']:
                staged.append(filename)
            if status[1] == 'M':
                modified.append(filename)
            elif status == '??':
                untracked.append(filename)

        # Check if behind/ahead of remote
        ahead_behind = ''
        if remote_result.stdout:
            first_line = remote_result.stdout.split('\n')[0]
            if '[ahead' in first_line:
                ahead_behind = 'ahead'
            elif '[behind' in first_line:
                ahead_behind = 'behind'

        has_changes = bool(modified or untracked or staged)

        # Get commit history (last 10 commits)
        commit_result = subprocess.run(
            ['git', 'log', '--oneline', '--decorate', '-10'],
            capture_output=True,
            text=True,
            timeout=5
        )

        commits = []
        if commit_result.stdout:
            for line in commit_result.stdout.strip().split('\n'):
                if line:
                    commits.append(line)

        # Get latest commit info
        latest_commit = None
        if commits:
            latest_commit_result = subprocess.run(
                ['git', 'log', '-1', '--format=%H|%an|%ar|%s'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if latest_commit_result.stdout:
                parts = latest_commit_result.stdout.strip().split('|')
                if len(parts) == 4:
                    latest_commit = {
                        'hash': parts[0][:7],
                        'author': parts[1],
                        'time': parts[2],
                        'message': parts[3]
                    }

        # Get unpushed improvements count
        unpushed_improvements = database.get_unpushed_improvements()

        return jsonify({
            'success': True,
            'branch': branch,
            'modified': modified,
            'untracked': untracked,
            'staged': staged,
            'has_changes': has_changes,
            'ahead_behind': ahead_behind,
            'clean': not has_changes,
            'commits': commits,
            'latest_commit': latest_commit,
            'unpushed_improvements': len(unpushed_improvements),
            'unpushed_improvement_list': [
                {'id': imp['id'], 'unique_id': imp.get('unique_id', f"IMP-{imp['id']}"), 'title': imp.get('title', 'Untitled')}
                for imp in unpushed_improvements
            ]
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/incept/git/commits', methods=['GET'])
@login_required
def api_git_commits():
    """Get detailed commit history with file changes."""
    import subprocess
    try:
        limit = request.args.get('limit', 15, type=int)

        # Get detailed commit info: hash, author, date, message, stats
        log_result = subprocess.run(
            ['git', 'log', f'-{limit}', '--format=%H|%an|%ar|%ai|%s', '--shortstat'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if log_result.returncode != 0:
            return jsonify({'error': 'Failed to get commit log'}), 500

        commits = []
        lines = log_result.stdout.strip().split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Parse commit line (hash|author|relative_date|full_date|message)
            if '|' in line:
                parts = line.split('|', 4)
                if len(parts) >= 5:
                    commit = {
                        'hash': parts[0][:7],
                        'full_hash': parts[0],
                        'author': parts[1],
                        'time_ago': parts[2],
                        'date': parts[3][:10],  # Just the date part
                        'message': parts[4],
                        'files_changed': None,
                        'insertions': None,
                        'deletions': None
                    }

                    # Check next line for stats
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line and 'file' in next_line:
                            # Parse stats: " 3 files changed, 45 insertions(+), 12 deletions(-)"
                            import re
                            files_match = re.search(r'(\d+) file', next_line)
                            ins_match = re.search(r'(\d+) insertion', next_line)
                            del_match = re.search(r'(\d+) deletion', next_line)

                            if files_match:
                                commit['files_changed'] = int(files_match.group(1))
                            if ins_match:
                                commit['insertions'] = int(ins_match.group(1))
                            if del_match:
                                commit['deletions'] = int(del_match.group(1))

                            i += 1  # Skip the stats line

                    commits.append(commit)
            i += 1

        return jsonify({
            'success': True,
            'commits': commits,
            'count': len(commits)
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/incept/git/push', methods=['POST'])
@login_required
def api_git_push():
    """Add all changes, commit, and push to git with improvement tracking."""
    import subprocess
    try:
        data = request.get_json() or {}
        commit_message = data.get('message', 'Auto-commit from Incept dashboard')

        # Get unpushed improvements BEFORE pushing (to log them)
        unpushed_improvements = database.get_unpushed_improvements()

        # Set git identity if not configured (needed on Render)
        subprocess.run(
            ['git', 'config', 'user.email', 'incept@telegram-dashboard.local'],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ['git', 'config', 'user.name', 'Incept Dashboard'],
            capture_output=True, timeout=5
        )

        # Check if origin remote exists
        remote_check = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, timeout=5
        )

        # If no remote, try to configure from env
        if remote_check.returncode != 0:
            github_repo = os.environ.get('GITHUB_REPO_URL')
            github_token = os.environ.get('GITHUB_TOKEN')

            if not github_repo:
                return jsonify({
                    'error': 'No git remote configured. Set GITHUB_REPO_URL env var (e.g., https://github.com/user/repo.git)'
                }), 500

            # Build URL with token if available
            if github_token and 'github.com' in github_repo:
                # Insert token into URL: https://TOKEN@github.com/user/repo.git
                push_url = github_repo.replace('https://', f'https://{github_token}@')
            else:
                push_url = github_repo

            # Add remote
            subprocess.run(
                ['git', 'remote', 'add', 'origin', push_url],
                capture_output=True, timeout=5
            )

        # Add all changes
        add_result = subprocess.run(
            ['git', 'add', '-A'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if add_result.returncode != 0:
            return jsonify({'error': f'Git add failed: {add_result.stderr}'}), 500

        # Commit
        commit_result = subprocess.run(
            ['git', 'commit', '-m', commit_message],
            capture_output=True,
            text=True,
            timeout=10
        )

        # It's ok if commit fails due to no changes
        if commit_result.returncode != 0 and 'nothing to commit' not in commit_result.stdout:
            return jsonify({'error': f'Git commit failed: {commit_result.stderr}'}), 500

        # Get current branch (empty if detached HEAD)
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True, text=True, timeout=5
        )
        current_branch = branch_result.stdout.strip()

        # Determine target branch (default to master, can be overridden by env)
        target_branch = os.environ.get('GIT_BRANCH', 'master')

        # Build push URL with token for authentication
        github_token = os.environ.get('GITHUB_TOKEN')
        if github_token:
            # Get current remote URL
            url_result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                capture_output=True, text=True, timeout=5
            )
            remote_url = url_result.stdout.strip()

            # If URL doesn't have token, set it temporarily
            if github_token not in remote_url and 'github.com' in remote_url:
                push_url = remote_url.replace('https://', f'https://{github_token}@')
                subprocess.run(
                    ['git', 'remote', 'set-url', 'origin', push_url],
                    capture_output=True, timeout=5
                )

        # Push - handle detached HEAD state (common on Render)
        if current_branch:
            # Normal branch - push with upstream tracking
            push_cmd = ['git', 'push', '-u', 'origin', current_branch]
        else:
            # Detached HEAD - push HEAD to target branch
            push_cmd = ['git', 'push', 'origin', f'HEAD:{target_branch}']

        push_result = subprocess.run(
            push_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if push_result.returncode != 0:
            error_msg = push_result.stderr
            if 'Authentication failed' in error_msg or 'could not read Username' in error_msg:
                return jsonify({
                    'error': 'Git push authentication failed. Set GITHUB_TOKEN env var with a personal access token.'
                }), 500
            return jsonify({'error': f'Git push failed: {error_msg}'}), 500

        # Mark improvements as pushed after successful push
        pushed_improvement_ids = [imp['id'] for imp in unpushed_improvements]
        if pushed_improvement_ids:
            database.mark_improvements_pushed(pushed_improvement_ids)

        # Build improvement summary for the response
        improvement_summary = []
        for imp in unpushed_improvements:
            improvement_summary.append({
                'id': imp['id'],
                'unique_id': imp.get('unique_id', f"IMP-{imp['id']}"),
                'title': imp.get('title', 'Untitled'),
                'commit_hash': imp.get('commit_hash')
            })

        # Log the push with all improvements included
        if improvement_summary:
            log_message = f"Pushed {len(improvement_summary)} improvement(s): " + \
                          ", ".join([f"{imp['unique_id']}" for imp in improvement_summary])
            database.add_system_log('git', 'push', 'success', log_message)

        return jsonify({
            'success': True,
            'message': 'Changes committed and pushed successfully',
            'commit_output': commit_result.stdout,
            'push_output': push_result.stdout,
            'improvements_pushed': improvement_summary,
            'improvement_count': len(improvement_summary)
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/incept/<int:req_id>')
@login_required
def incept_detail(req_id):
    """View details of a specific Incept request."""
    req = database.get_claude_request(req_id)
    if not req:
        return redirect(url_for('incept_control'))
    logs = database.get_claude_logs(req_id)
    return render_template('incept_detail_v6.html',
                         request=req,
                         logs=logs,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


# Keep old route for compatibility
@app.route('/claude/<int:req_id>')
@login_required
def claude_detail(req_id):
    """Redirect to incept detail."""
    return redirect(url_for('incept_detail', req_id=req_id))


# ==================== INCEPT+ ROUTES ====================

@app.route('/incept-plus')
@login_required
def incept_plus():
    """Incept+ page with AI-powered improvement suggestions."""
    all_suggestions = database.get_incept_suggestions(status='suggested', limit=50)
    improvements = database.get_incept_improvements(limit=50)
    settings = database.get_incept_plus_settings()
    auto_session = database.get_active_incept_auto_session()

    # Check auth availability for CLI modes
    has_api_key = bool(config.ANTHROPIC_API_KEY)
    has_oauth_token = bool(os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', ''))

    # Split suggestions into latest batch and older
    # Latest batch = suggestions created within 5 minutes of the newest one
    latest_suggestions = []
    older_suggestions = []

    if all_suggestions:
        # Parse the newest timestamp
        from datetime import timedelta
        newest = all_suggestions[0]
        newest_time = None
        if newest.get('created_at'):
            try:
                newest_time = datetime.fromisoformat(newest['created_at'].replace('Z', '+00:00'))
            except:
                newest_time = datetime.strptime(newest['created_at'][:19], '%Y-%m-%d %H:%M:%S')

        for s in all_suggestions:
            if newest_time and s.get('created_at'):
                try:
                    s_time = datetime.fromisoformat(s['created_at'].replace('Z', '+00:00'))
                except:
                    try:
                        s_time = datetime.strptime(s['created_at'][:19], '%Y-%m-%d %H:%M:%S')
                    except:
                        s_time = None

                if s_time and (newest_time - s_time) <= timedelta(minutes=5):
                    latest_suggestions.append(s)
                else:
                    older_suggestions.append(s)
            else:
                older_suggestions.append(s)
    else:
        latest_suggestions = []
        older_suggestions = []

    return render_template('incept_plus_v6.html',
                         suggestions=older_suggestions,
                         latest_suggestions=latest_suggestions,
                         improvements=improvements,
                         settings=settings,
                         auto_session=auto_session,
                         has_api_key=has_api_key,
                         has_oauth_token=has_oauth_token,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/incept-plus/suggest', methods=['POST'])
@login_required
def api_incept_plus_suggest():
    """Generate improvement suggestions using Claude."""
    import incept_plus_suggester

    data = request.get_json() or {}
    direction = data.get('direction', '').strip()
    context = data.get('context', '').strip() or None
    max_suggestions = int(data.get('max_suggestions', 10))

    if not direction:
        return jsonify({'success': False, 'error': 'Direction is required'}), 400

    try:
        suggestions = incept_plus_suggester.generate_and_save_suggestions(
            direction=direction,
            context=context,
            max_suggestions=max_suggestions
        )
        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/incept-plus/suggestions', methods=['GET'])
@login_required
def api_incept_plus_suggestions():
    """Get all suggestions with optional filtering."""
    status = request.args.get('status')
    category = request.args.get('category')
    limit = int(request.args.get('limit', 50))

    suggestions = database.get_incept_suggestions(status=status, category=category, limit=limit)
    return jsonify({'success': True, 'suggestions': suggestions})


@app.route('/api/incept-plus/suggestion/<int:suggestion_id>', methods=['GET'])
@login_required
def api_incept_plus_suggestion_detail(suggestion_id):
    """Get details of a specific suggestion."""
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return jsonify({'success': False, 'error': 'Suggestion not found'}), 404
    return jsonify({'success': True, 'suggestion': suggestion})


@app.route('/api/incept-plus/suggestion/<int:suggestion_id>/accept', methods=['POST'])
@login_required
def api_incept_plus_accept(suggestion_id):
    """Accept a suggestion for implementation."""
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return jsonify({'success': False, 'error': 'Suggestion not found'}), 404

    database.update_incept_suggestion_status(suggestion_id, 'accepted')
    return jsonify({'success': True})


@app.route('/api/incept-plus/suggestion/<int:suggestion_id>/reject', methods=['POST'])
@login_required
def api_incept_plus_reject(suggestion_id):
    """Reject a suggestion."""
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return jsonify({'success': False, 'error': 'Suggestion not found'}), 404

    database.update_incept_suggestion_status(suggestion_id, 'rejected')
    return jsonify({'success': True})


@app.route('/api/incept-plus/suggestion/<int:suggestion_id>/implement', methods=['POST'])
@login_required
def api_incept_plus_implement(suggestion_id):
    """Implement an accepted suggestion using Incept."""
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return jsonify({'success': False, 'error': 'Suggestion not found'}), 404

    # Create an Incept request for this suggestion
    request_text = f"""Implement the following improvement:

Title: {suggestion['title']}

Description: {suggestion['description']}

Implementation Details:
{suggestion['implementation_details']}

Category: {suggestion['category']}
Estimated Effort: {suggestion.get('estimated_effort', 'unknown')}
Dependencies: {suggestion.get('dependencies', 'none')}
"""

    # Get current settings
    incept_settings = database.get_incept_settings()
    mode = incept_settings.get('mode', 'api')
    model = incept_settings.get('model', 'claude-sonnet-4-20250514')

    # Add the request
    req_id = database.add_claude_request(request_text, mode=mode, model=model, auto_push=True)

    # Update suggestion status
    database.update_incept_suggestion_status(suggestion_id, 'implementing')

    return jsonify({
        'success': True,
        'request_id': req_id,
        'suggestion_id': suggestion_id
    })


@app.route('/api/incept-plus/improvements', methods=['GET'])
@login_required
def api_incept_plus_improvements():
    """Get all implemented improvements."""
    enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 100))

    improvements = database.get_incept_improvements(enabled_only=enabled_only, limit=limit)
    return jsonify({'success': True, 'improvements': improvements})


@app.route('/api/incept-plus/improvement/<int:improvement_id>/toggle', methods=['POST'])
@login_required
def api_incept_plus_toggle_improvement(improvement_id):
    """Toggle an improvement on/off."""
    improvement = database.get_incept_improvement(improvement_id)
    if not improvement:
        return jsonify({'success': False, 'error': 'Improvement not found'}), 404

    new_state = not bool(improvement['enabled'])
    database.toggle_incept_improvement(improvement_id, new_state)

    return jsonify({
        'success': True,
        'improvement_id': improvement_id,
        'enabled': new_state
    })


@app.route('/api/incept-plus/auto-mode/start', methods=['POST'])
@login_required
def api_incept_plus_auto_start():
    """Start auto-mode for continuous improvements."""
    data = request.get_json() or {}
    direction = data.get('direction', '').strip()
    max_suggestions = int(data.get('max_suggestions', 10))

    if not direction:
        return jsonify({'success': False, 'error': 'Direction is required'}), 400

    # Check if auto-mode is already running
    active_session = database.get_active_incept_auto_session()
    if active_session:
        return jsonify({
            'success': False,
            'error': 'Auto-mode is already running',
            'session_id': active_session['id']
        }), 400

    # Start new session
    session_id = database.start_incept_auto_session(direction, max_suggestions)

    return jsonify({
        'success': True,
        'session_id': session_id,
        'message': 'Auto-mode started'
    })


@app.route('/api/incept-plus/auto-mode/stop', methods=['POST'])
@login_required
def api_incept_plus_auto_stop():
    """Stop auto-mode."""
    active_session = database.get_active_incept_auto_session()
    if not active_session:
        return jsonify({'success': False, 'error': 'No active auto-mode session'}), 400

    database.update_incept_auto_session(active_session['id'], status='stopped')

    return jsonify({
        'success': True,
        'session_id': active_session['id'],
        'message': 'Auto-mode stopped'
    })


@app.route('/api/incept-plus/auto-mode/status', methods=['GET'])
@login_required
def api_incept_plus_auto_status():
    """Get current auto-mode status."""
    active_session = database.get_active_incept_auto_session()
    return jsonify({
        'success': True,
        'active': active_session is not None,
        'session': active_session
    })


# ============================================================================
# IMPROVEMENTS QUEUE MANAGEMENT
# ============================================================================

@app.route('/api/incept-plus/queue/status', methods=['GET'])
@login_required
def api_incept_plus_queue_status():
    """Get the improvements queue status."""
    status = database.get_improvements_queue_status()
    paused = database.is_improvements_queue_paused()

    return jsonify({
        'success': True,
        'queue': {
            'queued': status['queued'],
            'implementing': status['implementing'],
            'implemented': status['implemented'],
            'suggested': status['suggested'],
            'rejected': status['rejected'],
            'paused': paused,
            'current': status['current'],
            'next': status['next'],
            'total_in_queue': status['queued'] + status['implementing']
        }
    })


@app.route('/api/incept-plus/queue/pause', methods=['POST'])
@login_required
def api_incept_plus_queue_pause():
    """Pause the improvements queue."""
    database.pause_improvements_queue()
    database.add_system_log('incept_plus', 'queue_pause', 'success', 'Improvements queue paused')
    return jsonify({'success': True, 'message': 'Queue paused'})


@app.route('/api/incept-plus/queue/resume', methods=['POST'])
@login_required
def api_incept_plus_queue_resume():
    """Resume the improvements queue."""
    database.resume_improvements_queue()
    database.add_system_log('incept_plus', 'queue_resume', 'success', 'Improvements queue resumed')
    return jsonify({'success': True, 'message': 'Queue resumed'})


@app.route('/api/incept-plus/queue/clear', methods=['POST'])
@login_required
def api_incept_plus_queue_clear():
    """Clear the improvements queue (reject all accepted suggestions)."""
    data = request.get_json() or {}
    only_queued = data.get('only_queued', True)  # Default to only clearing queued, not implementing

    # Get queued improvements
    queued = database.get_queued_improvements(include_implementing=not only_queued)

    cleared_count = 0
    for suggestion in queued:
        if only_queued and suggestion['status'] == 'implementing':
            continue
        database.update_incept_suggestion_status(suggestion['id'], 'rejected')
        cleared_count += 1

    database.add_system_log('incept_plus', 'queue_clear', 'success',
                           f'Cleared {cleared_count} improvement(s) from queue')

    return jsonify({
        'success': True,
        'cleared': cleared_count,
        'message': f'Cleared {cleared_count} improvement(s) from queue'
    })


@app.route('/api/incept-plus/queue/items', methods=['GET'])
@login_required
def api_incept_plus_queue_items():
    """Get all items in the improvements queue."""
    queued = database.get_queued_improvements(include_implementing=True)

    return jsonify({
        'success': True,
        'items': queued
    })


@app.route('/api/incept-plus/queue/reorder', methods=['POST'])
@login_required
def api_incept_plus_queue_reorder():
    """Change the priority of an improvement in the queue."""
    data = request.get_json() or {}
    suggestion_id = data.get('suggestion_id')
    new_priority = data.get('priority')

    if not suggestion_id or new_priority is None:
        return jsonify({'success': False, 'error': 'suggestion_id and priority required'}), 400

    # Update priority (higher = processed first)
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE incept_suggestions
            SET priority = ?
            WHERE id = ? AND status = 'accepted'
        """, (new_priority, suggestion_id))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Suggestion not found or not in queue'}), 404

    return jsonify({'success': True, 'message': f'Priority updated to {new_priority}'})


@app.route('/api/incept-plus/settings', methods=['GET'])
@login_required
def api_incept_plus_settings_get():
    """Get Incept+ settings."""
    settings = database.get_incept_plus_settings()
    return jsonify({'success': True, 'settings': settings})


@app.route('/api/incept-plus/settings', methods=['POST'])
@login_required
def api_incept_plus_settings_update():
    """Update Incept+ settings."""
    data = request.get_json() or {}

    database.update_incept_plus_settings(
        auto_mode_enabled=data.get('auto_mode_enabled'),
        auto_mode_interval=data.get('auto_mode_interval'),
        suggestion_mode=data.get('suggestion_mode'),
        suggestion_model=data.get('suggestion_model'),
        max_list_length=data.get('max_list_length'),
        auto_implement_approved=data.get('auto_implement_approved')
    )

    return jsonify({'success': True})


@app.route('/api/incept-plus/batch-mode', methods=['GET'])
@login_required
def api_incept_plus_batch_mode_get():
    """Get batch mode status."""
    enabled = database.is_incept_batch_mode()
    return jsonify({'success': True, 'batch_mode': enabled})


@app.route('/api/incept-plus/batch-mode', methods=['POST'])
@login_required
def api_incept_plus_batch_mode_set():
    """Enable or disable batch mode."""
    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    database.set_incept_batch_mode(enabled)
    database.add_system_log('incept_plus', 'batch_mode',
                           'success' if enabled else 'info',
                           f'Batch mode {"enabled" if enabled else "disabled"}')
    return jsonify({'success': True, 'batch_mode': enabled})


@app.route('/api/incept-plus/push-queue-at-end', methods=['GET'])
@login_required
def api_incept_plus_push_queue_at_end_get():
    """Get push_queue_at_end status."""
    enabled = database.is_push_queue_at_end()
    return jsonify({'success': True, 'push_queue_at_end': enabled})


@app.route('/api/incept-plus/push-queue-at-end', methods=['POST'])
@login_required
def api_incept_plus_push_queue_at_end_set():
    """Enable or disable push_queue_at_end mode."""
    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    database.set_push_queue_at_end(enabled)
    database.add_system_log('incept_plus', 'push_queue_at_end',
                           'success' if enabled else 'info',
                           f'Push queue at end {"enabled" if enabled else "disabled"}')
    return jsonify({'success': True, 'push_queue_at_end': enabled})


@app.route('/api/incept-plus/git-status', methods=['GET'])
@login_required
def api_incept_plus_git_status():
    """Get git status: unpushed commits, current branch, etc."""
    import subprocess
    import os

    repo_path = os.path.dirname(__file__)

    try:
        # Get current branch
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        current_branch = branch_result.stdout.strip()

        # Get unpushed commits count
        unpushed_result = subprocess.run(
            ['git', 'rev-list', '--count', f'origin/{current_branch}..HEAD'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        unpushed_count = int(unpushed_result.stdout.strip()) if unpushed_result.returncode == 0 else 0

        # Get unpushed commit messages
        commits_result = subprocess.run(
            ['git', 'log', f'origin/{current_branch}..HEAD', '--oneline', '--no-decorate'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        unpushed_commits = commits_result.stdout.strip().split('\n') if commits_result.stdout.strip() else []

        # Check for uncommitted changes
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        has_uncommitted = bool(status_result.stdout.strip())

        return jsonify({
            'success': True,
            'branch': current_branch,
            'unpushed_count': unpushed_count,
            'unpushed_commits': unpushed_commits,
            'has_uncommitted_changes': has_uncommitted
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/incept-plus/push-all', methods=['POST'])
@login_required
def api_incept_plus_push_all():
    """Push all accumulated commits to remote."""
    import subprocess
    import os

    repo_path = os.path.dirname(__file__)

    try:
        # First check if there are commits to push
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        current_branch = branch_result.stdout.strip()

        unpushed_result = subprocess.run(
            ['git', 'rev-list', '--count', f'origin/{current_branch}..HEAD'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        unpushed_count = int(unpushed_result.stdout.strip()) if unpushed_result.returncode == 0 else 0

        if unpushed_count == 0:
            return jsonify({'success': True, 'message': 'No commits to push', 'pushed_count': 0})

        # Push to remote
        push_result = subprocess.run(
            ['git', 'push'],
            cwd=repo_path, capture_output=True, text=True, timeout=60
        )

        if push_result.returncode == 0:
            database.add_system_log('incept_plus', 'push_all', 'success',
                                   f'Pushed {unpushed_count} commit(s) to remote')
            return jsonify({
                'success': True,
                'message': f'Pushed {unpushed_count} commit(s)',
                'pushed_count': unpushed_count
            })
        else:
            error_msg = push_result.stderr or push_result.stdout
            database.add_system_log('incept_plus', 'push_all', 'error',
                                   f'Failed to push: {error_msg[:200]}')
            return jsonify({'success': False, 'error': error_msg}), 500

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Push timed out'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/incept-plus/improvement/<int:improvement_id>/rollback', methods=['POST'])
@login_required
def api_incept_plus_rollback(improvement_id):
    """Rollback an implemented improvement."""
    import incept_plus_tracker

    improvement = database.get_incept_improvement(improvement_id)
    if not improvement:
        return jsonify({'success': False, 'error': 'Improvement not found'}), 404

    success, message = incept_plus_tracker.rollback_improvement(improvement_id)

    return jsonify({
        'success': success,
        'message': message
    })


@app.route('/api/incept-plus/track-implementation', methods=['POST'])
@login_required
def api_incept_plus_track():
    """Track an improvement implementation after Incept request completes."""
    import incept_plus_tracker

    data = request.get_json() or {}
    suggestion_id = data.get('suggestion_id')
    request_id = data.get('request_id')

    if not suggestion_id or not request_id:
        return jsonify({'success': False, 'error': 'Missing suggestion_id or request_id'}), 400

    improvement_id = incept_plus_tracker.track_improvement_implementation(suggestion_id, request_id)

    if improvement_id:
        return jsonify({
            'success': True,
            'improvement_id': improvement_id
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to track improvement'
        }), 500


@app.route('/send', methods=['POST'])
@login_required
def send_message():
    """Queue a message to be sent."""
    text = request.form.get('text', '').strip()
    if text:
        database.queue_outgoing_message(text)
    return redirect(url_for('messages'))


@app.route('/api/send-message', methods=['POST'])
@login_required
def api_send_message():
    """API endpoint to send a message (returns JSON).

    Supports optional parameters:
    - reply_to: message_id to reply to
    - schedule_at: ISO datetime string to schedule the message
    - schedule_minutes: minutes from now to schedule the message
    """
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'No text provided'})

    # Get optional reply and scheduling parameters
    reply_to = data.get('reply_to')
    schedule_at = data.get('schedule_at')
    schedule_minutes = data.get('schedule_minutes')

    # Calculate scheduled_at if schedule_minutes is provided
    if schedule_minutes and not schedule_at:
        try:
            from datetime import timedelta
            minutes = int(schedule_minutes)
            scheduled_time = datetime.utcnow() + timedelta(minutes=minutes)
            schedule_at = scheduled_time.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid schedule_minutes value'})

    # Only mark messages as read if not scheduling
    if not schedule_at:
        # Mark all messages from her as read before sending
        # (since in Telegram it's impossible to send without seeing)
        my_name = config.MY_NAME if hasattr(config, 'MY_NAME') else 'Me'
        database.mark_all_messages_read(my_name)

    msg_id = database.queue_outgoing_message(text, reply_to_message_id=reply_to, scheduled_at=schedule_at)
    response = {'success': True, 'message_id': msg_id}
    if schedule_at:
        response['scheduled_at'] = schedule_at
    return jsonify(response)


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


@app.route('/api/notification/trigger', methods=['POST'])
def api_notification_trigger():
    """
    Webhook endpoint to trigger push notifications.
    This can be called by the monitor or external services (e.g., Home Assistant).
    No auth required for webhooks, but could add a secret token if needed.
    """
    data = request.get_json() or {}

    # Extract notification details
    title = data.get('title', 'Home Assistant')
    body = data.get('body', 'New automation event')
    icon = data.get('icon', '/static/ha-icon.svg')

    # Log the notification trigger
    database.add_system_log(
        'notification',
        'webhook_received',
        'info',
        f'Notification triggered: {title}',
        body
    )

    # Also send actual push notifications to subscribed devices
    try:
        import push_notifications
        result = push_notifications.send_push_notification(title, body, icon)
        return jsonify({
            'success': True,
            'message': 'Notification webhook received',
            'title': title,
            'body': body,
            'push_sent': result
        })
    except Exception as e:
        return jsonify({
            'success': True,
            'message': 'Notification webhook received (push failed)',
            'title': title,
            'body': body,
            'push_error': str(e)
        })


@app.route('/api/push/vapid-public-key', methods=['GET'])
def api_push_vapid_key():
    """Get the VAPID public key for push subscription."""
    return jsonify({'publicKey': config.VAPID_PUBLIC_KEY})


@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    """Subscribe to push notifications."""
    data = request.get_json() or {}

    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not endpoint or not p256dh or not auth:
        return jsonify({'error': 'Invalid subscription data'}), 400

    user_agent = request.headers.get('User-Agent', '')

    database.save_push_subscription(endpoint, p256dh, auth, user_agent)
    database.add_system_log('push', 'subscribe', 'info', f'New push subscription from {user_agent[:50]}')

    return jsonify({'success': True, 'message': 'Subscribed to push notifications'})


@app.route('/api/push/unsubscribe', methods=['POST'])
@login_required
def api_push_unsubscribe():
    """Unsubscribe from push notifications."""
    data = request.get_json() or {}
    endpoint = data.get('endpoint')

    if not endpoint:
        return jsonify({'error': 'Endpoint required'}), 400

    deleted = database.delete_push_subscription(endpoint)
    return jsonify({'success': True, 'deleted': deleted})


@app.route('/api/push/test', methods=['POST'])
@login_required
def api_push_test():
    """Send a test push notification with badge count."""
    import push_notifications
    # Get unread count for badge, minimum 1 for test
    unread = database.get_unread_count()
    badge_count = max(unread, 1)  # At least 1 for test
    result = push_notifications.send_push_notification(
        title="Home Assistant",
        body=f"Test notification - Badge: {badge_count}",
        tag="test",
        badge_count=badge_count
    )
    return jsonify({'success': True, 'result': result, 'badge_count': badge_count})


@app.route('/api/badge/count', methods=['GET'])
def api_badge_count():
    """Get current badge count (unread messages from target)."""
    # This endpoint doesn't require login so service worker can call it
    unread = database.get_unread_count()
    badge_enabled = database.get_setting('badge_enabled', 'true') == 'true'
    return jsonify({
        'count': unread if badge_enabled else 0,
        'enabled': badge_enabled
    })


@app.route('/api/settings/badge', methods=['GET', 'POST'])
@login_required
def api_settings_badge():
    """Get or set badge setting."""
    if request.method == 'GET':
        enabled = database.get_setting('badge_enabled', 'true')
        return jsonify({'enabled': enabled == 'true'})
    else:
        data = request.get_json() or {}
        enabled = data.get('enabled', True)
        database.set_setting('badge_enabled', 'true' if enabled else 'false')
        return jsonify({'success': True, 'enabled': enabled})


@app.route('/api/send-media', methods=['POST'])
@login_required
def api_send_media():
    """API endpoint to send a photo, video, or video circle."""
    import uuid

    try:
        if 'file' not in request.files:
            database.add_system_log('media', 'upload_failed', 'error', 'No file provided in request')
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        media_type = request.form.get('type', 'photo')  # photo, video, circle

        if file.filename == '':
            database.add_system_log('media', 'upload_failed', 'error', 'Empty filename')
            return jsonify({'error': 'No file selected'}), 400

        # Generate unique filename
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'bin'
        filename = f"upload_{media_type}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(config.MEDIA_PATH, filename)

        # Log upload start
        file_size = request.content_length or 0
        database.add_system_log('media', 'upload_start', 'info',
                              f'Starting upload: {file.filename} ({media_type})',
                              f'Size: {file_size} bytes, Destination: {filename}')

        # Save file
        file.save(filepath)

        # Get actual file size
        actual_size = os.path.getsize(filepath)

        database.add_system_log('media', 'upload_complete', 'success',
                              f'File saved: {filename}',
                              f'Size: {actual_size} bytes')

        # Queue for sending
        msg_id = database.queue_outgoing_media(filepath, media_type)

        database.add_system_log('media', 'queue_send', 'info',
                              f'Queued for sending: {filename} (msg_id: {msg_id})',
                              f'Type: {media_type}, Path: {filepath}')

        return jsonify({'success': True, 'id': msg_id, 'file': filename})

    except Exception as e:
        error_msg = str(e)
        database.add_system_log('media', 'upload_error', 'error',
                              f'Failed to upload media: {error_msg}',
                              f'Type: {media_type}, Original filename: {file.filename if "file" in locals() else "unknown"}')
        return jsonify({'error': f'Upload failed: {error_msg}'}), 500


@app.route('/api/react', methods=['POST'])
@login_required
def api_react():
    """API endpoint to add a reaction to a message."""
    data = request.get_json() or {}
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')
    emoji = data.get('emoji')  # fire, heart, unicorn
    if not message_id or not chat_id or not emoji:
        return jsonify({'error': 'message_id, chat_id and emoji required'}), 400
    react_id = database.queue_reaction(message_id, chat_id, emoji)
    return jsonify({'success': True, 'id': react_id})


@app.route('/api/react/<int:react_id>/status', methods=['GET'])
@login_required
def api_react_status(react_id):
    """Check the status of a reaction request."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pending_reactions WHERE id = ?", (react_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Reaction not found'}), 404
        return jsonify({
            'id': row['id'],
            'status': row['status'],
            'retry_count': row['retry_count'] or 0,
            'last_error': row['last_error'],
            'created_at': row['created_at'],
            'completed_at': row['completed_at']
        })


@app.route('/api/delete', methods=['POST'])
@login_required
def api_delete():
    """API endpoint to delete a message."""
    data = request.get_json() or {}
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')
    if not message_id or not chat_id:
        return jsonify({'error': 'message_id and chat_id required'}), 400
    delete_id = database.queue_delete(message_id, chat_id)
    return jsonify({'success': True, 'id': delete_id})


@app.route('/api/cancel-scheduled', methods=['POST'])
@login_required
def api_cancel_scheduled():
    """API endpoint to cancel a scheduled message."""
    data = request.get_json() or {}
    msg_id = data.get('id')
    if not msg_id:
        return jsonify({'error': 'id required'}), 400
    success = database.cancel_scheduled_message(msg_id)
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Message not found or already sent'}), 404


# ==================== DATABASE SYNC API ====================

@app.route('/api/db/export', methods=['GET'])
@login_required
def api_db_export():
    """Export database as JSON for syncing."""
    import json
    data = database.export_all_data()
    response = app.response_class(
        response=json.dumps(data, indent=2, default=str),
        status=200,
        mimetype='application/json'
    )
    response.headers['Content-Disposition'] = 'attachment; filename=telegram_export.json'
    return response


@app.route('/api/db/import', methods=['POST'])
@login_required
def api_db_import():
    """Import and merge database from JSON."""
    import json

    # Accept both file upload and JSON body
    if request.files and 'file' in request.files:
        file = request.files['file']
        data = json.load(file)
    elif request.is_json:
        data = request.get_json()
    else:
        return jsonify({'error': 'No data provided'}), 400

    result = database.import_and_merge_data(data)
    return jsonify({'success': True, **result})


@app.route('/api/db/stats', methods=['GET'])
@login_required
def api_db_stats():
    """Get database statistics for sync comparison."""
    stats = database.get_sync_stats()
    return jsonify(stats)


# ==================== AI ASSISTANT ====================

@app.route('/ai')
@login_required
def ai_assistant():
    """AI Assistant page - suggestions, Q&A, prompt management."""
    import ai_assistant as ai
    ai.ensure_default_prompts()

    prompts = database.get_ai_prompts()
    suggestions = database.get_ai_suggestions(limit=20)
    conversation = database.get_ai_conversation(limit=20)
    summaries = database.get_conversation_summaries(limit=5)
    pending_msgs = database.get_messages_without_suggestions(limit=5)

    # Get recent incoming messages (from her) for easy selection
    recent_incoming = database.get_messages(limit=10, direction='incoming')

    return render_template('ai_v6.html',
                         prompts=prompts,
                         suggestions=suggestions,
                         conversation=conversation,
                         summaries=summaries,
                         pending_messages=pending_msgs,
                         recent_incoming=recent_incoming,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/ai/suggest', methods=['POST'])
@login_required
def api_ai_suggest():
    """Generate reply suggestions for a message."""
    import ai_assistant as ai

    data = request.get_json() or {}
    message_id = data.get('message_id')
    message_text = data.get('text')
    prompt_id = data.get('prompt_id')
    num_suggestions = data.get('num_suggestions', 3)

    if not message_text:
        return jsonify({'error': 'text required'}), 400

    result = ai.generate_suggestions(
        message_text=message_text,
        message_id=message_id or 0,
        prompt_id=prompt_id,
        num_suggestions=num_suggestions
    )

    return jsonify(result)


@app.route('/api/ai/suggest/stream', methods=['POST'])
@login_required
def api_ai_suggest_stream():
    """Stream reply suggestions as they're parsed from the response."""
    import ai_assistant as ai
    from flask import Response, stream_with_context
    import json
    import re

    data = request.get_json() or {}
    message_text = data.get('text')
    prompt_id = data.get('prompt_id')
    custom_prompt = data.get('custom_prompt')  # One-time custom prompt
    num_suggestions = data.get('num_suggestions', 3)
    context_limit = data.get('context_limit', 50)
    context_days = data.get('context_days')  # None means use context_limit

    # Debug logging
    if custom_prompt:
        print(f"[AI] Using custom prompt ({len(custom_prompt)} chars): {custom_prompt[:80]}...")
    else:
        print(f"[AI] Using prompt_id: {prompt_id}")

    if context_days:
        print(f"[AI] Context: {context_days} days")
    else:
        print(f"[AI] Context: {context_limit} messages")

    if not message_text:
        return jsonify({'error': 'text required'}), 400

    def generate():
        # Track which indices have been yielded to prevent duplicates
        yielded_indices = set()

        # Get the full response first (streaming from LLM would require more complex setup)
        result = ai.generate_suggestions(
            message_text=message_text,
            message_id=0,
            prompt_id=prompt_id,
            custom_prompt=custom_prompt,
            num_suggestions=num_suggestions,
            context_limit=context_limit,
            context_days=context_days
        )

        if 'error' in result:
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        # If we have parsed suggestions as a list, use those
        suggestions = result.get('suggestions')
        if suggestions and isinstance(suggestions, list) and len(suggestions) > 0:
            # Check if suggestions have the expected format
            first_sug = suggestions[0]
            if isinstance(first_sug, dict) and 'text' in first_sug:
                if result.get('analysis'):
                    yield f"data: {json.dumps({'type': 'analysis', 'text': result['analysis']})}\n\n"
                for i, s in enumerate(suggestions):
                    if i not in yielded_indices and isinstance(s, dict) and 'text' in s:
                        yielded_indices.add(i)
                        yield f"data: {json.dumps({'type': 'suggestion', 'index': i, 'label': s.get('type', f'Option {i+1}'), 'text': s['text']})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

        # No parsed suggestions - try to parse raw_response or the result itself
        raw_text = result.get('raw_response', '')

        # Try to parse raw_text as JSON if it looks like JSON
        if raw_text and raw_text.strip().startswith('{'):
            try:
                json_start = raw_text.find('{')
                json_end = raw_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    parsed_json = json.loads(raw_text[json_start:json_end])
                    if parsed_json.get('suggestions') and isinstance(parsed_json['suggestions'], list):
                        if parsed_json.get('analysis'):
                            yield f"data: {json.dumps({'type': 'analysis', 'text': parsed_json['analysis']})}\n\n"
                        for i, s in enumerate(parsed_json['suggestions']):
                            if i not in yielded_indices and isinstance(s, dict) and 'text' in s:
                                yielded_indices.add(i)
                                yield f"data: {json.dumps({'type': 'suggestion', 'index': i, 'label': s.get('type', f'Option {i+1}'), 'text': s['text']})}\n\n"
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
            except json.JSONDecodeError:
                pass  # Fall through to other parsing methods

        if not raw_text:
            yield f"data: {json.dumps({'type': 'suggestion', 'index': 0, 'label': 'Response', 'text': 'No response received'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Truncate at first end-of-text marker (jailbreak models output multiple responses)
        end_markers = ['<|endoftext|>', '<|end|>', '<|eot_id|>', 'Human:', '\n\nHuman:']
        for marker in end_markers:
            if marker in raw_text:
                raw_text = raw_text.split(marker)[0]
                break

        # Parse and stream the raw response
        # First try to find analysis (support both ---ANALYSIS--- and ---\nANALYSIS formats)
        analysis_match = re.search(r'---\s*\n?ANALYSIS\s*\n?(.*?)(?=---\s*\n?REPLY|\Z)', raw_text, re.DOTALL | re.IGNORECASE)
        if analysis_match:
            analysis_text = analysis_match.group(1).strip()
            yield f"data: {json.dumps({'type': 'analysis', 'text': analysis_text})}\n\n"

        # Find all replies using our format (support multiple variations)
        # Pattern 1: ---REPLY 1--- or ---\nREPLY 1\n format
        reply_pattern = r'---\s*\n?REPLY\s*(\d+)\s*\n?---?\s*\n(.*?)(?=---\s*\n?REPLY|\Z)'
        replies = re.findall(reply_pattern, raw_text, re.DOTALL | re.IGNORECASE)

        if replies:
            for num, text in replies:
                idx = int(num) - 1
                if idx not in yielded_indices:
                    yielded_indices.add(idx)
                    clean_text = text.strip()
                    clean_text = re.sub(r'\n---.*$', '', clean_text, flags=re.DOTALL).strip()
                    yield f"data: {json.dumps({'type': 'suggestion', 'index': idx, 'label': f'Option {num}', 'text': clean_text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Fallback: try numbered list
        numbered = re.findall(r'(?:^|\n)\s*(\d+)[.):]\s*(.+?)(?=\n\s*\d+[.):]\s*|\n\n|$)', raw_text, re.DOTALL)
        if numbered:
            for i, (num, text) in enumerate(numbered[:num_suggestions]):
                if i not in yielded_indices:
                    yielded_indices.add(i)
                    yield f"data: {json.dumps({'type': 'suggestion', 'index': i, 'label': f'Option {i+1}', 'text': text.strip()})}\n\n"
        else:
            # Last resort: send raw as single option
            if 0 not in yielded_indices:
                yield f"data: {json.dumps({'type': 'suggestion', 'index': 0, 'label': 'Response', 'text': raw_text.strip()})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/ai/ask', methods=['POST'])
@login_required
def api_ai_ask():
    """Ask a question about the conversation."""
    import ai_assistant as ai

    data = request.get_json() or {}
    question = data.get('question', '').strip()

    if not question:
        return jsonify({'error': 'question required'}), 400

    # Get context options
    context_mode = data.get('context_mode', 'messages')  # 'messages' or 'days'
    context_value = data.get('context_value', 50)

    if context_mode == 'days':
        result = ai.ask_question(question, context_days=context_value)
    else:
        result = ai.ask_question(question, context_limit=context_value)

    return jsonify(result)


@app.route('/api/ai/context-preview', methods=['GET'])
@login_required
def api_ai_context_preview():
    """Get preview of context size (tokens, memory) for given parameters."""
    mode = request.args.get('mode', 'messages')  # 'messages' or 'days'
    value = request.args.get('value', 50, type=int)

    preview = database.get_context_preview(mode=mode, value=value)
    return jsonify(preview)


@app.route('/api/ai/summarize', methods=['POST'])
@login_required
def api_ai_summarize():
    """Generate a conversation summary."""
    import ai_assistant as ai

    data = request.get_json() or {}
    days = data.get('days', 7)

    result = ai.generate_summary(days=days)
    return jsonify(result)


@app.route('/api/ai/prompts', methods=['GET'])
@login_required
def api_ai_prompts_list():
    """List all AI prompts."""
    prompts = database.get_ai_prompts(active_only=False)
    return jsonify(prompts)


@app.route('/api/ai/prompts', methods=['POST'])
@login_required
def api_ai_prompts_create():
    """Create a new AI prompt."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    system_prompt = data.get('system_prompt', '').strip()
    description = data.get('description', '').strip()
    is_default = data.get('is_default', False)

    if not name or not system_prompt:
        return jsonify({'error': 'name and system_prompt required'}), 400

    prompt_id = database.save_ai_prompt(
        name=name,
        system_prompt=system_prompt,
        description=description,
        is_default=is_default
    )

    return jsonify({'success': True, 'id': prompt_id})


@app.route('/api/ai/prompts/<int:prompt_id>', methods=['PUT'])
@login_required
def api_ai_prompts_update(prompt_id):
    """Update an AI prompt."""
    data = request.get_json() or {}

    database.update_ai_prompt(
        prompt_id=prompt_id,
        name=data.get('name'),
        system_prompt=data.get('system_prompt'),
        description=data.get('description'),
        is_active=data.get('is_active'),
        is_default=data.get('is_default')
    )

    return jsonify({'success': True})


@app.route('/api/ai/prompts/<int:prompt_id>', methods=['DELETE'])
@login_required
def api_ai_prompts_delete(prompt_id):
    """Delete an AI prompt."""
    database.delete_ai_prompt(prompt_id)
    return jsonify({'success': True})


@app.route('/api/ai/conversation/clear', methods=['POST'])
@login_required
def api_ai_conversation_clear():
    """Clear the Q&A conversation history."""
    database.clear_ai_conversation()
    return jsonify({'success': True})


@app.route('/api/ai/process-pending', methods=['POST'])
@login_required
def api_ai_process_pending():
    """Process pending messages that need suggestions."""
    import ai_assistant as ai
    results = ai.process_pending_messages()
    return jsonify({'success': True, 'processed': len(results), 'results': results})


@app.route('/api/ai/provider', methods=['GET'])
@login_required
def api_ai_provider_status():
    """Get AI provider status."""
    import ai_assistant as ai
    return jsonify(ai.get_provider_status())


@app.route('/api/ai/provider', methods=['POST'])
@login_required
def api_ai_provider_set():
    """Set the AI provider."""
    import ai_assistant as ai
    data = request.get_json()
    provider = data.get('provider', 'anthropic')
    use_tailscale = data.get('use_tailscale', False)
    result = ai.set_provider(provider, use_tailscale)
    return jsonify(result)


@app.route('/api/ai/llm-settings', methods=['GET'])
@login_required
def api_ai_llm_settings_get():
    """Get LLM settings."""
    tailscale_url = getattr(config, "LOCAL_LLM_TAILSCALE_URL", "http://100.114.20.108:1234/v1")
    return jsonify({
        'tailscale_url': tailscale_url,
        'local_url': getattr(config, "LOCAL_LLM_URL", "http://localhost:1234/v1")
    })


@app.route('/api/ai/llm-settings', methods=['POST'])
@login_required
def api_ai_llm_settings_set():
    """Update LLM settings."""
    data = request.get_json() or {}
    tailscale_url = data.get('tailscale_url')

    if tailscale_url:
        # Update the config module at runtime
        config.LOCAL_LLM_TAILSCALE_URL = tailscale_url
        # Also update environment variable for persistence across restarts
        os.environ['LOCAL_LLM_TAILSCALE_URL'] = tailscale_url
        return jsonify({'success': True, 'tailscale_url': tailscale_url})

    return jsonify({'error': 'No URL provided'}), 400


@app.route('/api/ai/llm-settings/test', methods=['POST'])
@login_required
def api_ai_llm_settings_test():
    """Test connection to an LLM server."""
    import requests as req
    data = request.get_json() or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'available': False, 'error': 'No URL provided'})

    try:
        # Test the /models endpoint
        resp = req.get(f"{url}/models", timeout=5)
        if resp.status_code == 200:
            models_data = resp.json()
            model_name = None
            if models_data.get('data') and len(models_data['data']) > 0:
                model_name = models_data['data'][0].get('id', 'Unknown')
            return jsonify({'available': True, 'model': model_name})
        else:
            return jsonify({'available': False, 'error': f'Status {resp.status_code}'})
    except req.exceptions.Timeout:
        return jsonify({'available': False, 'error': 'Connection timeout'})
    except req.exceptions.ConnectionError:
        return jsonify({'available': False, 'error': 'Connection refused'})
    except Exception as e:
        return jsonify({'available': False, 'error': str(e)})


# ==================== MEDIA PROCESSING API ====================

@app.route('/api/media/process', methods=['POST'])
@login_required
def api_media_process():
    """Process pending media files to extract metadata."""
    try:
        import media_processor
        processed = media_processor.process_pending_media()
        return jsonify({'success': True, 'processed': processed})
    except ImportError:
        return jsonify({'error': 'Media processor not available (requires ffmpeg/ffprobe and PIL)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/media/check', methods=['GET'])
@login_required
def api_media_check():
    """Check media files for missing files."""
    try:
        import media_processor
        missing = media_processor.check_media_files()
        return jsonify({'success': True, 'missing_count': len(missing), 'missing_files': missing[:20]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/media/cleanup', methods=['POST'])
@login_required
def api_media_cleanup():
    """Clean up orphaned thumbnail files."""
    try:
        import media_processor
        removed = media_processor.cleanup_orphaned_thumbnails()
        return jsonify({'success': True, 'removed': removed})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SYSTEM LOG PAGE ====================

@app.route('/logs')
@app.route('/v6/logs')
@login_required
def system_logs():
    """View system log page."""
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    per_page = 100
    offset = (page - 1) * per_page

    logs = database.get_system_logs(limit=per_page, category=category if category else None,
                                   status=status if status else None, offset=offset)
    stats = database.get_system_log_stats()

    return render_template('logs_v6.html',
                         logs=logs,
                         stats=stats,
                         page=page,
                         has_more=len(logs) == per_page,
                         filter_category=category,
                         filter_status=status,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/logs/clear', methods=['POST'])
@login_required
def api_logs_clear():
    """Clear old log."""
    data = request.get_json() or {}
    days = data.get('days', 30)
    deleted = database.clear_old_logs(days)
    return jsonify({'success': True, 'deleted': deleted})


# ==================== DYNAMIC CONFIG API ====================
# Hot-reload config from /data disk - no redeploy needed!

@app.route('/settings')
@app.route('/v6/settings')
@login_required
def settings_page():
    """Settings page for dashboard configuration."""
    settings = dynamic_config.get_settings()
    return render_template('settings_v6.html',
                         settings=settings,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/config')
@app.route('/v6/config')
@login_required
def config_editor():
    """Config editor page."""
    all_config = dynamic_config.get_all_config()
    return render_template('config_v6.html',
                         prompts=all_config['prompts'],
                         settings=all_config['settings'],
                         config_dir=all_config['config_dir'],
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/config/prompts', methods=['GET'])
@login_required
def api_config_prompts_list():
    """Get all dynamic prompts."""
    return jsonify(dynamic_config.get_prompts())


@app.route('/api/config/prompts/<name>', methods=['GET'])
@login_required
def api_config_prompt_get(name):
    """Get a specific prompt."""
    prompts = dynamic_config.get_prompts()
    if name in prompts:
        return jsonify({'name': name, **prompts[name]})
    return jsonify({'error': 'Prompt not found'}), 404


@app.route('/api/config/prompts/<name>', methods=['POST', 'PUT'])
@login_required
def api_config_prompt_set(name):
    """Set/update a prompt."""
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    description = data.get('description', '')

    if not content:
        return jsonify({'error': 'content required'}), 400

    success = dynamic_config.set_prompt(name, content, description)
    if success:
        return jsonify({'success': True, 'name': name})
    return jsonify({'error': 'Failed to save prompt'}), 500


@app.route('/api/config/prompts/<name>', methods=['DELETE'])
@login_required
def api_config_prompt_delete(name):
    """Delete/reset a prompt."""
    success = dynamic_config.delete_prompt(name)
    return jsonify({'success': success})


@app.route('/api/config/settings', methods=['GET'])
@login_required
def api_config_settings_get():
    """Get all dynamic settings."""
    return jsonify(dynamic_config.get_settings())


@app.route('/api/config/settings', methods=['POST', 'PUT'])
@login_required
def api_config_settings_set():
    """Update settings."""
    data = request.get_json() or {}
    success = dynamic_config.set_settings(data)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to save settings'}), 500


@app.route('/api/config/all', methods=['GET'])
@login_required
def api_config_all():
    """Get all dynamic config."""
    return jsonify(dynamic_config.get_all_config())


@app.route('/api/config/reset', methods=['POST'])
@login_required
def api_config_reset():
    """Reset all config to defaults."""
    success = dynamic_config.reset_to_defaults()
    return jsonify({'success': success})


# ==================== LAB (CONTROL ROOM INTEGRATION) ====================

@app.route('/lab')
@app.route('/v6/lab')
@login_required
def lab():
    """Lab page - Control Room integration dashboard."""
    import control_room

    days = request.args.get('days', 30, type=int)
    connection_status = control_room.get_connection_status()

    # Only fetch data if connected
    lab_data = {}
    if connection_status.get('status') == 'connected':
        lab_data = control_room.get_full_lab_data(days=days)

    return render_template('lab_v6.html',
                         connection_status=connection_status,
                         lab_data=lab_data,
                         selected_days=days,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/lab/status', methods=['GET'])
@login_required
def api_lab_status():
    """Get Control Room connection status."""
    import control_room
    return jsonify(control_room.get_connection_status())


@app.route('/api/lab/dashboard', methods=['GET'])
@login_required
def api_lab_dashboard():
    """Fetch Control Room dashboard data."""
    import control_room
    days = request.args.get('days', 7, type=int)
    data = control_room.fetch_dashboard_data(days=days)
    return jsonify(data)


@app.route('/api/lab/entries', methods=['GET'])
@login_required
def api_lab_entries():
    """Fetch Control Room entries."""
    import control_room
    entry_type = request.args.get('type')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    since = request.args.get('since')

    data = control_room.fetch_entries(
        entry_type=entry_type,
        limit=limit,
        offset=offset,
        since=since
    )
    return jsonify(data)


@app.route('/api/lab/entries/<entry_type>', methods=['GET'])
@login_required
def api_lab_entries_by_type(entry_type):
    """Fetch Control Room entries by type."""
    import control_room
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)

    data = control_room.fetch_entries(
        entry_type=entry_type,
        limit=limit,
        offset=offset
    )
    return jsonify(data)


@app.route('/api/lab/schema', methods=['GET'])
@login_required
def api_lab_schema():
    """Fetch Control Room data schema."""
    import control_room
    data = control_room.fetch_schema()
    return jsonify(data)


@app.route('/api/lab/summary', methods=['GET'])
@login_required
def api_lab_summary():
    """Get formatted Lab summary data."""
    import control_room
    summary = control_room.get_lab_summary()
    return jsonify(summary)


@app.route('/api/lab/full', methods=['GET'])
@login_required
def api_lab_full():
    """Get full Lab data with charts and history."""
    import control_room
    days = request.args.get('days', 30, type=int)
    data = control_room.get_full_lab_data(days=days)
    return jsonify(data)


@app.route('/api/lab/category/<entry_type>/stats', methods=['GET'])
@login_required
def api_lab_category_stats(entry_type):
    """Get statistics for a specific category."""
    import control_room
    days = request.args.get('days', 30, type=int)
    stats = control_room.get_category_stats(entry_type, days=days)
    return jsonify(stats)


@app.route('/api/webhooks/control-room', methods=['POST'])
def webhook_control_room():
    """Webhook endpoint for Control Room notifications."""
    import control_room

    # Verify webhook secret
    webhook_secret = request.headers.get('X-Webhook-Secret', '')
    if not control_room.verify_webhook_secret(webhook_secret):
        logger.warning("Invalid webhook secret received")
        return jsonify({'error': 'Invalid webhook secret'}), 401

    data = request.get_json() or {}
    event = data.get('event', '')
    timestamp = data.get('timestamp', '')
    entry_data = data.get('data', {})

    logger.info(f"[Control Room Webhook] {event} at {timestamp}")

    # Store webhook event in database for tracking
    try:
        event_type = event.split('.')[0] if '.' in event else event
        database.add_system_log(
            'control_room',
            event,
            'info',
            f'Received {event} from Control Room',
            str(entry_data) if entry_data else None
        )
    except Exception as e:
        logger.error(f"Error logging webhook: {e}")

    return jsonify({'received': True, 'event': event})


@app.route('/control-room-summary')
@login_required
def control_room_summary():
    """Embed Control Room summary dashboard."""
    return render_template('control_room_summary.html', config=config)


@app.route('/lab2')
@app.route('/v6/lab2')
@login_required
def lab2():
    """Lab2 page - Embedded website with auto-login."""
    # Get the website URL from environment variable or use default
    embed_url = os.environ.get('LAB2_EMBED_URL', '')

    # If URL is provided, append auto-login parameters
    if embed_url:
        # Add auto-login parameters for admin user
        separator = '&' if '?' in embed_url else '?'
        embed_url_with_auth = f"{embed_url}{separator}username=admin&password=0319z&auto_login=true"
    else:
        embed_url_with_auth = ''

    return render_template('lab2_v6.html',
                         embed_url=embed_url_with_auth,
                         raw_url=embed_url)


# ==================== RENDER MANAGEMENT ====================

@app.route('/render')
@app.route('/v6/render')
@login_required
def render_status():
    """Render service management page."""
    # Check if API is configured
    api_configured = bool(config.RENDER_API_KEY and config.RENDER_SERVICE_ID
                         and config.RENDER_API_KEY != 'your_render_api_key'
                         and config.RENDER_SERVICE_ID != 'your_service_id')

    service = {}
    deploys = []
    env_vars = []
    api_error = None

    if api_configured:
        try:
            import render_api

            # Get service info
            service = render_api._request("GET", f"/services/{render_api.SERVICE_ID}") or {}
            if not service:
                api_error = "Could not connect to Render API"

            # Get recent deploys
            deploys_raw = render_api._request("GET", f"/services/{render_api.SERVICE_ID}/deploys?limit=10") or []
            deploys = [d.get('deploy', d) for d in deploys_raw]

            # Get env vars (mask sensitive values)
            env_vars_raw = render_api._request("GET", f"/services/{render_api.SERVICE_ID}/env-vars") or []
            sensitive_keys = ['KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'HASH']
            for item in env_vars_raw:
                ev = item.get('envVar', item)
                is_sensitive = any(s in ev['key'].upper() for s in sensitive_keys)
                env_vars.append({
                    'key': ev['key'],
                    'value': '***' if is_sensitive else ev.get('value', '')[:50]
                })
        except Exception as e:
            api_error = str(e)

    # Default service info when not configured
    if not service:
        service = {
            'name': 'telegram-monitor',
            'suspended': 'unknown',
            'branch': 'master',
            'autoDeploy': 'yes',
            'serviceDetails': {
                'url': os.getenv('RENDER_EXTERNAL_URL', 'Not deployed'),
                'region': 'oregon',
                'plan': 'starter',
                'runtime': 'python'
            }
        }

    return render_template('render_v6.html',
                         service=service,
                         deploys=deploys,
                         env_vars=env_vars,
                         api_configured=api_configured,
                         api_error=api_error,
                         last_refresh=datetime.now().strftime('%H:%M:%S'))


@app.route('/api/render/status', methods=['GET'])
@login_required
def api_render_status():
    """Get Render service status."""
    import render_api
    service = render_api._request("GET", f"/services/{render_api.SERVICE_ID}")
    return jsonify(service or {'error': 'Failed to fetch'})


@app.route('/api/render/deploys', methods=['GET'])
@login_required
def api_render_deploys():
    """Get recent deploys."""
    import render_api
    limit = request.args.get('limit', 10, type=int)
    deploys = render_api._request("GET", f"/services/{render_api.SERVICE_ID}/deploys?limit={limit}")
    return jsonify(deploys or [])


@app.route('/api/render/deploy', methods=['POST'])
@login_required
def api_render_deploy():
    """Trigger a new deploy."""
    import render_api
    data = request.get_json() or {}
    clear_cache = data.get('clear_cache', False)
    result = render_api.trigger_deploy(clear_cache=clear_cache)
    return jsonify(result or {'error': 'Failed to trigger deploy'})


@app.route('/api/render/restart', methods=['POST'])
@login_required
def api_render_restart():
    """Restart the service."""
    import render_api
    result = render_api._request("POST", f"/services/{render_api.SERVICE_ID}/restart")
    return jsonify({'success': result is not None})


@app.route('/api/render/env', methods=['GET'])
@login_required
def api_render_env_list():
    """List environment variables."""
    import render_api
    result = render_api._request("GET", f"/services/{render_api.SERVICE_ID}/env-vars")
    return jsonify(result or [])


@app.route('/api/render/env', methods=['POST'])
@login_required
def api_render_env_set():
    """Set an environment variable."""
    import render_api
    data = request.get_json() or {}
    key = data.get('key')
    value = data.get('value')
    if not key or value is None:
        return jsonify({'error': 'key and value required'}), 400
    result = render_api.set_env_var(key, value)
    return jsonify({'success': result is not None})


@app.route('/api/render/env/<key>', methods=['DELETE'])
@login_required
def api_render_env_delete(key):
    """Delete an environment variable."""
    import render_api
    result = render_api.delete_env_var(key)
    return jsonify({'success': result is not None})


# Auto-start embedded processor on Render or when EMBEDDED_PROCESSOR=1
def _auto_start_processor():
    """Auto-start the embedded processor if configured."""
    on_render = os.getenv('RENDER') == 'true'
    explicit_enable = os.getenv('EMBEDDED_PROCESSOR', '').lower() in ('1', 'true', 'yes')

    if on_render or explicit_enable:
        logger.info("Auto-starting embedded incept processor...")
        start_embedded_processor()


# Start processor when module loads (for gunicorn/production)
def _delayed_start():
    time.sleep(2)
    _auto_start_processor()

_startup_thread = threading.Thread(target=_delayed_start, daemon=True)
_startup_thread.start()


if __name__ == '__main__':
    print("="*50)
    print("  Dashboard v6 (Hourly)")
    print("="*50)
    print(f"  URL: http://0.0.0.0:{V6_PORT}")
    print(f"  Password: {config.DASHBOARD_PASSWORD}")
    print("="*50)

    # In debug mode, don't auto-start (use EMBEDDED_PROCESSOR=1 to override)
    if os.getenv('EMBEDDED_PROCESSOR', '').lower() in ('1', 'true', 'yes'):
        print("  Embedded processor: ENABLED")
        start_embedded_processor()
    else:
        print("  Embedded processor: disabled (set EMBEDDED_PROCESSOR=1 to enable)")
    print("="*50)

    app.run(
        host=config.DASHBOARD_HOST,
        port=V6_PORT,
        debug=True
    )
