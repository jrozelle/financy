"""Rapprochement des quantites d'un arrete avec le journal des transactions.

`holdings` porte une PHOTO (quantite a une date de valeur), `transactions` un
JOURNAL d'operations. Rien ne relie les deux : une transaction n'appartient a
aucun arrete, volontairement — la table a ete creee sans cle etrangere vers
`positions` pour qu'une ligne soldee ne disparaisse pas avec sa plus-value.

Consequence observee en prod : deux avis d'achat d'aout n'avaient jamais atteint
les snapshots, et 3 011 EUR manquaient a la valorisation. La photo bougeait avec
le cours du jour, donc rien ne signalait la quantite perimee.

Ce module ne corrige rien tout seul. Il repond a « la photo est-elle en retard
sur le journal ? », en laissant l'arbitrage a l'utilisateur.

Regle de comparaison
--------------------
On ne compare PAS la quantite au cumul total des transactions : cet historique
n'est complet que si tous les avis ont ete importes depuis l'origine du compte.
On compare a un DELTA LOCAL — les seules operations post-datant la date de
valeur de la ligne. La question devient « des operations sont-elles arrivees
apres ma derniere saisie ? », qui ne suppose rien sur l'exhaustivite du journal.

Une ligne dont la date de valeur est inconnue n'est pas verifiable : elle est
comptee et signalee, jamais devinee.
"""
from __future__ import annotations
import logging

logger = logging.getLogger('financy.reconcile')

# Les quantites sont fractionnaires (parts d'OPCVM a 5 decimales). Un seuil trop
# serre transformerait le bruit de sommation flottante en faux ecarts.
TOLERANCE_QTY = 1e-4


def _key(owner, envelope, establishment, isin):
    """Cle de rapprochement : (personne, enveloppe, etablissement, ISIN).

    La personne est indispensable : un meme support est detenu par deux
    titulaires chez le meme assureur (contrats Generali de Julien et Perrine,
    contrats enfants chez BoursoBank). Sans elle, les deux se confondent.
    NULL et '' sont equivalents, comme partout ailleurs dans le schema.
    """
    return (owner or '', envelope or '', establishment or '', isin or '')


def _signed(side, quantity):
    return (quantity or 0) if side == 'ACHAT' else -(quantity or 0)


def reconcile_snapshot(conn, snapshot_date):
    """Compare les quantites de l'arrete `snapshot_date` au journal.

    Returns un dict :
      ecarts     : lignes de la photo en retard sur le journal (delta != 0)
      absents    : titres encore detenus d'apres le journal, absents de la photo
      ignores    : decompte motive de ce qui n'a pas ete verifie
      verifiees  : nombre de lignes effectivement comparees
    """
    holdings = conn.execute(
        '''SELECT h.id, h.position_id, h.isin, h.quantity, h.cost_basis,
                  h.market_value, h.as_of_date,
                  p.owner, p.envelope, p.establishment,
                  s.name AS sec_name, s.last_price, s.last_price_date
           FROM holdings h
           JOIN positions p ON p.id = h.position_id
           LEFT JOIN securities s ON s.isin = h.isin
           WHERE p.date = ?
           ORDER BY p.owner, p.envelope, h.isin''',
        (snapshot_date,)
    ).fetchall()

    # Journal borne a l'arrete : une operation posterieure a la date du snapshot
    # ne saurait y figurer.
    txs = conn.execute(
        '''SELECT id, date, owner, envelope, establishment, isin, side,
                  quantity, net_eur
           FROM transactions
           WHERE date <= ?
           ORDER BY date, id''',
        (snapshot_date,)
    ).fetchall()

    tx_by_key = {}
    for t in txs:
        tx_by_key.setdefault(
            _key(t['owner'], t['envelope'], t['establishment'], t['isin']), []
        ).append(t)

    # Une meme cle portee par deux lignes de la photo (deux contrats chez le
    # meme etablissement pour la meme personne) rend le rapprochement ambigu :
    # on ne choisit pas a quelle ligne imputer l'operation.
    counts = {}
    for h in holdings:
        k = _key(h['owner'], h['envelope'], h['establishment'], h['isin'])
        counts[k] = counts.get(k, 0) + 1

    ecarts = []
    ignores = {'soldees': 0, 'sans_date_valeur': 0, 'ambigues': 0,
               'hors_journal': 0}
    verifiees = 0
    cles_vues = set()

    for h in holdings:
        k = _key(h['owner'], h['envelope'], h['establishment'], h['isin'])
        cles_vues.add(k)
        ops = tx_by_key.get(k)
        if not ops:
            ignores['hors_journal'] += 1
            continue
        if counts[k] > 1:
            ignores['ambigues'] += 1
            continue
        if not h['as_of_date']:
            ignores['sans_date_valeur'] += 1
            continue

        posterieures = [t for t in ops if t['date'] > h['as_of_date']]
        verifiees += 1
        if not posterieures:
            continue

        delta_qty = round(sum(_signed(t['side'], t['quantity']) for t in posterieures), 6)
        if abs(delta_qty) < TOLERANCE_QTY:
            continue
        delta_cost = round(sum(
            (t['net_eur'] or 0) if t['side'] == 'ACHAT' else -(t['net_eur'] or 0)
            for t in posterieures), 2)

        ecarts.append({
            'holding_id':     h['id'],
            'position_id':    h['position_id'],
            'isin':           h['isin'],
            'name':           h['sec_name'] or h['isin'],
            'owner':          h['owner'],
            'envelope':       h['envelope'],
            'establishment':  h['establishment'],
            'as_of_date':     h['as_of_date'],
            'quantity':       h['quantity'],
            'expected':       round((h['quantity'] or 0) + delta_qty, 6),
            'delta_quantity': delta_qty,
            'cost_basis':     h['cost_basis'],
            'cost_delta':     delta_cost,
            'operations':     [{
                'id':       t['id'],
                'date':     t['date'],
                'side':     t['side'],
                'quantity': t['quantity'],
                'net_eur':  t['net_eur'],
            } for t in posterieures],
        })

    # Titres du journal absents de la photo : encore detenus, ou soldes ?
    absents = []
    for k, ops in tx_by_key.items():
        if k in cles_vues:
            continue
        reste = round(sum(_signed(t['side'], t['quantity']) for t in ops), 6)
        if abs(reste) < TOLERANCE_QTY:
            ignores['soldees'] += 1
            continue
        owner, envelope, establishment, isin = k
        sec = conn.execute('SELECT name FROM securities WHERE isin=?', (isin,)).fetchone()
        absents.append({
            'isin':          isin,
            'name':          (sec['name'] if sec else None) or isin,
            'owner':         owner,
            'envelope':      envelope or None,
            'establishment': establishment or None,
            'quantity':      0,
            'expected':      reste,
            'operations':    [{
                'id': t['id'], 'date': t['date'], 'side': t['side'],
                'quantity': t['quantity'], 'net_eur': t['net_eur'],
            } for t in ops],
        })

    return {
        'date':      snapshot_date,
        'ecarts':    ecarts,
        'absents':   absents,
        'ignores':   ignores,
        'verifiees': verifiees,
    }


