"""Registre des transactions et plus-values realisees."""
from flask import Blueprint, jsonify, request

from models import get_db
from auth import login_required
from services.realized import compute_realized

transactions_bp = Blueprint('transactions', __name__)


def _load(conn, owner=None, envelope=None, isin=None):
    q = 'SELECT * FROM transactions WHERE 1=1'
    p = []
    if owner:
        q += ' AND owner=?'; p.append(owner)
    if envelope:
        q += ' AND envelope=?'; p.append(envelope)
    if isin:
        q += ' AND isin=?'; p.append(isin)
    q += ' ORDER BY date, id'
    return [dict(r) for r in conn.execute(q, p).fetchall()]


@transactions_bp.route('/api/transactions')
@login_required
def list_transactions():
    """Journal des operations, filtrable, avec le nom de la valeur."""
    limit = request.args.get('limit', type=int)
    with get_db() as conn:
        rows = _load(conn, request.args.get('owner'),
                     request.args.get('envelope'), request.args.get('isin'))
        names = {r['isin']: r['name'] for r in conn.execute('SELECT isin, name FROM securities')}
    for r in rows:
        r['name'] = names.get(r['isin'])
    total_buy = sum(r['net_eur'] for r in rows if r['side'] == 'ACHAT')
    total_sell = sum(r['net_eur'] for r in rows if r['side'] == 'VENTE')
    return jsonify({
        'count': len(rows),
        'total_buy': round(total_buy, 2), 'total_sell': round(total_sell, 2),
        'total_fees': round(sum(r['fees'] or 0 for r in rows), 2),
        'transactions': rows[:limit] if limit else rows,
    })


@transactions_bp.route('/api/transactions/realized')
@login_required
def realized():
    """Plus-values realisees par ligne, et detail des cessions."""
    with get_db() as conn:
        rows = _load(conn, request.args.get('owner'), request.args.get('envelope'))
        names = {r['isin']: r['name'] for r in conn.execute('SELECT isin, name FROM securities')}
    state, events = compute_realized(rows)
    lines = []
    for isin, s in state.items():
        if abs(s['realized']) < 0.005 and s['untracked_qty'] < 1e-9:
            continue
        lines.append({'isin': isin, 'name': names.get(isin), 'realized': s['realized'],
                      'sold_qty': s['sold_qty'], 'still_held': s['quantity'],
                      'pru': s['pru'], 'untracked_qty': s['untracked_qty'],
                      'untracked_proceeds': s['untracked_proceeds']})
    lines.sort(key=lambda l: -l['realized'])
    untracked = [l for l in lines if l['untracked_qty'] > 1e-9]
    return jsonify({
        'total_realized': round(sum(l['realized'] for l in lines), 2),
        'lines': lines, 'events': events,
        'untracked_lines': len(untracked),
    })
