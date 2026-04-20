"""Routes de gestion des cours de marche (phase 2 + 3)."""
import logging
import threading
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from models import get_db, validate_isin
from services.prices import (get_provider, refresh_securities, refresh_history,
                             freshness_status)
from services.scheduler import status as scheduler_status, is_enabled as scheduler_is_enabled
from auth import login_required, csrf_protect

logger = logging.getLogger('financy')
prices_bp = Blueprint('prices', __name__)

PERIOD_DAYS = {'1d': 2, '7d': 8, '30d': 32, '90d': 92, '1y': 370, '5y': 1830}

# Lock applicatif : empeche deux refresh globaux concurrents (spam bouton UI).
# Non-bloquant — le second appel recoit 409.
_refresh_lock = threading.Lock()


@prices_bp.route('/api/prices/refresh', methods=['POST'])
@login_required
@csrf_protect
def refresh():
    """Rafraichit les cours de toutes les securities priceables.

    Query params :
    - only_stale=1 : ne traite que les cours > 20h.
    """
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({
            'error': 'Un refresh est deja en cours. Reessayez dans quelques secondes.'
        }), 409
    try:
        only_stale = request.args.get('only_stale') in ('1', 'true', 'yes')
        provider = get_provider()
        with get_db() as conn:
            stats = refresh_securities(conn, provider=provider, only_stale=only_stale)
        stats['provider'] = provider.name
        logger.info('Prices refresh: %s', stats)
        return jsonify(stats)
    finally:
        _refresh_lock.release()


