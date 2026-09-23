"""
Fonctions de duplication de snapshots.

UN SEUL helper `duplicate_position` pour copier une position + ses holdings.
Utilise par :
- auto_snapshot route (routes/tools.py)
- snapshot_update route (routes/positions.py)
"""
import logging
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential, snapshot_holdings_to_date, validate_number)

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
    correspondance = _dupliquer_avec_correspondance(conn, source_date, target_date)
    if not correspondance:
        return {'positions_copied': 0, 'holdings_copied': 0}
    ids = list(correspondance.values())
    holdings = conn.execute(
        f'SELECT COUNT(*) AS c FROM holdings WHERE position_id IN ({",".join("?" * len(ids))})', ids
    ).fetchone()['c']
    return {'positions_copied': len(ids), 'holdings_copied': holdings}


# ── Mise a jour d'un arrete ──────────────────────────────────────────────────
#
# Mettre a jour ses soldes demandait de dupliquer l'arrete, puis d'ouvrir une
# modale par compte. Ces deux fonctions portent le parcours en une fois : l'une
# dit ce qui se met a jour et comment, l'autre applique tout dans une seule
# transaction — un echec ne laisse pas un arrete a moitie recopie.

def _mode(pos, holdings_count):
    """Comment une position est valorisee, dans l'ordre de `compute_position`."""
    if pos.get('entity'):
        return 'entite'
    if holdings_count:
        return 'titres'
    return 'saisie'


def preparer_mise_a_jour(conn, source_date, target_date):
    """Ce que l'ecran « Mettre a jour » affiche.

    Seules les positions en mode `saisie` s'editent ici : une position liee a
    une entite tient sa valeur de l'entite (editable dans la meme liste), une
    position a lignes de titres est valorisee par les cours.
    """
    rows = conn.execute('SELECT * FROM positions WHERE date=? ORDER BY owner, establishment, envelope',
                        (source_date,)).fetchall()
    holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
    ref = load_referential(conn)
    entity_map = get_entity_map(conn, source_date)

    positions = []
    for r in rows:
        p = compute_position(dict(r), entity_map, ref, holdings_map)
        n = len(holdings_map.get(r['id']) or [])
        positions.append({
            'id': r['id'], 'owner': r['owner'], 'label': r['label'],
            'establishment': r['establishment'], 'envelope': r['envelope'],
            'category': r['category'], 'entity': r['entity'],
            'value': round(p['value'] or 0, 2), 'debt': round(r['debt'] or 0, 2),
            'mode': _mode(dict(r), n), 'holdings_count': n,
        })

    utilisees = {p['entity'] for p in positions if p['entity']}
    entites = [{'name': nom, 'gross_assets': round(v['gross_assets'], 2), 'debt': round(v['debt'], 2)}
               for nom, v in sorted(entity_map.items()) if nom in utilisees]
    # La dette d'une entite dont les prets ont un echeancier : celle du
    # tableau d'amortissement a la date de l'arrete, proposee a la saisie.
    try:
        from services.prets import dettes_par_entite
        echeancier = dettes_par_entite(conn, target_date)
    except Exception:
        echeancier = {}           # table absente (base non migree)
    for e in entites:
        if e['name'] in echeancier:
            e['dette_echeancier'] = echeancier[e['name']]
    # La tresorerie d'une entite dont les releves sont importes : la valeur
    # proposee remplace celle que l'arrete precedent comprenait, sans la
    # recompter.
    try:
        from services.tresorerie_entite import tresorerie_a
        for e in entites:
            t = tresorerie_a(conn, e['name'], target_date)
            if not t:
                continue
            avant = conn.execute('SELECT tresorerie FROM entity_snapshots WHERE entity_name=? AND date<=? '
                                 'ORDER BY date DESC LIMIT 1', (e['name'], source_date)).fetchone()
            incluse = (avant['tresorerie'] or 0.0) if avant else 0.0
            e['tresorerie'] = {**t, 'incluse_avant': round(incluse, 2)}
            e['valeur_proposee'] = round(e['gross_assets'] - incluse + t['montant'], 2)
    except Exception:
        pass                      # table absente (base non migree)

    existe = conn.execute('SELECT 1 FROM positions WHERE date=? LIMIT 1', (target_date,)).fetchone()
    return {
        'source_date': source_date, 'target_date': target_date,
        # Mettre a jour l'arrete lui-meme, ou en creer un nouveau a partir de lui.
        'en_place': source_date == target_date,
        'cible_existe': bool(existe) and source_date != target_date,
        'positions': positions, 'entites': entites,
    }


