"""
Authentication routes for multi-user support.
"""

from functools import wraps
from flask import session, redirect, url_for, request, jsonify


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get current logged-in user info from session."""
    if not session.get('user_id'):
        return None
    return {
        'id': session.get('user_id'),
        'username': session.get('username')
    }


def init_auth_routes(app, user_manager):
    """Initialize authentication routes on Flask app."""

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        from flask import render_template
        error = None

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user = user_manager.authenticate(username, password)

            if user:
                session.permanent = True
                session['user_id'] = user['id']
                session['username'] = user['username']

                # Check if setup is complete
                if not user_manager.is_setup_complete(user['id']):
                    return redirect(url_for('setup'))

                return redirect(url_for('index'))
            else:
                error = 'Invalid username or password'

        return render_template('multi/login.html', error=error)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        from flask import render_template
        error = None
        success = None

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm', '')

            if not username:
                error = 'Username is required'
            elif not username.replace('_', '').isalnum():
                error = 'Username can only contain letters, numbers, and underscores'
            elif len(username) < 3:
                error = 'Username must be at least 3 characters'
            elif not password:
                error = 'Password is required'
            elif len(password) < 4:
                error = 'Password must be at least 4 characters'
            elif password != confirm:
                error = 'Passwords do not match'
            else:
                user_id = user_manager.create_user(username, password)
                if user_id:
                    # Auto-login after registration
                    session.permanent = True
                    session['user_id'] = user_id
                    session['username'] = username.lower()
                    return redirect(url_for('setup'))
                else:
                    error = 'Username already exists'

        return render_template('multi/register.html', error=error, success=success)

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))
