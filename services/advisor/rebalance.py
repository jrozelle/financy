"""
Generation des propositions d'arbitrage (phase 7).

Deux niveaux de propositions, tous deterministes (pas de LLM en phase 7) :

1. bucket  : alleger une categorie surponderee vers une categorie sous-ponderee
            (montants en €, base sur compute_gap).
2. fiscal  : opportunites fiscales chiffrees (plafond PEA, moins-values du CTO).
Le niveau « security » (alleger telle ligne) a disparu : il repetait la
proposition de poche, qui nomme desormais les lignes mobilisables. Les
propositions deja enregistrees de ce genre restent lisibles dans l'historique.

Le LLM (phase 7+) peut ensuite enrichir le `rationale` de chaque proposition,
avec prompt caching sur le contexte profil/positions.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Dict, Optional

from models import _holding_value_or_none
from services.advisor.allocation import CLASSE_DE
from services.montants import centimes, lignes_en_euros

logger = logging.getLogger('financy.advisor.rebalance')

# Plafond PEA classique (hors PEA-PME)
PEA_PLAFOND = 150_000
SEUIL_MOINS_VALUE = 200


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _proposal(kind, label, from_ref=None, to_ref=None, amount=None, rationale=''):
    return {
        'kind':       kind,
        'label':      label,
        'from_ref':   from_ref,
        'to_ref':     to_ref,
        'amount':     round(amount, 2) if amount is not None else None,
        'rationale':  rationale,
        'status':     'pending',
    }


# Categories non-arbitrables : on ne peut pas "vendre" de l'immobilier
# ou des objets de valeur pour acheter des ETF.
#
# 'Société' est l'ancien nom de 'Parts sociales' ; le referentiel a ete renomme
# sans que ce jeu suive, si bien que le conseiller pouvait proposer d'arbitrer
# des parts de sa propre holding. Les deux noms restent listes : une base qui
# porte encore l'ancien continue d'etre protegee.
NON_ARBITRABLE = {'Immobilier', 'Objets de valeur', 'Société', 'Parts sociales', 'SCPI'}


# ─── Bucket level ────────────────────────────────────────────────────────────

LIQUIDITES = 'Cash'


def _eur(v):
    """Un montant marque ⟦v⟧, que le front formate — et masque en mode
    discretion. Ecrit en toutes lettres, il s'affichait en clair. Meme
    convention que les constats."""
    return f'⟦{round(v, 2)}⟧'


def _reglemente(ligne):
    return any(env in ligne['libelle'] for env in ('Livret A', 'LDDS', 'LEP'))


def _lignes(lignes, n=3):
    txt = ', '.join(f"{l['libelle']} ({_eur(l['montant'])})" for l in lignes[:n])
    return txt + (f' et {len(lignes) - n} autre(s)' if len(lignes) > n else '')


def _gardes_precaution(allocation):
    """Ce que chaque classe garde pour la cible de precaution : les
    liquidites d'abord, puis les fonds euros. None sans cible au profil."""
    c = (allocation.get('precaution') or {}).get('cible')
    if c is None:
        return None
    par_classe = allocation.get('precaution_par_classe') or {}
    gardes, reste = {}, c
    for cle in (LIQUIDITES, 'Obligations'):
        g = min(par_classe.get(cle, 0.0), reste)
        if g > 0:
            gardes[cle] = g
            reste -= g
    return {'cible': c, 'par_classe': gardes}


