"""
Auto-snapshot : duplique le dernier snapshot vers la date du jour
si aucun snapshot n'existe pour aujourd'hui.

Appele automatiquement avant les modifications de positions/holdings.
"""
import logging
from datetime import datetime
from models import get_db, compute_position, get_entity_map, get_holdings_map, \
    load_referential, snapshot_holdings_to_date

logger = logging.getLogger('financy.snapshot')


def ensure_today_snapshot(conn):
    """Duplique le dernier snapshot vers aujourd'hui si necessaire.

    Retourne (created: bool, target_date: str).
    Ne fait rien si un snapshot existe deja pour aujourd'hui.
    """
    today = datetime.now().strftime('%Y-%m-%d')

    existing = conn.execute(
        'SELECT COUNT(*) as cnt FROM positions WHERE date=?', (today,)
    ).fetchone()
    if existing['cnt'] > 0:
        return False, today

    last = conn.execute(
        'SELECT DISTINCT date FROM positions ORDER BY date DESC LIMIT 1'
    ).fetchone()
    if not last:
        return False, today

    last_date = last['date']
    if last_date == today:
        return False, today

    source_rows = conn.execute('SELECT * FROM positions WHERE date=?', (last_date,)).fetchall()
    holdings_map = get_holdings_map(conn, [r['id'] for r in source_rows])
    ref = load_referential(conn)
    entity_map = get_entity_map(conn, last_date)

    cols = [k for k in source_rows[0].keys() if k not in ('id', 'date')]

    old_to_new = {}
    for r in source_rows:
        p = compute_position(dict(r), entity_map, ref, holdings_map)
        frozen_value = p['value'] if p.get('has_holdings') and not p.get('entity') else r['value']
        vals = {k: r[k] for k in cols}
        vals['value'] = frozen_value
        vals['date'] = today
        placeholders = ', '.join(['?'] * (len(cols) + 1))
        col_names = ', '.join(['date'] + cols)
        cur = conn.execute(
            f'INSERT INTO positions ({col_names}) VALUES ({placeholders})',
            [today] + [vals[k] for k in cols]
        )
        old_to_new[r['id']] = cur.lastrowid

    # Copier les holdings vers les nouvelles positions
    holdings_copied = 0
    for old_id, new_id in old_to_new.items():
        for h in conn.execute('SELECT * FROM holdings WHERE position_id=?', (old_id,)).fetchall():
            conn.execute(
                '''INSERT INTO holdings (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                   VALUES (?,?,?,?,?,?)''',
                (new_id, h['isin'], h['quantity'], h['cost_basis'], h['market_value'], h['as_of_date'])
            )
            holdings_copied += 1

    snap_count = snapshot_holdings_to_date(conn, today)
    logger.info('Auto-snapshot: %d positions + %d holdings copied from %s to %s',
                len(source_rows), holdings_copied, last_date, today)
    return True, today
