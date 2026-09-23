from flask import Blueprint, jsonify, request
from models import get_db, validate_date, validate_number, validate_string, parse_number
from auth import login_required, csrf_protect
from services.montants import centimes, ligne_en_euros

flux_bp = Blueprint('flux', __name__)


@flux_bp.route('/api/flux', methods=['GET'])
@login_required
def get_flux():
    date_from = request.args.get('date_from')
    date_to   = request.args.get('date_to')
    limit     = request.args.get('limit', type=int)
    offset    = request.args.get('offset', 0, type=int)
    with get_db() as conn:
        if date_from and date_to:
            query = 'SELECT * FROM flux WHERE date >= ? AND date <= ? ORDER BY date DESC'
            params = [date_from, date_to]
        else:
            query = 'SELECT * FROM flux ORDER BY date DESC'
            params = []
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params += [limit, offset]
        rows = conn.execute(query, params).fetchall()
    return jsonify([ligne_en_euros('flux', r) for r in rows])


def _erreur(d):
    """Message d'erreur d'un flux, ou None. Une seule validation pour la
    creation et la modification : le PUT en omettait la moitie, et un montant
    vide ou un titulaire absent y finissait en erreur 500."""
    if not d or not validate_date(d.get('date')):
        return 'Date invalide'
    if not d.get('owner') or not validate_string(d.get('owner'), 80):
        return 'Propriétaire requis'
    if d.get('amount') is None or not validate_number(d.get('amount'), allow_negative=True):
        return 'Montant invalide'
    for champ, lib, n in (('notes', 'Notes', 2000), ('establishment', 'Établissement', 120),
                          ('envelope', 'Enveloppe', 80), ('type', 'Type', 40), ('category', 'Catégorie', 80)):
        if not validate_string(d.get(champ), n):
            return f'{lib} trop long ({n} car. max)'
    return None


def _valeurs(d):
    return (d['date'], d['owner'], d.get('envelope'), d.get('establishment') or None,
            d.get('type'), centimes(parse_number(d['amount'])), d.get('notes'), d.get('category'))


@flux_bp.route('/api/flux', methods=['POST'])
@login_required
@csrf_protect
def add_flux():
    d = request.json
    if (err := _erreur(d)):
        return jsonify({'error': err}), 400
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO flux (date, owner, envelope, establishment, type, amount, notes, category) '
            'VALUES (?,?,?,?,?,?,?,?)', _valeurs(d))
        row = conn.execute('SELECT * FROM flux WHERE id=?', (cur.lastrowid,)).fetchone()
    return jsonify(ligne_en_euros('flux', row)), 201


@flux_bp.route('/api/flux/<int:fid>', methods=['PUT'])
@login_required
@csrf_protect
def update_flux(fid):
    d = request.json
    if (err := _erreur(d)):
        return jsonify({'error': err}), 400
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM flux WHERE id=?', (fid,)).fetchone():
            return jsonify({'error': 'Flux introuvable'}), 404
        conn.execute(
            'UPDATE flux SET date=?, owner=?, envelope=?, establishment=?, type=?, amount=?, '
            'notes=?, category=? WHERE id=?', (*_valeurs(d), fid))
        row = conn.execute('SELECT * FROM flux WHERE id=?', (fid,)).fetchone()
    return jsonify(ligne_en_euros('flux', row))


@flux_bp.route('/api/flux/<int:fid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_flux(fid):
    with get_db() as conn:
        conn.execute('DELETE FROM flux WHERE id=?', (fid,))
    return '', 204