def _bucket_proposals(gap, threshold_eur=2000, total_eur=0.0, reserve=None, reglementes=0.0, precaution=None):
    """A partir du gap par classe (allocation.allocation_financiere), genere
    des allegements (classe surponderee -> classe sous-ponderee).

    Une classe ne cede que sa part LIBRE : un contrat nanti, un PER ou un
    produit structure comptent dans l'exposition mais ne bougent pas.
    L'epargne de precaution garde sa cible (charges x mois du profil) :
    livrets d'abord, fonds euros ensuite (`precaution`, de _gardes_precaution).
    Sans cible renseignee, les liquidites gardent la reserve libre du profil,
    a defaut les livrets reglementes. Sans garde, le conseiller proposait
    d'investir l'argent destine a nantir un credit.
    """
    merged = {}
    for g in gap:
        if g['category'] in NON_ARBITRABLE or g['category'] == 'Autres':
            continue
        key = CLASSE_DE.get(g['category'], g['category'])
        m = merged.setdefault(key, {'category': key, 'delta_eur': 0.0, 'actual_eur': 0.0,
                                    'target_eur': 0.0, 'libre_eur': 0.0,
                                    'lignes_libres': [], 'lignes_bloquees': []})
        actual = g.get('actual_eur', (g.get('actual_pct') or 0) * total_eur)
        m['delta_eur'] += g['delta_eur']
        m['actual_eur'] += actual
        m['target_eur'] += g.get('target_eur', (g.get('target_pct') or 0) * total_eur)
        m['libre_eur'] += g.get('libre_eur', actual)
        m['lignes_libres'] += g.get('lignes_libres') or []
        m['lignes_bloquees'] += g.get('lignes_bloquees') or []

    notes = {}
    for key, m in merged.items():
        if m['delta_eur'] >= 0:
            continue
        excedent = -m['delta_eur']
        libre = m['libre_eur']
        note = ''
        if precaution is not None:
            garde = precaution['par_classe'].get(key, 0.0)
            if garde:
                libre = max(0.0, libre - garde)
                excedent = min(excedent, max(0.0, m['actual_eur'] - max(m['target_eur'], garde)))
                note = (f' Épargne de précaution gardée : {_eur(garde)}'
                        f'{"" if garde >= precaution["cible"] else " (sur une cible de " + _eur(precaution["cible"]) + ")"}.')
        elif key == LIQUIDITES:
            garde = reserve if reserve else reglementes
            libre = max(0.0, libre - garde)
            excedent = min(excedent, max(0.0, m['actual_eur'] - max(m['target_eur'], garde)))
            if reserve:
                note = f' Réserve déclarée de {_eur(reserve)} préservée.'
            elif reglementes:
                note = (f' Aucune réserve déclarée : les livrets réglementés ({_eur(reglementes)}) '
                        'sont gardés comme épargne de précaution.')
            else:
                note = ' Aucune réserve déclarée dans le profil : tout l’excédent sur la cible est proposé.'
        # Les lignes d'ou vient l'argent ; en liquidites, hors livrets gardes.
        sources = [l for l in m['lignes_libres']
                   if not (precaution is None and key == LIQUIDITES and not reserve and _reglemente(l))]
        if sources:
            note = f' Mobilisable : {_lignes(sources)}.' + note
        if m['lignes_bloquees'] and libre < excedent:
            note += f' Bloqué, donc laissé en place : {_lignes(m["lignes_bloquees"])}.'
        m['delta_eur'] = -min(excedent, libre)
        notes[key] = note

    over  = sorted([m for m in merged.values() if m['delta_eur'] < -threshold_eur],
                   key=lambda g: g['delta_eur'])
    under = sorted([m for m in merged.values() if m['delta_eur'] >  threshold_eur],
                   key=lambda g: -g['delta_eur'])

    out = []
    over_left  = [(g['category'], -g['delta_eur']) for g in over]
    under_left = [(g['category'],  g['delta_eur']) for g in under]

    while over_left and under_left:
        src_cat, src_amt = over_left[0]
        dst_cat, dst_amt = under_left[0]
        amt = min(src_amt, dst_amt)
        out.append(_proposal(
            kind='bucket',
            label=f'Alléger {src_cat} de {_eur(amt)} vers {dst_cat}',
            from_ref=src_cat, to_ref=dst_cat, amount=amt,
            rationale=(f'{src_cat} au-dessus de la cible de {_eur(src_amt)} mobilisables, '
                       f'{dst_cat} en dessous de {_eur(dst_amt)}.' + notes.get(src_cat, '')),
        ))
        if amt >= src_amt:
            over_left.pop(0)
        else:
            over_left[0] = (src_cat, src_amt - amt)
        if amt >= dst_amt:
            under_left.pop(0)
        else:
            under_left[0] = (dst_cat, dst_amt - amt)
    return out


# ─── Fiscal level ────────────────────────────────────────────────────────────