def appliquer_mise_a_jour(conn, source_date, target_date, soldes, entites):
    """Cree (ou modifie) l'arrete `target_date` et y applique les soldes.

    Args:
        soldes:  {id_position_source: {'value': x, 'debt': y}}
        entites: {nom: {'gross_assets': x, 'debt': y}}

    L'appelant ouvre la transaction. Une position qui n'est pas en mode
    `saisie` est refusee et rendue dans `refusees` : ecrire sa valeur n'aurait
    aucun effet, et le taire laisserait croire qu'elle a change.
    """
    if source_date != target_date:
        if conn.execute('SELECT 1 FROM positions WHERE date=? LIMIT 1', (target_date,)).fetchone():
            raise ValueError(f'Un arrêté existe déjà au {target_date} : ouvrez-le pour le modifier.')
        correspondance = _dupliquer_avec_correspondance(conn, source_date, target_date)
    else:
        correspondance = {r['id']: r['id'] for r in
                          conn.execute('SELECT id FROM positions WHERE date=?', (source_date,))}

    holdings_map = get_holdings_map(conn, list(correspondance.values()))
    maj, refusees = 0, []
    for src_id, vals in (soldes or {}).items():
        pid = correspondance.get(int(src_id))
        if pid is None:
            refusees.append({'id': int(src_id), 'motif': 'position absente de l’arrêté source'})
            continue
        row = dict(conn.execute('SELECT * FROM positions WHERE id=?', (pid,)).fetchone())
        mode = _mode(row, len(holdings_map.get(pid) or []))
        if mode != 'saisie':
            refusees.append({'id': int(src_id), 'motif': f'valorisée par {"l’entité" if mode == "entite" else "les cours"}'})
            continue
        conn.execute('UPDATE positions SET value=?, debt=? WHERE id=?',
                     (vals.get('value', row['value']), vals.get('debt', row['debt']), pid))
        maj += 1

    connues = {r['name'] for r in conn.execute('SELECT name FROM entities')}
    ent_maj = 0
    for nom, vals in (entites or {}).items():
        if nom not in connues:
            refusees.append({'entite': nom, 'motif': 'entité inconnue'})
            continue
        treso = vals.get('tresorerie')
        if treso is not None and not validate_number(treso, allow_negative=True):
            refusees.append({'entite': nom, 'motif': 'trésorerie invalide'})
            continue
        conn.execute('''INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt, tresorerie)
                        VALUES (?,?,?,?,?)''', (nom, target_date, vals['gross_assets'], vals['debt'], treso))
        ent_maj += 1

    return {'target_date': target_date, 'cree': source_date != target_date,
            'positions_maj': maj, 'entites_maj': ent_maj, 'refusees': refusees}


def _dupliquer_avec_correspondance(conn, source_date, target_date):
    """Copie l'arrete `source_date` vers `target_date` ; rend {id source: id cible}.

    La valeur est figee a sa valeur effective (cours des lignes, ou entite).
    La dette, elle, est recopiee BRUTE. On recopiait `debt_attributed`, c'est-
    a-dire la dette deja multipliee par `debt_pct` — que `compute_position`
    multiplie a nouveau a la lecture : une dette detenue a 50 % etait divisee
    par deux a chaque duplication, y compris celle de l'arrete du jour.
    """
    rows = conn.execute('SELECT * FROM positions WHERE date=?', (source_date,)).fetchall()
    holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
    ref = load_referential(conn)
    entity_map = get_entity_map(conn, source_date)
    correspondance = {}
    for r in rows:
        p = compute_position(dict(r), entity_map, ref, holdings_map)
        override = {'value': p['value'], 'debt': r['debt']}
        correspondance[r['id']] = duplicate_position(conn, r, target_date, value_override=override)
    snapshot_holdings_to_date(conn, target_date)
    return correspondance
