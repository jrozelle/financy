from flask import Blueprint, jsonify, request
from models import (get_db, compute_position, get_entity_map, get_holdings_map, holdings_a_date,
                    load_referential, snapshot_holdings_to_date,
                    validate_date, validate_number, validate_string,
                    validate_pct, parse_number, LIQUIDITY_ORDER)
from auth import login_required, csrf_protect
from services.montants import centimes, ligne_en_euros, lignes_en_euros

positions_bp = Blueprint('positions', __name__)

# Longueurs maximales des champs texte d'une position.
_LONGUEURS = (('owner', 100, 'Propriétaire'), ('category', 100, 'Catégorie'),
              ('envelope', 100, 'Enveloppe'), ('establishment', 200, 'Établissement'),
              ('label', 200, 'Libellé'), ('entity', 200, 'Entité'), ('notes', 2000, 'Notes'))


def _erreur_position(conn, d):
    """Message d'erreur (400) d'une position saisie, ou None.

    La date se verifie a part : snapshot_update ne la porte pas dans la
    position. Une valeur hors format levait une 500 a l'ecriture ; une
    liquidite inconnue s'enregistrait et faussait les echeances de
    disponibilite.
    """
    if not isinstance(d.get('owner'), str) or not d['owner'].strip():
        return 'Propriétaire requis'
    if not isinstance(d.get('category'), str) or not d['category'].strip():
        return 'Catégorie requise'
    for champ, n, nom in _LONGUEURS:
        if not validate_string(d.get(champ), n):
            return f'{nom} invalide ou trop long ({n} car. max)'
    if not validate_number(d.get('value')) or not validate_number(d.get('debt')):
        return 'Valeur / dette invalide'
    if not validate_pct(d.get('ownership_pct')) or not validate_pct(d.get('debt_pct')):
        return '% propriété ou dette invalide (0-100)'
    # Stockee comme les autres parts : une fraction de 0 a 1 (le front divise par 100).
    if not validate_pct(d.get('mobilizable_pct_override')):
        return 'Part mobilisable invalide (0-100 %)'
    liq = d.get('liquidity_override')
    if liq not in (None, ''):
        permises = set(LIQUIDITY_ORDER) | set(load_referential(conn).get('liquidity_order') or [])
        if liq not in permises:
            return f'Liquidité inconnue (attendu : {", ".join(LIQUIDITY_ORDER)})'
    return None


def _pct_stocke(v):
    """Une part validee par validate_pct, bornee a [0, 1] (marge d'arrondi)."""
    n = parse_number(v)
    return None if n is None else max(0.0, min(n, 1.0))


@positions_bp.route('/api/dates')
@login_required
def get_dates():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date DESC'
        ).fetchall()
    return jsonify([r['date'] for r in rows])


@positions_bp.route('/api/positions', methods=['GET'])
@login_required
def get_positions():
    date   = request.args.get('date')
    limit  = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    with get_db() as conn:
        if date:
            query = 'SELECT * FROM positions WHERE date=? ORDER BY owner, category'
            params = [date]
        else:
            query = 'SELECT * FROM positions ORDER BY date DESC, owner, category'
            params = []
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params += [limit, offset]
        rows = lignes_en_euros('positions', conn.execute(query, params))
        entity_map   = get_entity_map(conn, date)
        ref          = load_referential(conn)
        holdings_map = holdings_a_date(conn, [r['id'] for r in rows], date)
    return jsonify([compute_position(r, entity_map, ref, holdings_map) for r in rows])