def _fiscal_proposals(profile, positions, versements_pea=None):
    """Detecte des opportunites fiscales standard.

    `versements_pea` : somme des versements enregistres sur le PEA. Le plafond
    de 150 000 € porte sur les VERSEMENTS, pas sur la valeur : un PEA qui a
    double laisse la meme marge qu'avant. Faute de versements enregistres, la
    valeur sert d'estimation, et la proposition le dit.
    """
    out = []

    # Calculs preparatoires par enveloppe
    by_env = {}
    for p in positions:
        env = (p.get('envelope') or '').strip()
        if not env:
            continue
        by_env.setdefault(env, []).append(p)

    pea_value = sum(p.get('value') or 0 for p in by_env.get('PEA', []))
    base, source = ((versements_pea, 'versements enregistrés') if versements_pea
                    else (pea_value, 'valeur actuelle, faute de versements enregistrés — estimation'))
    if pea_value > 0 and base < PEA_PLAFOND:
        room = PEA_PLAFOND - base
        out.append(_proposal(
            kind='fiscal',
            label=f'Renforcer le PEA : {_eur(room)} de versements possibles avant le plafond',
            from_ref='CTO', to_ref='PEA', amount=room,
            rationale=(f'Plafond de {_eur(PEA_PLAFOND)} sur les versements ; {_eur(base)} versés ({source}). '
                       'Les gains réalisés dans le PEA sont exonérés d’impôt sur le revenu après cinq ans.'),
        ))

    # Moins-values latentes du CTO, ligne a ligne : realisees, elles
    # s'imputent sur les plus-values des dix annees suivantes. Rien a dire s'il
    # n'y en a pas — un « verifiez » sans chiffre n'est pas une proposition.
    pertes = []
    for p in by_env.get('CTO', []):
        for h in (p.get('holdings_detail') or []):
            mv, cost = _holding_value_or_none(h), h.get('cost_basis')
            if mv is not None and cost and cost - mv >= SEUIL_MOINS_VALUE:
                pertes.append((h.get('name') or h.get('isin'), cost - mv))
    if pertes:
        pertes.sort(key=lambda x: -x[1])
        total = sum(x for _, x in pertes)
        out.append(_proposal(
            kind='fiscal',
            label=f'{_eur(total)} de moins-values latentes sur le CTO',
            from_ref='CTO', amount=total,
            rationale=(', '.join(f'{n} ({_eur(x)})' for n, x in pertes[:3])
                       + '. Réalisée, une moins-value s’impute sur les plus-values de l’année et des '
                         'dix suivantes ; racheter la ligne ensuite garde l’exposition.'),
        ))

    pension_age = profile.get('pension_age')
    horizon = profile.get('horizon_years')
    if pension_age and horizon and horizon <= 10:
        out.append(_proposal(
            kind='fiscal',
            label='Anticiper la sortie du PER, en capital ou en rente',
            from_ref='PER',
            rationale=f'Retraite dans {horizon} ans. Le PER se dénoue en capital (imposé au barème), en rente viagère, ou un mélange des deux : un choix à préparer.',
        ))

    return out


# ─── Orchestration + persistence ─────────────────────────────────────────────

def generate_proposals(profile, positions, allocation, versements_pea=None):
    """Renvoie une liste de propositions (sans les sauvegarder)."""
    gap = allocation.get('gap') or []
    return [
        *_bucket_proposals(gap, total_eur=allocation.get('total_eur') or 0,
                           reserve=(profile or {}).get('reserve_eur'),
                           reglementes=allocation.get('reglementes_eur') or 0,
                           precaution=_gardes_precaution(allocation)),
        *_fiscal_proposals(profile, positions, versements_pea),
    ]


def replace_proposals(conn, owner, snapshot_date, proposals):
    """Wipe + insert les propositions d'un owner pour un snapshot_date donne.

    Conserve les anciennes propositions deja appliquees ou ecartees pour
    historique : on ne touche qu'aux 'pending'.
    """
    # Toutes les propositions en attente, quel que soit leur arrete : celles
    # d'un arrete anterieur sont perimees, et s'empilaient a chaque generation.
    conn.execute("DELETE FROM rebalance_proposals WHERE owner=? AND status='pending'", (owner,))
    inserted = []
    for p in proposals:
        cur = conn.execute(
            '''INSERT INTO rebalance_proposals
               (owner, snapshot_date, kind, label, from_ref, to_ref, amount, rationale, status)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (owner, snapshot_date, p['kind'], p['label'], p['from_ref'],
             p['to_ref'], centimes(p['amount']), p['rationale'], p['status'])
        )
        inserted.append(cur.lastrowid)
    return inserted


def list_proposals(conn, owner, status=None):
    """Liste les propositions (filtre optionnel par status)."""
    if status:
        rows = conn.execute(
            '''SELECT * FROM rebalance_proposals WHERE owner=? AND status=?
               ORDER BY snapshot_date DESC, id''',
            (owner, status)
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT * FROM rebalance_proposals WHERE owner=?
               ORDER BY snapshot_date DESC, status='pending' DESC, id''',
            (owner,)
        ).fetchall()
    return lignes_en_euros('rebalance_proposals', rows)


def update_status(conn, proposal_id, status):
    if status not in ('pending', 'applied', 'dismissed'):
        raise ValueError(f'status invalide : {status}')
    cur = conn.execute(
        'UPDATE rebalance_proposals SET status=? WHERE id=?',
        (status, proposal_id)
    )
    return cur.rowcount > 0
