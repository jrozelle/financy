from flask import Blueprint, jsonify, request
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential, snapshot_holdings_to_date,
                    validate_date, validate_number, validate_string, validate_pct)
from auth import login_required, csrf_protect

positions_bp = Blueprint('positions', __name__)


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
        rows = conn.execute(query, params).fetchall()
        entity_map   = get_entity_map(conn, date)
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
    return jsonify([compute_position(dict(r), entity_map, ref, holdings_map) for r in rows])


@positions_bp.route('/api/positions', methods=['POST'])
@login_required
@csrf_protect
def add_position():
    d = request.json
    if not d or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide (format AAAA-MM-JJ attendu)'}), 400
    if not validate_string(d.get('owner'), 100) or not d.get('owner'):
        return jsonify({'error': 'Propriétaire requis'}), 400
    if not validate_string(d.get('category'), 100) or not d.get('category'):
        return jsonify({'error': 'Catégorie requise'}), 400
    if not validate_number(d.get('value')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeur / dette invalide'}), 400
    if not validate_pct(d.get('ownership_pct')) or not validate_pct(d.get('debt_pct')):
        return jsonify({'error': '% propriété ou dette invalide (0-100)'}), 400
    if not validate_string(d.get('notes'), 2000):
        return jsonify({'error': 'Notes trop longues (2000 car. max)'}), 400
    with get_db() as conn:
        entity = d.get('entity')
        stored_value = 0 if entity else d.get('value', 0)
        stored_debt  = 0 if entity else d.get('debt', 0)
        mob_override = d.get('mobilizable_pct_override')
        if mob_override is not None:
            mob_override = float(mob_override)
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
             d.get('ownership_pct', 1.0), d.get('debt_pct', 1.0), mob_override, liq_override)
        )
        row          = conn.execute('SELECT * FROM positions WHERE id=?', (cur.lastrowid,)).fetchone()
        entity_map   = get_entity_map(conn)
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [row['id']])
    return jsonify(compute_position(dict(row), entity_map, ref, holdings_map)), 201


@positions_bp.route('/api/positions/<int:pid>', methods=['PUT'])
@login_required
@csrf_protect
def update_position(pid):
    d = request.json
    if not d or not validate_date(d.get('date')):
        return jsonify({'error': 'Date invalide'}), 400
    if not validate_number(d.get('value')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeur / dette invalide'}), 400
    if not validate_pct(d.get('ownership_pct')) or not validate_pct(d.get('debt_pct')):
        return jsonify({'error': '% invalide'}), 400
    if not validate_string(d.get('notes'), 2000):
        return jsonify({'error': 'Notes trop longues (2000 car. max)'}), 400
    with get_db() as conn:
        entity = d.get('entity')
        stored_value = 0 if entity else d.get('value', 0)
        stored_debt  = 0 if entity else d.get('debt', 0)
        mob_override = d.get('mobilizable_pct_override')
        if mob_override is not None:
            mob_override = float(mob_override)
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
             d.get('ownership_pct', 1.0), d.get('debt_pct', 1.0), mob_override, liq_override, pid)
        )
        row          = conn.execute('SELECT * FROM positions WHERE id=?', (pid,)).fetchone()
        entity_map   = get_entity_map(conn)
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [row['id']])
    return jsonify(compute_position(dict(row), entity_map, ref, holdings_map))


@positions_bp.route('/api/positions/<int:pid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_position(pid):
    with get_db() as conn:
        conn.execute('DELETE FROM positions WHERE id=?', (pid,))
    return '', 204


@positions_bp.route('/api/positions/<int:pid>/snapshot-update', methods=['POST'])
@login_required
@csrf_protect
def snapshot_update(pid):
    d           = request.json
    source_date = d.get('source_date')
    target_date = d.get('target_date')
    new_values  = d.get('position')

    if not source_date or not target_date or not new_values:
        return jsonify({'error': 'source_date, target_date et position requis'}), 400
    if not validate_date(source_date) or not validate_date(target_date):
        return jsonify({'error': 'Dates invalides'}), 400
    if source_date == target_date:
        return jsonify({'error': 'Les dates source et cible doivent être différentes'}), 400
    if not new_values.get('owner') or not new_values.get('category'):
        return jsonify({'error': 'Propriétaire et catégorie requis'}), 400
    if not validate_pct(new_values.get('ownership_pct')) or not validate_pct(new_values.get('debt_pct')):
        return jsonify({'error': '% propriété ou dette invalide'}), 400
    if not validate_string(new_values.get('notes'), 2000):
        return jsonify({'error': 'Notes trop longues'}), 400

    with get_db() as conn:
        entity_map = get_entity_map(conn, target_date)
        ref        = load_referential(conn)

        # Acquire write lock immediately to prevent race conditions
        conn.execute('BEGIN IMMEDIATE')

        source_rows = conn.execute(
            'SELECT * FROM positions WHERE date=?', (source_date,)
        ).fetchall()

        if not source_rows:
            return jsonify({'error': f'Aucune position à la date {source_date}'}), 404

        conn.execute('DELETE FROM positions WHERE date=?', (target_date,))

        created = []
        for row in source_rows:
            r = dict(row)
            if r['id'] == pid:
                entity = new_values.get('entity')
                stored_value = 0 if entity else new_values.get('value', 0)
                stored_debt  = 0 if entity else new_values.get('debt', 0)
                cur = conn.execute(
                    '''INSERT INTO positions
                       (date, owner, category, envelope, establishment,
                        value, debt, notes, entity, ownership_pct, debt_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (target_date,
                     new_values['owner'], new_values['category'],
                     new_values.get('envelope'), new_values.get('establishment'),
                     stored_value, stored_debt,
                     new_values.get('notes'), entity,
                     new_values.get('ownership_pct', 1.0),
                     new_values.get('debt_pct', 1.0))
                )
            else:
                cur = conn.execute(
                    '''INSERT INTO positions
                       (date, owner, category, envelope, establishment,
                        value, debt, notes, entity, ownership_pct, debt_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (target_date,
                     r['owner'], r['category'], r['envelope'], r['establishment'],
                     r['value'], r['debt'], r['notes'], r['entity'],
                     r['ownership_pct'], r['debt_pct'])
                )
            new_row = conn.execute('SELECT * FROM positions WHERE id=?', (cur.lastrowid,)).fetchone()
            holdings_map = get_holdings_map(conn, [new_row['id']])
            created.append(compute_position(dict(new_row), entity_map, ref, holdings_map))

        snapshot_holdings_to_date(conn, target_date)

    return jsonify({'target_date': target_date, 'count': len(created)}), 201