@positions_bp.route('/api/positions', methods=['POST'])
@login_required
@csrf_protect
def add_position():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide (format AAAA-MM-JJ attendu)'}), 400
    with get_db() as conn:
        err = _erreur_position(conn, d)
        if err:
            return jsonify({'error': err}), 400
        entity = d.get('entity')
        stored_value = 0 if entity else centimes(parse_number(d.get('value'), 0))
        stored_debt  = 0 if entity else centimes(parse_number(d.get('debt'), 0))
        mob_override = _pct_stocke(d.get('mobilizable_pct_override'))
        liq_override = d.get('liquidity_override') or None
        cur = conn.execute(
            '''INSERT INTO positions
               (date, owner, category, envelope, establishment, value, debt,
                label, notes, entity, ownership_pct, debt_pct, mobilizable_pct_override, liquidity_override)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (d['date'], d['owner'], d['category'],
             d.get('envelope'), d.get('establishment'),
             stored_value, stored_debt,
             d.get('label'), d.get('notes'), entity,
             parse_number(d.get('ownership_pct'), 1.0),
             parse_number(d.get('debt_pct'), 1.0), mob_override, liq_override)
        )
        row          = conn.execute('SELECT * FROM positions WHERE id=?', (cur.lastrowid,)).fetchone()
        entity_map   = get_entity_map(conn)
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [row['id']])
    return jsonify(compute_position(ligne_en_euros('positions', row), entity_map, ref, holdings_map)), 201


@positions_bp.route('/api/positions/<int:pid>', methods=['PUT'])
@login_required
@csrf_protect
def update_position(pid):
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide'}), 400
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM positions WHERE id=?', (pid,)).fetchone():
            return jsonify({'error': 'Position introuvable'}), 404
        err = _erreur_position(conn, d)
        if err:
            return jsonify({'error': err}), 400
        entity = d.get('entity')
        stored_value = 0 if entity else centimes(parse_number(d.get('value'), 0))
        stored_debt  = 0 if entity else centimes(parse_number(d.get('debt'), 0))
        mob_override = _pct_stocke(d.get('mobilizable_pct_override'))
        liq_override = d.get('liquidity_override') or None
        conn.execute(
            '''UPDATE positions SET
               date=?, owner=?, category=?, envelope=?, establishment=?,
               value=?, debt=?, label=?, notes=?, entity=?, ownership_pct=?, debt_pct=?,
               mobilizable_pct_override=?, liquidity_override=?
               WHERE id=?''',
            (d['date'], d['owner'], d['category'],
             d.get('envelope'), d.get('establishment'),
             stored_value, stored_debt,
             d.get('label'), d.get('notes'), entity,
             parse_number(d.get('ownership_pct'), 1.0),
             parse_number(d.get('debt_pct'), 1.0), mob_override, liq_override, pid)
        )
        row          = conn.execute('SELECT * FROM positions WHERE id=?', (pid,)).fetchone()
        entity_map   = get_entity_map(conn)
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [row['id']])
    return jsonify(compute_position(ligne_en_euros('positions', row), entity_map, ref, holdings_map))


@positions_bp.route('/api/positions/<int:pid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_position(pid):
    with get_db() as conn:
        # ON DELETE CASCADE inactif (PRAGMA foreign_keys off) -> purge explicite
        # des holdings pour ne pas laisser d'orphelins.
        conn.execute('DELETE FROM holdings WHERE position_id=?', (pid,))
        conn.execute('DELETE FROM positions WHERE id=?', (pid,))
    return '', 204


@positions_bp.route('/api/positions/<int:pid>/snapshot-update', methods=['POST'])
@login_required
@csrf_protect
def snapshot_update(pid):
    d           = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({'error': 'source_date, target_date et position requis'}), 400
    source_date = d.get('source_date')
    target_date = d.get('target_date')
    new_values  = d.get('position')

    if not source_date or not target_date or not isinstance(new_values, dict) or not new_values:
        return jsonify({'error': 'source_date, target_date et position requis'}), 400
    if not validate_date(source_date) or not validate_date(target_date):
        return jsonify({'error': 'Dates invalides'}), 400
    if source_date == target_date:
        return jsonify({'error': 'Les dates source et cible doivent être différentes'}), 400

    from services.snapshot import duplicate_position

    with get_db() as conn:
        err = _erreur_position(conn, new_values)
        if err:
            return jsonify({'error': err}), 400
        entity_map = get_entity_map(conn, target_date)
        ref        = load_referential(conn)

        conn.execute('BEGIN IMMEDIATE')

        source_rows = conn.execute(
            'SELECT * FROM positions WHERE date=?', (source_date,)
        ).fetchall()

        if not source_rows:
            return jsonify({'error': f'Aucune position à la date {source_date}'}), 404
        if not any(r['id'] == pid for r in source_rows):
            return jsonify({'error': f'Position {pid} absente de l\u2019arrêté du {source_date}'}), 404

        # ON DELETE CASCADE est inerte : les lignes de titres de l'arrete
        # remplace restaient orphelines. Meme purge que la duplication.
        conn.execute('DELETE FROM holdings WHERE position_id IN '
                     '(SELECT id FROM positions WHERE date=?)', (target_date,))
        conn.execute('DELETE FROM holdings_snapshots WHERE snapshot_date=?', (target_date,))
        conn.execute('DELETE FROM positions WHERE date=?', (target_date,))

        created = []
        for row in source_rows:
            if row['id'] == pid:
                entity = new_values.get('entity')
                override = {
                    'owner': new_values['owner'],
                    'category': new_values['category'],
                    'envelope': new_values.get('envelope'),
                    'establishment': new_values.get('establishment'),
                    'value': 0 if entity else parse_number(new_values.get('value'), 0),
                    'debt': 0 if entity else parse_number(new_values.get('debt'), 0),
                    'label': new_values.get('label'),
                    'notes': new_values.get('notes'),
                    'entity': entity,
                    'ownership_pct': parse_number(new_values.get('ownership_pct'), 1.0),
                    'debt_pct': parse_number(new_values.get('debt_pct'), 1.0),
                    'mobilizable_pct_override': _pct_stocke(new_values.get('mobilizable_pct_override')),
                    'liquidity_override': new_values.get('liquidity_override') or None,
                }
                new_id = duplicate_position(conn, row, target_date, value_override=override)
            else:
                new_id = duplicate_position(conn, row, target_date)
            new_row = conn.execute('SELECT * FROM positions WHERE id=?', (new_id,)).fetchone()
            holdings_map = get_holdings_map(conn, [new_id])
            created.append(compute_position(ligne_en_euros('positions', new_row), entity_map, ref, holdings_map))

        snapshot_holdings_to_date(conn, target_date)

    return jsonify({'target_date': target_date, 'count': len(created)}), 201
