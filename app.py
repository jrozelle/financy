import os
import hmac
import logging
import secrets
import shutil
import time
from collections import defaultdict
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optionnel — variables d'env directes

from flask import Flask, render_template, session, request, redirect, url_for, jsonify
from auth import AUTH_PASSWORD, login_required, csrf_protect
from models import init_db, set_demo_mode, get_db_path, DEMO_DB_PATH
from routes import all_blueprints

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('financy')

# ─── App ──────────────────────────────────────────────────────────────────────

app = Flask(__name__)
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning('SECRET_KEY non définie — clé aléatoire générée (sessions invalidées au redémarrage)')
if len(_secret) < 32:
    logger.warning('SECRET_KEY trop courte (%d car.) — recommandé : 32+ caractères', len(_secret))
app.secret_key = _secret


# ─── Upload size limit ───────────────────────────────────────────────────────

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB


# ─── Session config ──────────────────────────────────────────────────────────

def _env_int(key, default, min_val=1, max_val=None):
    try:
        val = int(os.environ.get(key, default))
        if val < min_val:
            val = min_val
        if max_val and val > max_val:
            val = max_val
        return val
    except (ValueError, TypeError):
        logger.warning('%s invalide — valeur par défaut %s', key, default)
        return default

_session_minutes = _env_int('SESSION_TIMEOUT_MINUTES', 60, min_val=5, max_val=1440)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=_session_minutes)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True


# ─── Rate limiting (login) ───────────────────────────────────────────────────

_login_attempts = defaultdict(list)  # IP → [timestamp, ...]
_RATE_LIMIT_WINDOW = 300   # 5 minutes
_RATE_LIMIT_MAX    = 10    # max attempts per window

def _is_rate_limited(ip):
    now = time.time()
    attempts = _login_attempts[ip]
    # Purge old entries
    _login_attempts[ip] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    return len(_login_attempts[ip]) >= _RATE_LIMIT_MAX

def _record_attempt(ip):
    _login_attempts[ip].append(time.time())


# ─── Auth routes ──────────────────────────────────────────────────────────────

from flask import Blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if not AUTH_PASSWORD:
        return redirect(url_for('index'))
    if request.method == 'POST':
        ip = request.remote_addr
        if _is_rate_limited(ip):
            logger.warning('Login rate limited — IP %s', ip)
            return render_template('login.html', error='Trop de tentatives. Réessayez dans quelques minutes.',
                                   csrf_token=session.get('csrf_token', '')), 429
        _record_attempt(ip)
        form_token = request.form.get('csrf_token', '')
        if not form_token or form_token != session.get('csrf_token'):
            logger.warning('Login failed — CSRF token mismatch')
            return render_template('login.html', error='Session expirée, réessayez.',
                                   csrf_token=session.get('csrf_token', ''))
        if hmac.compare_digest(request.form.get('password', ''), AUTH_PASSWORD):
            # Regenerate session to prevent session fixation
            session.clear()
            session['authenticated'] = True
            session['csrf_token'] = secrets.token_hex(32)
            session.permanent = True
            logger.info('Login successful')
            return redirect(url_for('index'))
        logger.warning('Login failed — bad password from %s', ip)
        return render_template('login.html', error='Mot de passe incorrect.',
                               csrf_token=session.get('csrf_token', ''))
    return render_template('login.html', error=None, csrf_token=session.get('csrf_token', ''))

@auth_bp.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('auth.login_page'))

app.register_blueprint(auth_bp)


# ─── CSRF ─────────────────────────────────────────────────────────────────────

@app.before_request
def ensure_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    # Sync demo mode from session to models on every request
    set_demo_mode(session.get('demo_mode', False))


# ─── Index ────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html', has_auth=bool(AUTH_PASSWORD), csrf_token=session.get('csrf_token', ''))


@app.route('/api/csrf-token')
@login_required
def get_csrf_token():
    return jsonify({'token': session.get('csrf_token', '')})


# ─── Demo mode ────────────────────────────────────────────────────────────────

@app.route('/api/demo-mode', methods=['GET'])
@login_required
def get_demo_mode():
    return jsonify({'demo': session.get('demo_mode', False), 'available': os.path.exists(DEMO_DB_PATH)})


@app.route('/api/demo-mode', methods=['PUT'])
@login_required
@csrf_protect
def toggle_demo_mode():
    data = request.json
    if not isinstance(data, dict) or 'demo' not in data:
        return jsonify({'error': 'Champ "demo" requis'}), 400
    if data['demo'] and not os.path.exists(DEMO_DB_PATH):
        return jsonify({'error': 'Fichier demo.db introuvable'}), 404
    session['demo_mode'] = bool(data['demo'])
    set_demo_mode(session['demo_mode'])
    logger.info('Demo mode: %s', 'ON' if session['demo_mode'] else 'OFF')
    return jsonify({'demo': session['demo_mode']})


# ─── Backup ───────────────────────────────────────────────────────────────────

@app.route('/api/backup', methods=['POST'])
@login_required
@csrf_protect
def create_backup():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return jsonify({'error': 'Base de données introuvable'}), 404

    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    backup_path = os.path.join(backup_dir, f'{db_name}_{ts}.db')

    shutil.copy2(db_path, backup_path)
    size_kb = round(os.path.getsize(backup_path) / 1024, 1)
    backup_filename = f'{db_name}_{ts}.db'
    logger.info('Backup created: %s (%.1f KB)', backup_filename, size_kb)
    return jsonify({
        'ok': True,
        'filename': backup_filename,
        'size_kb': size_kb,
        'timestamp': ts,
    })


# ─── Register blueprints ─────────────────────────────────────────────────────

for bp in all_blueprints:
    app.register_blueprint(bp)


# ─── Request logging ─────────────────────────────────────────────────────────

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'"
    )
    if response.status_code >= 400 and request.path.startswith('/api/'):
        logger.warning('%s %s → %s', request.method, request.path, response.status_code)
    return response


# ─── Démarrage ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = _env_int('PORT', 5017, min_val=1, max_val=65535)
    debug = os.environ.get('FLASK_ENV') != 'production'
    init_db()
    logger.info('Base initialisée — http://localhost:%d (debug=%s)', port, debug)
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, debug=debug, port=port)
