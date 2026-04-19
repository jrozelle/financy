"""
Auto-split des holdings par categorie lors d'un import.

Si les holdings importes ont des asset_classes mixtes (ex: ETF + fonds euro),
les lignes sont reparties dans des positions compagnons par categorie.
"""
import logging
from services.securities import _infer_asset_class

logger = logging.getLogger('financy.holdings_split')

# Mapping asset_class → categorie position
ASSET_CLASS_TO_CATEGORY = {
    'etf':         'Actions',
    'action':      'Actions',
    'opcvm':       'Actions',
    'obligation':  'Obligations',
    'fonds_euros': 'Fond Euro',
    'scpi':        'Immobilier',
    'sci':         'Immobilier',
    'cash':        'Cash & dépôts',
}


def infer_category(name):
    """Infere la categorie position depuis le nom du holding."""
    ac = _infer_asset_class(name)
    return ASSET_CLASS_TO_CATEGORY.get(ac, 'Actions')


def find_or_create_position(conn, base_pos, category):
    """Trouve une position compagnon (meme date/owner/envelope/etablissement)
    avec la bonne categorie, ou en cree une."""
    row = conn.execute(
        '''SELECT id FROM positions
           WHERE date=? AND owner=? AND envelope=? AND category=?
                 AND COALESCE(establishment,'')=?''',
        (base_pos['date'], base_pos['owner'], base_pos['envelope'],
         category, base_pos['establishment'] or '')
    ).fetchone()
    if row:
        return row['id']
    cur = conn.execute(
        '''INSERT INTO positions (date, owner, category, envelope, establishment, value, debt)
           VALUES (?,?,?,?,?,0,0)''',
        (base_pos['date'], base_pos['owner'], category,
         base_pos['envelope'], base_pos['establishment'])
    )
    logger.info('Auto-split: created position %s/%s/%s (id=%d)',
                base_pos['owner'], base_pos['envelope'], category, cur.lastrowid)
    return cur.lastrowid


def split_holdings_by_category(conn, position_id, items):
    """Repartit les holdings par categorie avec auto-split.

    items : liste de dicts {isin, name, quantity, cost_basis, market_value, as_of_date, ...}

    Retourne (touched_position_ids, split_categories_or_None).
    """
    base_pos = conn.execute(
        'SELECT * FROM positions WHERE id=?', (position_id,)
    ).fetchone()
    base_pos = dict(base_pos)

    # Grouper par categorie inferee
    by_category = {}
    for item in items:
        cat = infer_category(item.get('name'))
        by_category.setdefault(cat, []).append(item)

    categories = list(by_category.keys())
    touched = []

    if len(categories) <= 1:
        # Pas de split — tout dans la position d'origine
        _replace_holdings(conn, position_id, items)
        return [position_id], None

    # Auto-split
    for cat, cat_items in by_category.items():
        if cat == base_pos['category']:
            pid = position_id
        else:
            pid = find_or_create_position(conn, base_pos, cat)
        _replace_holdings(conn, pid, cat_items)
        touched.append(pid)

    logger.info('Auto-split: position %d → %d categories (%s)',
                position_id, len(categories), ', '.join(categories))
    return touched, categories


def _replace_holdings(conn, position_id, items):
    """Full replace des holdings d'une position.

    Si cost_basis est absent, cherche un cost_basis existant pour cet ISIN
    en base (import precedent). Sinon, utilise market_value comme PRU initial.
    """
    # Collecter les cost_basis existants avant suppression
    existing = {}
    for row in conn.execute(
        'SELECT isin, cost_basis FROM holdings WHERE position_id=?', (position_id,)
    ).fetchall():
        if row['cost_basis']:
            existing[row['isin']] = row['cost_basis']

    conn.execute('DELETE FROM holdings WHERE position_id=?', (position_id,))
    for item in items:
        cost = item.get('cost_basis')
        if not cost:
            # Reutiliser le cost_basis de cette meme position (import precedent)
            cost = existing.get(item['isin'])
        if not cost and item.get('market_value'):
            # Derniere resort : premiere observation = cout d'entree
            cost = item['market_value']
        conn.execute(
            '''INSERT INTO holdings
               (position_id, isin, quantity, cost_basis, market_value, as_of_date)
               VALUES (?,?,?,?,?,?)''',
            (position_id, item['isin'], item['quantity'],
             cost, item.get('market_value'), item.get('as_of_date'))
        )
