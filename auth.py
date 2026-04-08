import os
import secrets
from functools import wraps
from flask import session, request, jsonify, redirect, url_for, render_template

AUTH_PASSWORD = os.environ.get('FINANCY_PASSWORD')  # None = pas d'auth


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_PASSWORD and not session.get('authenticated'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Non authentifié'}), 401
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = request.headers.get('X-CSRF-Token', '')
            if not token or token != session.get('csrf_token'):
                return jsonify({'error': 'CSRF token invalide'}), 403
        return f(*args, **kwargs)
    return decorated
