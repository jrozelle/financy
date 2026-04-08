import json
from flask import Blueprint, jsonify, request
from models import get_db, load_referential
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
