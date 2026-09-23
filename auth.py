import hmac
import os
from functools import wraps
from flask import session, request, jsonify, redirect, url_for

AUTH_PASSWORD = os.environ.get('FINANCY_PASSWORD')  # None = pas d'auth
CSRF_PROTECTED_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


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
        if request.method in CSRF_PROTECTED_METHODS:
            token = request.headers.get('X-CSRF-Token', '')
            attendu = session.get('csrf_token')
            # Comparaison a temps constant : `!=` s'arrete au premier
            # caractere different et laisse deviner le jeton par la duree.
            if (not token or not isinstance(attendu, str)
                    or not hmac.compare_digest(token.encode(), attendu.encode())):
                return jsonify({'error': 'CSRF token invalide'}), 403
        return f(*args, **kwargs)
    return decorated
