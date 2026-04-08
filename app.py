import os
import secrets
from flask import Flask, render_template, session, request, redirect, url_for, jsonify
from auth import AUTH_PASSWORD, login_required, csrf_protect
from models import init_db, is_demo_mode, set_demo_mode, DEMO_DB_PATH
from routes import all_blueprints

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))


# ─── Auth routes ──────────────────────────────────────────────────────────────

from flask import Blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if not AUTH_PASSWORD:
        return redirect(url_for('index'))
    if request.method == 'POST':
        if request.form.get('password') == AUTH_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='Mot de passe incorrect.')
    return render_template('login.html', error=None)

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
    return jsonify({'demo': is_demo_mode(), 'available': os.path.exists(DEMO_DB_PATH)})


@app.route('/api/demo-mode', methods=['PUT'])
@login_required
@csrf_protect
def toggle_demo_mode():
    data = request.json
    if not isinstance(data, dict) or 'demo' not in data:
        return jsonify({'error': 'Champ "demo" requis'}), 400
    if data['demo'] and not os.path.exists(DEMO_DB_PATH):
        return jsonify({'error': 'Fichier demo.db introuvable'}), 404
    set_demo_mode(bool(data['demo']))
    return jsonify({'demo': is_demo_mode()})


# ─── Register blueprints ─────────────────────────────────────────────────────

for bp in all_blueprints:
    app.register_blueprint(bp)


# ─── Démarrage ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("✓ Base initialisée — http://localhost:5000")
    app.run(debug=True, port=5000)
