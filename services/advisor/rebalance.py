"""
Generation des propositions d'arbitrage (phase 7).

Trois niveaux de propositions, tous deterministes (pas de LLM en phase 7) :

1. bucket  : alleger une categorie surponderee vers une categorie sous-ponderee
            (montants en €, base sur compute_gap).
2. fiscal  : opportunites fiscales standard (plafond PEA, AV >8 ans, etc.).
3. security: pour chaque categorie surponderee, suggere les holdings concretes
            a alleger en priorite (les plus surponderees ou les moins-values).

Le LLM (phase 7+) peut ensuite enrichir le `rationale` de chaque proposition,
avec prompt caching sur le contexte profil/positions.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Dict, Optional

from models import _holding_value_or_none

logger = logging.getLogger('financy.advisor.rebalance')

# Plafond PEA classique (hors PEA-PME)
PEA_PLAFOND = 150_000


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

LIQUIDITES = 'Cash / Fond Euro'


def _eur(v):
    """Un montant marque ⟦v⟧, que le front formate — et masque en mode
    discretion. Ecrit en toutes lettres, il s'affichait en clair. Meme
    convention que les constats."""
    return f'⟦{round(v, 2)}⟧'


def _bucket_proposals(gap, threshold_eur=2000, total_eur=0.0, reserve=None):
    """A partir du gap (cf. allocation.compute_gap), genere des allegements
    par couple (categorie surponderee → categorie sous-ponderee).

    Exclut les categories non-arbitrables (immobilier, objets de valeur, etc.).

    `reserve` : montant que le titulaire garde disponible (profil). Les
    liquidites mobilisables sont `reel - max(cible, reserve)` : sans elle, le
    conseiller proposait d'investir l'argent destine a nantir un credit.
    """
    arbitrable = [g for g in gap if g['category'] not in NON_ARBITRABLE]

    # Fusionner Cash & Fond Euro en une seule poche "Cash/Fond Euro"
    # (le fonds euro est du quasi-cash securise, meme profil de risque)
    merged = {}
    for g in arbitrable:
        key = LIQUIDITES if g['category'] in ('Cash & dépôts', 'Fond Euro', 'Monétaire') else g['category']
        if key not in merged:
            merged[key] = {'category': key, 'delta_eur': 0, 'actual_eur': 0, 'target_eur': 0}
        merged[key]['delta_eur'] += g['delta_eur']
        merged[key]['actual_eur'] += (g.get('actual_pct') or 0) * total_eur
        merged[key]['target_eur'] += (g.get('target_pct') or 0) * total_eur
    liq = merged.get(LIQUIDITES)
    note_reserve = ''
    if liq and liq['delta_eur'] < 0:
        garde = max(liq['target_eur'], reserve or 0)
        liq['delta_eur'] = min(0, -(liq['actual_eur'] - garde))
        note_reserve = (f' Réserve déclarée de {_eur(reserve)} préservée.' if reserve
                        else ' Aucune réserve déclarée dans le profil : tout l’excédent sur la cible est proposé.')
    arbitrable = list(merged.values())

    over  = sorted([g for g in arbitrable if g['delta_eur'] < -threshold_eur],
                   key=lambda g: g['delta_eur'])
    under = sorted([g for g in arbitrable if g['delta_eur'] >  threshold_eur],
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
            rationale=(f'{src_cat} au-dessus de la cible de {_eur(src_amt)}, {dst_cat} en dessous de {_eur(dst_amt)}.'
                       + (note_reserve if src_cat == LIQUIDITES else '')),
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

    cto_value = sum(p.get('value') or 0 for p in by_env.get('CTO', []))
    if cto_value > 0:
        # Suggestion generique : verifier MV purgeables
        out.append(_proposal(
            kind='fiscal',
            label='Vérifier les moins-values latentes du CTO',
            from_ref='CTO',
            rationale='Une moins-value réalisée sur un CTO s’impute sur les plus-values des dix années suivantes. À examiner en fin d’année.',
        ))

    av_positions = by_env.get('Assurance-vie', [])
    if av_positions:
        out.append(_proposal(
            kind='fiscal',
            label='Vérifier l’ancienneté des assurances-vie (abattement après 8 ans)',
            from_ref='Assurance-vie',
            rationale='Après huit ans, les gains retirés sont exonérés d’impôt sur le revenu jusqu’à 4 600 € par an (9 200 € pour un couple), hors prélèvements sociaux.',
        ))

    if profile.get('employment_type') == 'TNS':
        out.append(_proposal(
            kind='fiscal',
            label='Arbitrer rémunération, dividendes et versements PER',
            from_ref='Remuneration',
            rationale='Travailleur non salarié : les versements sur un PER se déduisent du revenu professionnel dans la limite du plafond. À rapprocher de l’arbitrage dividendes / rémunération selon la tranche marginale.',
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


# ─── Security level ──────────────────────────────────────────────────────────

def _security_proposals(positions, gap, threshold_eur=2000):
    """Pour chaque categorie surponderee (delta_eur fortement negatif), liste
    les holdings reelles a alleger. On suggere par ordre de poids decroissant."""
    # Les liquidites se traitent en poche (_bucket_proposals), reserve deduite :
    # proposer ici d'alleger un fonds euros ignorait la reserve, et sa
    # « plus-value +0 € » ne mesurait rien.
    over_categories = {g['category'] for g in gap if g['delta_eur'] < -threshold_eur
                       and g['category'] not in ('Cash & dépôts', 'Fond Euro', 'Monétaire')}
    if not over_categories:
        return []

    out = []
    for cat in over_categories:
        # On regarde les holdings agreges des positions de cette categorie
        cat_positions = [p for p in positions if p.get('category') == cat]
        # Aggregator par ISIN sur l'ensemble des holdings (priceables)
        isin_totals = {}
        for p in cat_positions:
            for h in (p.get('holdings_detail') or []):
                isin = h.get('isin')
                if not isin:
                    continue
                # Meme valorisation que les positions : cours converti en
                # euros, rien a defaut de taux. `quantite x cours` comptait en
                # euros un cours en dollars.
                mv = _holding_value_or_none(h)
                if mv is None:
                    continue
                cost = h.get('cost_basis') or 0
                rec = isin_totals.setdefault(isin, {'isin': isin, 'name': h.get('name'),
                                                    'mv': 0, 'cost': 0})
                rec['mv'] += mv
                rec['cost'] += cost
        if not isin_totals:
            continue
        ranked = sorted(isin_totals.values(), key=lambda r: -r['mv'])[:3]
        for r in ranked:
            label_isin = r['name'] or r['isin']
            pnl = r['mv'] - r['cost'] if r['cost'] else None
            pnl_txt = ''
            if pnl is not None and abs(pnl) >= 1:
                pnl_txt = f' (plus-value latente {"+" if pnl >= 0 else "−"}{_eur(abs(pnl))})'
            out.append(_proposal(
                kind='security',
                label=f'Alléger {label_isin} ({r["isin"]}) — {_eur(r["mv"])} détenus',
                from_ref=r['isin'], to_ref=cat,
                amount=r['mv'],
                rationale=f'{cat} au-dessus de la cible. {label_isin} est l’une des plus grosses lignes ({_eur(r["mv"])}){pnl_txt}.',
            ))
    return out


# ─── Orchestration + persistence ─────────────────────────────────────────────

def generate_proposals(profile, positions, allocation, versements_pea=None):
    """Renvoie une liste de propositions (sans les sauvegarder)."""
    gap = allocation.get('gap') or []
    return [
        *_bucket_proposals(gap, total_eur=allocation.get('total_eur') or 0,
                           reserve=(profile or {}).get('reserve_eur')),
        *_fiscal_proposals(profile, positions, versements_pea),
        *_security_proposals(positions, gap),
    ]


def replace_proposals(conn, owner, snapshot_date, proposals):
    """Wipe + insert les propositions d'un owner pour un snapshot_date donne.

    Conserve les anciennes propositions deja appliquees ou ecartees pour
    historique : on ne touche qu'aux 'pending'.
    """
    conn.execute(
        "DELETE FROM rebalance_proposals WHERE owner=? AND snapshot_date=? AND status='pending'",
        (owner, snapshot_date)
    )
    inserted = []
    for p in proposals:
        cur = conn.execute(
            '''INSERT INTO rebalance_proposals
               (owner, snapshot_date, kind, label, from_ref, to_ref, amount, rationale, status)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (owner, snapshot_date, p['kind'], p['label'], p['from_ref'],
             p['to_ref'], p['amount'], p['rationale'], p['status'])
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
    return [dict(r) for r in rows]


def update_status(conn, proposal_id, status):
    if status not in ('pending', 'applied', 'dismissed'):
        raise ValueError(f'status invalide : {status}')
    cur = conn.execute(
        'UPDATE rebalance_proposals SET status=? WHERE id=?',
        (status, proposal_id)
    )
    return cur.rowcount > 0
