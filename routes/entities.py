from flask import Blueprint, jsonify, request
from datetime import datetime
from models import get_db, validate_number, validate_string
from auth import login_required, csrf_protect

entities_bp = Blueprint('entities', __name__)


@entities_bp.route('/api/entities', methods=['GET'])
@login_required
def get_entities():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM entities ORDER BY name').fetchall()
    result = []
    for r in rows:
        e = dict(r)
        e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
        result.append(e)
    return jsonify(result)


@entities_bp.route('/api/entities', methods=['POST'])
@login_required
@csrf_protect
def add_entity():
    d = request.json
    if not d or not d.get('name') or not validate_string(d.get('name'), 200):
        return jsonify({'error': 'Nom requis'}), 400
    if not validate_number(d.get('gross_assets')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeurs numériques invalides'}), 400
    today = datetime.now().strftime('%Y-%m-%d')
    gross = d.get('gross_assets', 0)
    debt  = d.get('debt', 0)
    with get_db() as conn:
        cur = conn.execute(
            '''INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment)
               VALUES (?,?,?,?,?,?)''',
            (d['name'], d.get('type'), d.get('valuation_mode'), gross, debt, d.get('comment'))
        )
        conn.execute(
            '''INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt)
               VALUES (?,?,?,?)''',
            (d['name'], today, gross, debt)
        )
        row = conn.execute('SELECT * FROM entities WHERE id=?', (cur.lastrowid,)).fetchone()
    e = dict(row)
    e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
    e['snapshot_date'] = today
    return jsonify(e), 201


@entities_bp.route('/api/entities/<int:eid>', methods=['PUT'])
@login_required
@csrf_protect
def update_entity(eid):
    d = request.json
    if not d or not d.get('name'):
        return jsonify({'error': 'Nom requis'}), 400
    if not validate_number(d.get('gross_assets')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeurs numériques invalides'}), 400
    today = datetime.now().strftime('%Y-%m-%d')
    gross = d.get('gross_assets', 0)
    debt  = d.get('debt', 0)
    with get_db() as conn:
        conn.execute(
            '''UPDATE entities SET name=?, type=?, valuation_mode=?,
               gross_assets=?, debt=?, comment=? WHERE id=?''',
            (d['name'], d.get('type'), d.get('valuation_mode'), gross, debt, d.get('comment'), eid)
        )
        conn.execute(
            '''INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt)
               VALUES (?,?,?,?)''',
            (d['name'], today, gross, debt)
        )
        row = conn.execute('SELECT * FROM entities WHERE id=?', (eid,)).fetchone()
    e = dict(row)
    e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
    e['snapshot_date'] = today
    return jsonify(e)


@entities_bp.route('/api/entities/<int:eid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_entity(eid):
    with get_db() as conn:
        name = conn.execute('SELECT name FROM entities WHERE id=?', (eid,)).fetchone()
        if name:
            conn.execute('DELETE FROM entity_snapshots WHERE entity_name=?', (name['name'],))
        conn.execute('DELETE FROM entities WHERE id=?', (eid,))
    return '', 204


@entities_bp.route('/api/entity-snapshots')
@login_required
def get_entity_snapshots():
    entity_name = request.args.get('entity')
    with get_db() as conn:
        if entity_name:
            rows = conn.execute(
                'SELECT * FROM entity_snapshots WHERE entity_name=? ORDER BY date DESC',
                (entity_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM entity_snapshots ORDER BY entity_name, date DESC'
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@entities_bp.route('/api/entity-snapshots/<int:sid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_entity_snapshot(sid):
    with get_db() as conn:
        conn.execute('DELETE FROM entity_snapshots WHERE id=?', (sid,))
    return '', 204
