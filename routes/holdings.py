from flask import Blueprint, jsonify, request
from models import (get_db, validate_isin, validate_number, validate_string,
                    validate_date, snapshot_holdings_to_date)
from auth import login_required, csrf_protect

holdings_bp = Blueprint('holdings', __name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _normalize_isin(raw):
    """Normalise un ISIN (trim + upper). Retourne None si invalide."""
    if not raw or not isinstance(raw, str):
        return None
    isin = raw.strip().upper()
    return isin if validate_isin(isin) else None


def _upsert_security(conn, isin, name=None, ticker=None, currency='EUR',
                     asset_class=None, is_priceable=None):
    """Cree la security si elle n'existe pas, met a jour les champs fournis."""
    row = conn.execute('SELECT * FROM securities WHERE isin=?', (isin,)).fetchone()
    is_pseudo = isin.startswith(('FONDS_EUROS_', 'CUSTOM_'))
    if row is None:
        conn.execute(
            '''INSERT INTO securities
               (isin, name, ticker, currency, asset_class, is_priceable, data_source)
               VALUES (?,?,?,?,?,?,?)''',
            (isin, name, ticker, currency or 'EUR',
             asset_class or ('fonds_euros' if isin.startswith('FONDS_EUROS_') else 'autre'),
             0 if is_pseudo else (1 if is_priceable is None else int(bool(is_priceable))),
             'manual')
        )
        return
    # Update partiel des champs fournis
    updates, params = [], []
    for col, val in [('name', name), ('ticker', ticker), ('currency', currency),
                     ('asset_class', asset_class)]:
        if val is not None:
            updates.append(f'{col}=?')
            params.append(val)
    if is_priceable is not None:
        updates.append('is_priceable=?')
        params.append(int(bool(is_priceable)))
    if updates:
        updates.append("updated_at=CURRENT_TIMESTAMP")
        params.append(isin)
        conn.execute(
            f'UPDATE securities SET {", ".join(updates)} WHERE isin=?', params
        )


def _validate_holding_payload(d):
    """Renvoie (isin_normalise, error_message_ou_None)."""
    isin = _normalize_isin(d.get('isin'))
    if not isin:
        return None, 'ISIN invalide'
    if not validate_number(d.get('quantity')):
        return None, 'Quantite invalide'
    try:
        if float(d.get('quantity') or 0) <= 0:
            return None, 'Quantite doit etre > 0'
    except (ValueError, TypeError):
        return None, 'Quantite invalide'
    if d.get('cost_basis') is not None and not validate_number(d.get('cost_basis')):
        return None, 'Prix de revient invalide'
    if d.get('market_value') is not None and not validate_number(d.get('market_value')):
        return None, 'Valorisation invalide'
    if d.get('as_of_date') and not validate_date(d.get('as_of_date')):
        return None, 'Date invalide (format AAAA-MM-JJ attendu)'
    if not validate_string(d.get('name'), 200):
        return None, 'Nom trop long (200 car. max)'
    if not validate_string(d.get('ticker'), 50):
        return None, 'Ticker trop long (50 car. max)'
    return isin, None


def _holding_row_to_dict(row):
    """Joint holdings + securities pour l'affichage."""
    return {
        'id':              row['id'],
        'position_id':     row['position_id'],
        'isin':            row['isin'],
        'quantity':        row['quantity'],
        'cost_basis':      row['cost_basis'],
        'market_value':    row['market_value'],
        'as_of_date':      row['as_of_date'],
        'name':            row['sec_name'],
        'ticker':          row['sec_ticker'],
        'currency':        row['sec_currency'],
        'asset_class':     row['sec_asset_class'],
        'is_priceable':    bool(row['sec_is_priceable']) if row['sec_is_priceable'] is not None else True,
        'last_price':      row['sec_last_price'],
        'last_price_date': row['sec_last_price_date'],
    }


def _fetch_holdings(conn, position_id):
    rows = conn.execute(
        '''SELECT h.*,
                  s.name           AS sec_name,
                  s.ticker         AS sec_ticker,
                  s.currency       AS sec_currency,
                  s.asset_class    AS sec_asset_class,
                  s.is_priceable   AS sec_is_priceable,
                  s.last_price     AS sec_last_price,
                  s.last_price_date AS sec_last_price_date
           FROM holdings h
           LEFT JOIN securities s ON s.isin = h.isin
           WHERE h.position_id = ?
           ORDER BY h.id''',
        (position_id,)
    ).fetchall()
    return [_holding_row_to_dict(r) for r in rows]


def _position_exists(conn, position_id):
    return conn.execute(
        'SELECT 1 FROM positions WHERE id=?', (position_id,)
    ).fetchone() is not None


# ─── Routes holdings ─────────────────────────────────────────────────────────

@holdings_bp.route('/api/positions/<int:position_id>/holdings', methods=['GET'])
@login_required
def get_holdings(position_id):
    with get_db() as conn:
        if not _position_exists(conn, position_id):
            return jsonify({'error': 'Position introuvable'}), 404
        holdings = _fetch_holdings(conn, position_id)
    total_mv = sum(h['market_value'] or 0 for h in holdings)
    total_cost = sum(h['cost_basis'] or 0 for h in holdings)
    return jsonify({
        'position_id':         position_id,
        'holdings':            holdings,
        'total_market_value':  total_mv,
        'total_cost_basis':    total_cost,
    })


@holdings_bp.route('/api/positions/<int:position_id>/holdings', methods=['POST'])
@login_required
@csrf_protect
def add_holding(position_id):
    """Ajoute une ligne unique a une position."""
    d = request.json or {}
    isin, err = _validate_holding_payload(d)
    if err:
        return jsonify({'error': err}), 400
    with get_db() as conn:
        if not _position_exists(conn, position_id):
            return jsonify({'error': 'Position introuvable'}), 404
        _upsert_security(
            conn, isin,
            name=d.get('name'), ticker=d.get('ticker'),
            currency=d.get('currency'),
            asset_class=d.get('asset_class'),
            is_priceable=d.get('is_priceable'),
        )
        cur = conn.execute(
            '''INSERT INTO holdings
               (position_id, isin, quantity, cost_basis, market_value, as_of_date)
               VALUES (?,?,?,?,?,?)''',
            (position_id, isin,
             float(d['quantity']),
             float(d['cost_basis']) if d.get('cost_basis') is not None else None,
             float(d['market_value']) if d.get('market_value') is not None else None,
             d.get('as_of_date'))
        )
        holdings = _fetch_holdings(conn, position_id)
    created = next((h for h in holdings if h['id'] == cur.lastrowid), None)
    return jsonify(created), 201


@holdings_bp.route('/api/positions/<int:position_id>/holdings', methods=['PUT'])
@login_required
@csrf_protect
def replace_holdings(position_id):
    """Remplace integralement les holdings d'une position (usage : import PDF, modale)."""
    d = request.json or {}
    items = d.get('holdings')
    if not isinstance(items, list):
        return jsonify({'error': 'Format attendu : {"holdings": [...]}'}), 400
    if len(items) > 500:
        return jsonify({'error': 'Trop de lignes (500 max)'}), 400

    validated = []
    for idx, item in enumerate(items):
        isin, err = _validate_holding_payload(item)
        if err:
            return jsonify({'error': f'Ligne {idx + 1} : {err}'}), 400
        validated.append((isin, item))

    with get_db() as conn:
        if not _position_exists(conn, position_id):
            return jsonify({'error': 'Position introuvable'}), 404
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM holdings WHERE position_id=?', (position_id,))
        for isin, item in validated:
            _upsert_security(
                conn, isin,
                name=item.get('name'), ticker=item.get('ticker'),
                currency=item.get('currency'),
                asset_class=item.get('asset_class'),
                is_priceable=item.get('is_priceable'),
            )
            conn.execute(
                '''INSERT INTO holdings
                   (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                   VALUES (?,?,?,?,?,?)''',
                (position_id, isin,
                 float(item['quantity']),
                 float(item['cost_basis']) if item.get('cost_basis') is not None else None,
                 float(item['market_value']) if item.get('market_value') is not None else None,
                 item.get('as_of_date'))
            )
        holdings = _fetch_holdings(conn, position_id)
    return jsonify({'position_id': position_id, 'holdings': holdings})


@holdings_bp.route('/api/holdings/<int:holding_id>', methods=['PATCH'])
@login_required
@csrf_protect
def update_holding(holding_id):
    """Met a jour une ligne (quantite, cost_basis, market_value, as_of_date)."""
    d = request.json or {}
    with get_db() as conn:
        row = conn.execute('SELECT * FROM holdings WHERE id=?', (holding_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Ligne introuvable'}), 404

        updates, params = [], []
        if 'quantity' in d:
            if not validate_number(d['quantity']) or float(d['quantity']) <= 0:
                return jsonify({'error': 'Quantite invalide'}), 400
            updates.append('quantity=?'); params.append(float(d['quantity']))
        if 'cost_basis' in d:
            if d['cost_basis'] is not None and not validate_number(d['cost_basis']):
                return jsonify({'error': 'Prix de revient invalide'}), 400
            updates.append('cost_basis=?')
            params.append(float(d['cost_basis']) if d['cost_basis'] is not None else None)
        if 'market_value' in d:
            if d['market_value'] is not None and not validate_number(d['market_value']):
                return jsonify({'error': 'Valorisation invalide'}), 400
            updates.append('market_value=?')
            params.append(float(d['market_value']) if d['market_value'] is not None else None)
        if 'as_of_date' in d:
            if d['as_of_date'] and not validate_date(d['as_of_date']):
                return jsonify({'error': 'Date invalide'}), 400
            updates.append('as_of_date=?'); params.append(d['as_of_date'])

        if not updates:
            return jsonify({'error': 'Aucun champ a mettre a jour'}), 400

        params.append(holding_id)
        conn.execute(f'UPDATE holdings SET {", ".join(updates)} WHERE id=?', params)
        holdings = _fetch_holdings(conn, row['position_id'])
    updated = next((h for h in holdings if h['id'] == holding_id), None)
    return jsonify(updated)


@holdings_bp.route('/api/holdings/<int:holding_id>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_holding(holding_id):
    with get_db() as conn:
        cur = conn.execute('DELETE FROM holdings WHERE id=?', (holding_id,))
        if cur.rowcount == 0:
            return jsonify({'error': 'Ligne introuvable'}), 404
    return '', 204


# ─── Snapshot de l'état actuel des holdings à une date ──────────────────────

@holdings_bp.route('/api/holdings/snapshot', methods=['POST'])
@login_required
@csrf_protect
def holdings_snapshot():
    """Ecrit l'etat courant de toutes les holdings dans holdings_snapshots.

    Appele par le frontend apres une duplication de snapshot pour figer la
    granularite holdings a la nouvelle date.
    """
    d = request.json or {}
    snap_date = d.get('date')
    if not validate_date(snap_date):
        return jsonify({'error': 'Date invalide'}), 400
    with get_db() as conn:
        n = snapshot_holdings_to_date(conn, snap_date)
    return jsonify({'ok': True, 'snapshot_date': snap_date, 'count': n})


# ─── Routes securities ───────────────────────────────────────────────────────

@holdings_bp.route('/api/securities', methods=['GET'])
@login_required
def search_securities():
    """Recherche pour auto-completion (ISIN ou nom)."""
    q = (request.args.get('q') or '').strip()
    limit = min(request.args.get('limit', 20, type=int), 100)
    with get_db() as conn:
        if q:
            pattern = f'%{q.upper()}%'
            rows = conn.execute(
                '''SELECT * FROM securities
                   WHERE UPPER(isin) LIKE ? OR UPPER(name) LIKE ? OR UPPER(ticker) LIKE ?
                   ORDER BY name LIMIT ?''',
                (pattern, pattern, pattern, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM securities ORDER BY name LIMIT ?', (limit,)
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@holdings_bp.route('/api/securities/<isin>', methods=['PATCH'])
@login_required
@csrf_protect
def update_security(isin):
    """Met a jour les metadonnees d'une security (name, ticker, is_priceable)."""
    isin = (isin or '').strip().upper()
    if not validate_isin(isin):
        return jsonify({'error': 'ISIN invalide'}), 400
    d = request.json or {}
    with get_db() as conn:
        row = conn.execute('SELECT * FROM securities WHERE isin=?', (isin,)).fetchone()
        if not row:
            return jsonify({'error': 'Security introuvable'}), 404

        updates, params = [], []
        for field, validator in [
            ('name', lambda v: validate_string(v, 200)),
            ('ticker', lambda v: validate_string(v, 50)),
            ('currency', lambda v: validate_string(v, 10)),
            ('asset_class', lambda v: validate_string(v, 50)),
        ]:
            if field in d:
                if not validator(d[field]):
                    return jsonify({'error': f'{field} invalide'}), 400
                updates.append(f'{field}=?'); params.append(d[field])
        if 'is_priceable' in d:
            updates.append('is_priceable=?')
            params.append(int(bool(d['is_priceable'])))

        if not updates:
            return jsonify({'error': 'Aucun champ a mettre a jour'}), 400

        updates.append('updated_at=CURRENT_TIMESTAMP')
        params.append(isin)
        conn.execute(
            f'UPDATE securities SET {", ".join(updates)} WHERE isin=?', params
        )
        row = conn.execute('SELECT * FROM securities WHERE isin=?', (isin,)).fetchone()
    return jsonify(dict(row))