@prices_bp.route('/api/prices/history/<isin>', methods=['GET'])
@login_required
def history(isin):
    """Historique des cours pour un ISIN.

    Query params :
    - period : '1d' | '7d' | '30d' (defaut) | '90d' | '1y' | '5y'.
    - refresh=1 : force un fetch provider meme si la DB est fraiche.
    """
    isin = (isin or '').strip().upper()
    if not validate_isin(isin):
        return jsonify({'error': 'ISIN invalide'}), 400
    period = request.args.get('period', '30d')
    if period not in PERIOD_DAYS:
        period = '30d'
    force = request.args.get('refresh') in ('1', 'true', 'yes')

    days_window = PERIOD_DAYS[period]
    cutoff = (datetime.now() - timedelta(days=days_window)).strftime('%Y-%m-%d')

    with get_db() as conn:
        sec = conn.execute(
            'SELECT isin, name, ticker, currency, is_priceable, last_price, last_price_date FROM securities WHERE isin=?',
            (isin,)
        ).fetchone()
        if not sec:
            return jsonify({'error': 'Security introuvable'}), 404

        # Points deja en DB sur la plage demandee
        rows = conn.execute(
            'SELECT date, price FROM price_history WHERE isin=? AND date>=? ORDER BY date',
            (isin, cutoff)
        ).fetchall()

        # Heuristique de refresh : on re-fetch si force=1, si DB vide,
        # si la derniere donnee a plus de 24h, ou si on a peu de points
        # (insuffisant pour un graphe sur la periode demandee).
        need_refresh = force
        expected_min = max(2, days_window // 4)  # tolere les week-ends/feries
        if sec['is_priceable']:
            if not rows or len(rows) < expected_min:
                need_refresh = True
            else:
                last = rows[-1]['date']
                try:
                    last_dt = datetime.strptime(last, '%Y-%m-%d')
                    if datetime.now() - last_dt > timedelta(days=1):
                        need_refresh = True
                except ValueError:
                    need_refresh = True

        if need_refresh:
            try:
                refresh_history(conn, isin, period=period)
                rows = conn.execute(
                    'SELECT date, price FROM price_history WHERE isin=? AND date>=? ORDER BY date',
                    (isin, cutoff)
                ).fetchall()
                # Recharger les metadonnees securities (last_price peut avoir change)
                sec = conn.execute(
                    'SELECT isin, name, ticker, currency, is_priceable, last_price, last_price_date FROM securities WHERE isin=?',
                    (isin,)
                ).fetchone()
            except Exception as e:
                logger.warning('refresh_history failed for %s: %s', isin, e)

        # Dernier snapshot pour filtrer les holdings
        latest = conn.execute(
            'SELECT MAX(date) as d FROM positions'
        ).fetchone()
        latest_date = latest['d'] if latest else None

        # Holdings du dernier snapshot uniquement (pas les anciens)
        date_filter = 'AND p.date=?' if latest_date else ''
        date_params = [isin, latest_date] if latest_date else [isin]

        hs = conn.execute(
            f'''SELECT SUM(h.quantity) as qty, SUM(h.cost_basis) as cost, SUM(h.market_value) as mv
               FROM holdings h JOIN positions p ON p.id = h.position_id
               WHERE h.isin=? {date_filter}''', date_params
        ).fetchone()

        positions_detail = conn.execute(
            f'''SELECT h.quantity, h.cost_basis, h.market_value,
                      p.owner, p.envelope, p.establishment, p.category
               FROM holdings h
               JOIN positions p ON p.id = h.position_id
               WHERE h.isin=? {date_filter}
               ORDER BY h.market_value DESC''',
            date_params
        ).fetchall()

    points = [{'date': r['date'], 'price': r['price']} for r in rows]
    last_price = points[-1]['price'] if points else sec['last_price']
    first_price = points[0]['price'] if points else None
    variation_pct = ((last_price - first_price) / first_price * 100) if (first_price and last_price) else None

    qty = hs['qty'] if hs else None
    cost = hs['cost'] if hs else None
    mv_stored = hs['mv'] if hs else None

    pnl = None
    pnl_pct = None
    current_value = None
    if qty and qty > 0:
        if last_price is not None and sec['is_priceable']:
            current_value = qty * last_price
        elif mv_stored is not None:
            current_value = mv_stored
        if current_value is not None and cost:
            pnl = current_value - cost
            pnl_pct = (pnl / cost * 100) if cost else None

    return jsonify({
        'isin':            isin,
        'name':            sec['name'],
        'ticker':          sec['ticker'],
        'currency':        sec['currency'],
        'is_priceable':    bool(sec['is_priceable']),
        'period':          period,
        'points':          points,
        'last_price':      last_price,
        'last_price_date': sec['last_price_date'],
        'freshness':       freshness_status(sec['last_price_date']),
        'variation_pct':   variation_pct,
        'holding': {
            'quantity':      qty,
            'cost_basis':    cost,
            'current_value': current_value,
            'pnl':           pnl,
            'pnl_pct':       pnl_pct,
            'positions': [{
                'owner':         r['owner'],
                'envelope':      r['envelope'],
                'establishment': r['establishment'],
                'category':      r['category'],
                'quantity':      r['quantity'],
                'market_value':  r['market_value'],
            } for r in positions_detail],
        } if qty else None,
    })


@prices_bp.route('/api/scheduler/status', methods=['GET'])
@login_required
def get_scheduler_status():
    """Expose l'etat du scheduler pour diagnostic cote UI."""
    return jsonify({
        'configured': scheduler_is_enabled(),
        **scheduler_status(),
    })


@prices_bp.route('/api/securities/<isin>/resolve-ticker', methods=['POST'])
@login_required
@csrf_protect
def resolve_ticker(isin):
    """Declenche la resolution manuelle d'un ticker pour une security."""
    isin = (isin or '').strip().upper()
    if not validate_isin(isin):
        return jsonify({'error': 'ISIN invalide'}), 400
    provider = get_provider()
    with get_db() as conn:
        row = conn.execute('SELECT isin, name FROM securities WHERE isin=?', (isin,)).fetchone()
        if not row:
            return jsonify({'error': 'Security introuvable'}), 404
    ticker, quote_type = provider.resolve_ticker(isin, name=row['name'])
    if not ticker:
        return jsonify({'error': 'Ticker introuvable sur le provider',
                        'provider': provider.name}), 404
    from services.prices import _quote_type_to_asset_class
    with get_db() as conn:
        ac = _quote_type_to_asset_class(quote_type)
        if ac:
            conn.execute(
                '''UPDATE securities SET ticker=?, asset_class=CASE WHEN asset_class IN ('autre','') THEN ? ELSE asset_class END,
                   updated_at=CURRENT_TIMESTAMP WHERE isin=?''',
                (ticker, ac, isin)
            )
        else:
            conn.execute(
                'UPDATE securities SET ticker=?, updated_at=CURRENT_TIMESTAMP WHERE isin=?',
                (ticker, isin)
            )
    return jsonify({'isin': isin, 'ticker': ticker, 'quote_type': quote_type, 'provider': provider.name})
