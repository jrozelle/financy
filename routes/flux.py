from flask import Blueprint, jsonify, request
from models import get_db, validate_date, validate_number, validate_string
from auth import login_required, csrf_protect

flux_bp = Blueprint('flux', __name__)


@flux_bp.route('/api/flux', methods=['GET'])
@login_required
def get_flux():
    date_from = request.args.get('date_from')
    date_to   = request.args.get('date_to')
    with get_db() as conn:
        if date_from and date_to:
            rows = conn.execute(
                'SELECT * FROM flux WHERE date >= ? AND date <= ? ORDER BY date DESC',
                (date_from, date_to)
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM flux ORDER BY date DESC').fetchall()
    return jsonify([dict(r) for r in rows])


@flux_bp.route('/api/flux', methods=['POST'])
@login_required
@csrf_protect
def add_flux():
    d = request.json
    if not d or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide'}), 400
    if not d.get('owner'):
        return jsonify({'error': 'Propriétaire requis'}), 400
    if not validate_number(d.get('amount'), allow_negative=True) or d.get('amount') is None:
        return jsonify({'error': 'Montant invalide'}), 400
    if not validate_string(d.get('notes'), 2000):
        return jsonify({'error': 'Notes trop longues (2000 car. max)'}), 400
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO flux (date, owner, envelope, type, amount, notes, category) VALUES (?,?,?,?,?,?,?)',
            (d['date'], d['owner'], d.get('envelope'), d.get('type'),
             d['amount'], d.get('notes'), d.get('category'))
        )
        row = conn.execute('SELECT * FROM flux WHERE id=?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@flux_bp.route('/api/flux/<int:fid>', methods=['PUT'])
@login_required
@csrf_protect
def update_flux(fid):
    d = request.json
    if not d or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide'}), 400
    if not validate_number(d.get('amount'), allow_negative=True):
        return jsonify({'error': 'Montant invalide'}), 400
    if not validate_string(d.get('notes'), 2000):
        return jsonify({'error': 'Notes trop longues (2000 car. max)'}), 400
    with get_db() as conn:
        conn.execute(
            'UPDATE flux SET date=?, owner=?, envelope=?, type=?, amount=?, notes=?, category=? WHERE id=?',
            (d['date'], d['owner'], d.get('envelope'), d.get('type'),
             d['amount'], d.get('notes'), d.get('category'), fid)
        )
        row = conn.execute('SELECT * FROM flux WHERE id=?', (fid,)).fetchone()
    return jsonify(dict(row))


@flux_bp.route('/api/flux/<int:fid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_flux(fid):
    with get_db() as conn:
        conn.execute('DELETE FROM flux WHERE id=?', (fid,))
    return '', 204