def apply_ecart(conn, snapshot_date, holding_id):
    """Applique a UNE ligne le delta calcule par `reconcile_snapshot`.

    Le delta est TOUJOURS recalcule ici : le client transmet un identifiant de
    ligne, jamais un montant. Un ecart rejoue deux fois ne doublerait donc pas la
    quantite — apres la premiere application, la date de valeur passe au-dela des
    operations concernees et le delta retombe a zero.

    `market_value` est recalculee au prix unitaire courant : la laisser telle
    quelle decrirait l'ancienne quantite, et cette valeur reprendrait la main le
    jour ou le titre cesse d'etre cote.

    Returns le detail applique, ou None si la ligne n'a plus d'ecart.
    """
    rapport = reconcile_snapshot(conn, snapshot_date)
    cible = next((e for e in rapport['ecarts'] if e['holding_id'] == holding_id), None)
    if cible is None:
        return None

    h = conn.execute(
        '''SELECT h.quantity, h.cost_basis, h.market_value, h.position_id,
                  s.last_price, s.last_price_date
           FROM holdings h LEFT JOIN securities s ON s.isin = h.isin
           WHERE h.id = ?''', (holding_id,)
    ).fetchone()

    new_qty = round((h['quantity'] or 0) + cible['delta_quantity'], 6)
    new_cost = round((h['cost_basis'] or 0) + cible['cost_delta'], 2)

    # Prix unitaire : le cours si on en a un, sinon celui qu'implique la photo.
    unit = h['last_price']
    if unit is None and h['quantity']:
        unit = (h['market_value'] or 0) / h['quantity']
    new_mv = round(new_qty * unit, 2) if unit else h['market_value']

    # La date de valeur avance jusqu'a la derniere operation integree : la ligne
    # dit desormais « juste au <date du dernier avis> », ce qui est exact.
    new_as_of = max(op['date'] for op in cible['operations'])

    conn.execute(
        'UPDATE holdings SET quantity=?, cost_basis=?, market_value=?, as_of_date=? '
        'WHERE id=?',
        (new_qty, new_cost, new_mv, new_as_of, holding_id)
    )
    logger.info('Reconcile %s: holding %s %s -> %s parts (%+.6f), cout %+.2f',
                snapshot_date, holding_id, h['quantity'], new_qty,
                cible['delta_quantity'], cible['cost_delta'])

    return {
        'holding_id':  holding_id,
        'position_id': h['position_id'],
        'isin':        cible['isin'],
        'quantity':    {'avant': h['quantity'], 'apres': new_qty},
        'cost_basis':  {'avant': h['cost_basis'], 'apres': new_cost},
        'market_value': {'avant': h['market_value'], 'apres': new_mv},
        'as_of_date':  {'avant': cible['as_of_date'], 'apres': new_as_of},
        'operations':  cible['operations'],
    }
