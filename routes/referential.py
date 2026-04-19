import json
import os
from flask import Blueprint, jsonify, request
from models import get_db, load_referential, REFERENTIAL_TEMPLATES
from auth import login_required, csrf_protect

referential_bp = Blueprint('referential', __name__)


@referential_bp.route('/api/config')
@login_required
def get_config():
    with get_db() as conn:
        entity_names = [r['name'] for r in
                        conn.execute('SELECT name FROM entities ORDER BY name').fetchall()]
        ref = load_referential(conn)
    return jsonify({
        'owners':               ref['owners'],
        'categories':           ref['categories'],
        'envelopes':            list(ref['envelope_meta'].keys()),
        'flux_types':           ref['flux_types'],
        'liquidity_order':      ref['liquidity_order'],
        'category_mobilizable': ref['category_mobilizable'],
        'envelope_meta':        ref['envelope_meta'],
        'entity_types':         ref['entity_types'],
        'valuation_modes':      ref['valuation_modes'],
        'entity_names':         entity_names,
    })


# — Allocation cible —

@referential_bp.route('/api/targets', methods=['GET'])
@login_required
def get_targets():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='allocation_targets'").fetchone()
    if row:
        try:
            return jsonify(json.loads(row['value']))
        except Exception:
            pass
    return jsonify({})


@referential_bp.route('/api/targets', methods=['PUT'])
@login_required
@csrf_protect
def save_targets():
    data = request.json
    if not isinstance(data, dict):
        return jsonify({'error': 'Objet JSON attendu'}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('allocation_targets', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True})


# — Alertes —

@referential_bp.route('/api/alerts', methods=['GET'])
@login_required
def get_alerts():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='user_alerts'").fetchone()
    if row:
        try:
            return jsonify(json.loads(row['value']))
        except Exception:
            pass
    return jsonify([])


@referential_bp.route('/api/alerts', methods=['PUT'])
@login_required
@csrf_protect
def save_alerts_api():
    data = request.json
    if not isinstance(data, list):
        return jsonify({'error': 'Tableau JSON attendu'}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('user_alerts', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True})


# — Référentiel —

@referential_bp.route('/api/referential/templates', methods=['GET'])
@login_required
def get_templates():
    return jsonify({name: tpl for name, tpl in REFERENTIAL_TEMPLATES.items()})


@referential_bp.route('/api/referential', methods=['GET'])
@login_required
def get_referential_api():
    with get_db() as conn:
        ref = load_referential(conn)
    return jsonify(ref)


@referential_bp.route('/api/referential', methods=['PUT'])
@login_required
@csrf_protect
def save_referential():
    data = request.json
    required = ['owners', 'categories', 'category_mobilizable', 'envelope_meta']
    for k in required:
        if k not in data:
            return jsonify({'error': f'Champ manquant : {k}'}), 400
    if not data['owners']:
        return jsonify({'error': 'La liste des propriétaires ne peut pas être vide'}), 400
    data.pop('liquidity_order', None)
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('referential', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True})


@referential_bp.route('/api/referential/orphans', methods=['GET'])
@login_required
def check_orphans():
    """Vérifie les positions/flux orphelins si une catégorie ou enveloppe est supprimée."""
    with get_db() as conn:
        ref = load_referential(conn)
        categories = set(ref['categories'])
        envelopes  = set(ref.get('envelope_meta', {}).keys())

        orphans = {}

        # Catégories utilisées dans positions mais absentes du référentiel
        cat_rows = conn.execute(
            'SELECT DISTINCT category FROM positions WHERE category IS NOT NULL'
        ).fetchall()
        for r in cat_rows:
            cat = r['category']
            if cat and cat not in categories:
                cnt = conn.execute('SELECT COUNT(*) as c FROM positions WHERE category=?', (cat,)).fetchone()['c']
                orphans.setdefault('categories', {})[cat] = cnt

        # Enveloppes utilisées dans positions/flux mais absentes du référentiel
        env_rows = conn.execute(
            'SELECT DISTINCT envelope FROM positions WHERE envelope IS NOT NULL '
            'UNION SELECT DISTINCT envelope FROM flux WHERE envelope IS NOT NULL'
        ).fetchall()
        for r in env_rows:
            env = r['envelope']
            if env and env not in envelopes:
                pos_cnt = conn.execute('SELECT COUNT(*) as c FROM positions WHERE envelope=?', (env,)).fetchone()['c']
                flux_cnt = conn.execute('SELECT COUNT(*) as c FROM flux WHERE envelope=?', (env,)).fetchone()['c']
                if pos_cnt or flux_cnt:
                    orphans.setdefault('envelopes', {})[env] = {'positions': pos_cnt, 'flux': flux_cnt}

    return jsonify(orphans)


# — Parametres applicatifs (cles API, etc.) —

from services.settings import load_settings as _load_settings, save_settings as _save_settings


@referential_bp.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    s = _load_settings()
    api_key = s.get('anthropic_api_key', '')
    env_key = os.environ.get('ANTHROPIC_API_KEY', '')
    effective = api_key or env_key
    result = {
        'anthropic_api_key_set': bool(api_key),
        'anthropic_api_key_masked': (api_key[:10] + '...' + api_key[-4:]) if len(api_key) > 14 else '',
        'anthropic_api_key_env': bool(env_key),
        'effective_source': 'db' if api_key else ('env' if env_key else 'none'),
        'llm_available': bool(effective),
    }
    return jsonify(result)


@referential_bp.route('/api/settings', methods=['PUT'])
@login_required
@csrf_protect
def update_settings():
    d = request.json
    if not d:
        return jsonify({'error': 'Corps requis'}), 400
    with get_db() as conn:
        s = _load_settings()
        if 'anthropic_api_key' in d:
            key = (d['anthropic_api_key'] or '').strip()
            if key:
                if not key.startswith('sk-ant-'):
                    return jsonify({'error': 'Format de cle invalide (attendu : sk-ant-...)'}), 400
                s['anthropic_api_key'] = key
            else:
                s.pop('anthropic_api_key', None)
        _save_settings(conn, s)
    return jsonify({'ok': True})
