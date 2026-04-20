from flask import Blueprint, jsonify, request
from models import (get_db, validate_isin, validate_number, validate_string,
                    validate_date, snapshot_holdings_to_date)
from services.securities import upsert_security as _upsert_security
from auth import login_required, csrf_protect

holdings_bp = Blueprint('holdings', __name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_ASSET_CLASS_LABELS = {
    'etf': 'ETF', 'opcvm': 'OPCVM', 'scpi': 'SCPI', 'sci': 'SCI',
    'action': 'Action', 'fonds_euros': 'Fonds euros', 'cash': 'Cash',
    'obligation': 'Obligation', 'produit_structure': 'Produit structure',
    'autre': 'Autre',
}


def _asset_class_label(raw):
    if not raw:
        return 'Autre'
    return _ASSET_CLASS_LABELS.get(raw.lower(), raw.capitalize())


def _normalize_isin(raw):
    """Normalise un ISIN (trim + upper). Retourne None si invalide."""
    if not raw or not isinstance(raw, str):
        return None
    isin = raw.strip().upper()
    return isin if validate_isin(isin) else None


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
        'asset_class':     _asset_class_label(row['sec_asset_class']),
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
    """Remplace integralement les holdings d'une position (usage : import PDF/CSV, modale).

    Auto-split : si les holdings ont des asset_classes mixtes, les lignes sont
    reparties dans des positions compagnons par categorie.
    """
    from services.holdings_split import split_holdings_by_category
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

        # Upsert securities
        for isin, item in validated:
            _upsert_security(
                conn, isin,
                name=item.get('name'), ticker=item.get('ticker'),
                currency=item.get('currency'),
                asset_class=item.get('asset_class'),
                is_priceable=item.get('is_priceable'),
            )

        # Auto-split par categorie
        split_items = [{
            'isin': isin,
            'name': item.get('name'),
            'quantity': float(item['quantity']),
            'cost_basis': float(item['cost_basis']) if item.get('cost_basis') is not None else None,
            'market_value': float(item['market_value']) if item.get('market_value') is not None else None,
            'as_of_date': item.get('as_of_date'),
        } for isin, item in validated]

        touched, split_cats = split_holdings_by_category(conn, position_id, split_items)
        holdings = _fetch_holdings(conn, position_id)

    result = {'position_id': position_id, 'holdings': holdings}
    if split_cats:
        result['split_categories'] = split_cats
    return jsonify(result)


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


@holdings_bp.route('/api/holdings/consolidated', methods=['GET'])
@login_required
def get_consolidated():
    """Agregation cross-positions par ISIN.

    Retourne les lignes d'actifs cumulees sur l'ensemble des positions
    (optionnellement filtre par owner ou date), avec totaux valorisation,
    cout de revient, P&L, poids, et breakdowns par asset_class / devise /
    enveloppe.
    """
    owner = request.args.get('owner')
    date  = request.args.get('date')  # optionnel : date specifique du snapshot

    with get_db() as conn:
        # Si pas de date, on prend les positions de la derniere date disponible
        # (cross-owner ou filtre par owner)
        if not date:
            if owner:
                r = conn.execute(
                    'SELECT MAX(date) AS d FROM positions WHERE owner=?', (owner,)
                ).fetchone()
            else:
                r = conn.execute('SELECT MAX(date) AS d FROM positions').fetchone()
            date = r['d'] if r else None

        if not date:
            return jsonify({
                'snapshot_date': None, 'owner': owner, 'lines': [], 'totals': {},
                'breakdowns': {'asset_class': [], 'currency': [], 'envelope': []},
            })

        params = [date]
        where  = 'WHERE p.date=?'
        if owner:
            where += ' AND p.owner=?'
            params.append(owner)

        rows = conn.execute(
            f'''SELECT h.isin, h.quantity, h.cost_basis, h.market_value,
                       p.owner    AS pos_owner,
                       p.envelope AS pos_envelope,
                       p.category AS pos_category,
                       s.name, s.ticker, s.currency, s.asset_class, s.is_priceable,
                       s.last_price, s.last_price_date
                FROM holdings h
                JOIN positions p ON p.id = h.position_id
                LEFT JOIN securities s ON s.isin = h.isin
                {where}
                ORDER BY h.isin''',
            params
        ).fetchall()

    # Agregation par ISIN
    by_isin = {}
    for r in rows:
        isin = r['isin']
        q  = r['quantity'] or 0
        mv = r['market_value'] if r['market_value'] is not None else None
        # Valorisation effective : qty * last_price si is_priceable + last_price dispo,
        # sinon market_value saisi
        is_priceable = r['is_priceable']
        if is_priceable is None:
            is_priceable = 1
        if is_priceable and r['last_price'] is not None:
            effective_mv = q * r['last_price']
        else:
            effective_mv = mv or 0

        rec = by_isin.setdefault(isin, {
            'isin':            isin,
            'name':            r['name'],
            'ticker':          r['ticker'],
            'currency':        r['currency'] or 'EUR',
            'asset_class':     _asset_class_label(r['asset_class']),
            'is_priceable':    bool(is_priceable),
            'last_price':      r['last_price'],
            'last_price_date': r['last_price_date'],
            'quantity':        0,
            'cost_basis':      0,
            'market_value':    0,
            'positions_count': 0,
            'owners':          set(),
            'envelopes':       set(),
        })
        rec['quantity']         += q
        rec['cost_basis']       += r['cost_basis'] or 0
        rec['market_value']     += effective_mv
        rec['positions_count']  += 1
        if r['pos_owner']:    rec['owners'].add(r['pos_owner'])
        if r['pos_envelope']: rec['envelopes'].add(r['pos_envelope'])

    total_mv   = sum(v['market_value'] for v in by_isin.values())
    # P&L : ne compter que les lignes avec un vrai cost_basis
    has_cost_lines = [v for v in by_isin.values() if v['cost_basis']]
    total_cost = sum(v['cost_basis'] for v in has_cost_lines)
    total_mv_with_cost = sum(v['market_value'] for v in has_cost_lines)

    lines = []
    for v in by_isin.values():
        has_cost = v['cost_basis'] is not None and v['cost_basis'] > 0
        pnl = (v['market_value'] - v['cost_basis']) if has_cost else None
        pnl_pct = (pnl / v['cost_basis'] * 100) if (pnl is not None and v['cost_basis']) else None
        weight = (v['market_value'] / total_mv * 100) if total_mv > 0 else 0
        avg_cost = (v['cost_basis'] / v['quantity']) if v['quantity'] else None
        lines.append({
            **v,
            'owners':          sorted(v['owners']),
            'envelopes':       sorted(v['envelopes']),
            'avg_cost':        round(avg_cost, 4) if avg_cost is not None else None,
            'pnl':             round(pnl, 2) if pnl is not None else None,
            'pnl_pct':         round(pnl_pct, 2) if pnl_pct is not None else None,
            'weight_pct':      round(weight, 2),
            'market_value':    round(v['market_value'], 2),
            'cost_basis':      round(v['cost_basis'], 2),
        })
    lines.sort(key=lambda l: -l['market_value'])

    # Breakdowns
    def _group(attr):
        agg = {}
        for l in lines:
            k = l.get(attr) or 'Autre'
            agg[k] = agg.get(k, 0) + l['market_value']
        return [{'label': k, 'market_value': round(v, 2),
                 'weight_pct': round(v / total_mv * 100, 2) if total_mv else 0}
                for k, v in sorted(agg.items(), key=lambda x: -x[1])]

    by_envelope_agg = {}
    for l in lines:
        for env in (l['envelopes'] or ['Autre']):
            # Pour une ligne presente sur N enveloppes, on divise equitablement (approximation)
            share = l['market_value'] / max(1, len(l['envelopes'] or ['Autre']))
            by_envelope_agg[env] = by_envelope_agg.get(env, 0) + share
    envelope_breakdown = [
        {'label': k, 'market_value': round(v, 2),
         'weight_pct': round(v / total_mv * 100, 2) if total_mv else 0}
        for k, v in sorted(by_envelope_agg.items(), key=lambda x: -x[1])
    ]

    return jsonify({
        'snapshot_date': date,
        'owner':         owner,
        'lines':         lines,
        'totals': {
            'market_value': round(total_mv, 2),
            'cost_basis':   round(total_cost, 2) if total_cost else None,
            'pnl':          round(total_mv_with_cost - total_cost, 2) if total_cost else None,
            'pnl_pct':      round((total_mv_with_cost - total_cost) / total_cost * 100, 2) if total_cost else None,
            'lines_count':  len(lines),
        },
        'breakdowns': {
            'asset_class': _group('asset_class'),
            'currency':    _group('currency'),
            'envelope':    envelope_breakdown,
        },
    })


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
                val = d[field]
                if val is not None and not validator(val):
                    return jsonify({'error': f'{field} invalide'}), 400
                updates.append(f'{field}=?'); params.append(val)
        if 'is_priceable' in d:
            updates.append('is_priceable=?')
            params.append(int(bool(d['is_priceable'])))
        if 'last_price' in d:
            updates.append('last_price=?')
            params.append(float(d['last_price']) if d['last_price'] is not None else None)
        if 'last_price_date' in d:
            updates.append('last_price_date=?')
            params.append(d['last_price_date'])

        if not updates:
            return jsonify({'error': 'Aucun champ a mettre a jour'}), 400

        updates.append('updated_at=CURRENT_TIMESTAMP')
        params.append(isin)
        conn.execute(
            f'UPDATE securities SET {", ".join(updates)} WHERE isin=?', params
        )
        row = conn.execute('SELECT * FROM securities WHERE isin=?', (isin,)).fetchone()
    return jsonify(dict(row))
