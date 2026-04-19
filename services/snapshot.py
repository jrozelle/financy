"""
Fonctions de duplication de snapshots.

UN SEUL helper `duplicate_position` pour copier une position + ses holdings.
Utilise par :
- ensure_today_snapshot (auto-snapshot)
- auto_snapshot route (routes/tools.py)
- snapshot_update route (routes/positions.py)
"""
import logging
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential, snapshot_holdings_to_date)

logger = logging.getLogger('financy.snapshot')

# Colonnes de la table positions a copier (TOUTES sauf id et date).
# /!\ METTRE A JOUR cette liste quand on ajoute une colonne a positions.
_POSITION_COPY_COLS = [
    'owner', 'category', 'envelope', 'establishment',
    'value', 'debt', 'label', 'notes', 'entity',
    'ownership_pct', 'debt_pct',
    'mobilizable_pct_override', 'liquidity_override',
]

_INSERT_SQL = f'''INSERT INTO positions (date, {', '.join(_POSITION_COPY_COLS)})
                  VALUES (?{', ?' * len(_POSITION_COPY_COLS)})'''

_HOLDINGS_INSERT_SQL = '''INSERT INTO holdings
    (position_id, isin, quantity, cost_basis, market_value, as_of_date)
    VALUES (?,?,?,?,?,?)'''


def duplicate_position(conn, source_row, target_date, value_override=None):
    """Copie UNE position vers une nouvelle date, avec ses holdings.

    Args:
        conn: connexion SQLite ouverte
        source_row: dict-like (sqlite3.Row) de la position source
        target_date: date cible (str YYYY-MM-DD)
        value_override: dict {value, debt, ...} pour surcharger les champs
                        (utilise par snapshot_update pour la position modifiee)

    Returns:
        new_position_id (int)
    """
    vals = {col: source_row[col] for col in _POSITION_COPY_COLS
            if col in source_row.keys()}

    # Surcharge si fournie (snapshot_update modifie une position)
    if value_override:
        for k, v in value_override.items():
            if k in _POSITION_COPY_COLS:
                vals[k] = v

    params = [target_date] + [vals.get(col) for col in _POSITION_COPY_COLS]
    cur = conn.execute(_INSERT_SQL, params)
    new_id = cur.lastrowid

    # Copier les holdings
    old_id = source_row['id']
    for h in conn.execute('SELECT * FROM holdings WHERE position_id=?', (old_id,)).fetchall():
        conn.execute(_HOLDINGS_INSERT_SQL,
                     (new_id, h['isin'], h['quantity'], h['cost_basis'],
                      h['market_value'], h['as_of_date']))

    return new_id


def duplicate_snapshot(conn, source_date, target_date):
    """Duplique toutes les positions d'un snapshot vers une nouvelle date.

    Gele les valeurs calculees (holdings, entites) au moment de la copie.

    Returns:
        dict {positions_copied, holdings_copied}
    """
    source_rows = conn.execute(
        'SELECT * FROM positions WHERE date=?', (source_date,)
    ).fetchall()
    if not source_rows:
        return {'positions_copied': 0, 'holdings_copied': 0}

    holdings_map = get_holdings_map(conn, [r['id'] for r in source_rows])
    ref = load_referential(conn)
    entity_map = get_entity_map(conn, source_date)

    positions_copied = 0
    holdings_copied = 0
    for r in source_rows:
        # Calculer la valeur effective (holdings ou entite)
        p = compute_position(dict(r), entity_map, ref, holdings_map)
        override = {'value': p['value'], 'debt': p.get('debt_attributed', r['debt'])}

        new_id = duplicate_position(conn, r, target_date, value_override=override)
        positions_copied += 1
        holdings_copied += conn.execute(
            'SELECT COUNT(*) as c FROM holdings WHERE position_id=?', (new_id,)
        ).fetchone()['c']

    snapshot_holdings_to_date(conn, target_date)
    return {'positions_copied': positions_copied, 'holdings_copied': holdings_copied}


def ensure_today_snapshot(conn):
    """Duplique le dernier snapshot vers aujourd'hui si necessaire.

    Retourne (created: bool, target_date: str).
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
    if not last or last['date'] == today:
        return False, today

    stats = duplicate_snapshot(conn, last['date'], today)
    logger.info('Auto-snapshot: %d positions + %d holdings from %s to %s',
                stats['positions_copied'], stats['holdings_copied'],
                last['date'], today)
    return True, today
