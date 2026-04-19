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
NON_ARBITRABLE = {'Immobilier', 'Objets de valeur', 'Société', 'SCPI'}


# ─── Bucket level ────────────────────────────────────────────────────────────

def _bucket_proposals(gap, threshold_eur=2000):
    """A partir du gap (cf. allocation.compute_gap), genere des allegements
    par couple (categorie surponderee → categorie sous-ponderee).

    Exclut les categories non-arbitrables (immobilier, objets de valeur, etc.).
    """
    arbitrable = [g for g in gap if g['category'] not in NON_ARBITRABLE]

    # Fusionner Cash & Fond Euro en une seule poche "Cash/Fond Euro"
    # (le fonds euro est du quasi-cash securise, meme profil de risque)
    merged = {}
    for g in arbitrable:
        key = 'Cash / Fond Euro' if g['category'] in ('Cash & dépôts', 'Fond Euro', 'Monétaire') else g['category']
        if key not in merged:
            merged[key] = {'category': key, 'delta_eur': 0}
        merged[key]['delta_eur'] += g['delta_eur']
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
            label=f'Allegir {src_cat} de {round(amt):,.0f} € vers {dst_cat}'.replace(',', ' '),
            from_ref=src_cat, to_ref=dst_cat, amount=amt,
            rationale=f'Cible : {src_cat} surponderee de {round(src_amt):,.0f} €, {dst_cat} sous-ponderee de {round(dst_amt):,.0f} €.'.replace(',', ' '),
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

def _fiscal_proposals(profile, positions):
    """Detecte des opportunites fiscales standard."""
    out = []

    # Calculs preparatoires par enveloppe
    by_env = {}
    for p in positions:
        env = (p.get('envelope') or '').strip()
        if not env:
            continue
        by_env.setdefault(env, []).append(p)

    pea_value = sum(p.get('value') or 0 for p in by_env.get('PEA', []))
    if pea_value > 0 and pea_value < PEA_PLAFOND:
        room = PEA_PLAFOND - pea_value
        out.append(_proposal(
            kind='fiscal',
            label=f'Renforcer le PEA : marge restante {round(room):,.0f} € avant le plafond'.replace(',', ' '),
            from_ref='CTO', to_ref='PEA', amount=room,
            rationale=f'Le PEA actuel est a {round(pea_value):,.0f} € sur {PEA_PLAFOND:,.0f} € autorises. Tout achat d\'eligibles supplementaires beneficie de l\'exo apres 5 ans.'.replace(',', ' '),
        ))

    cto_value = sum(p.get('value') or 0 for p in by_env.get('CTO', []))
    if cto_value > 0:
        # Suggestion generique : verifier MV purgeables
        out.append(_proposal(
            kind='fiscal',
            label='Verifier les moins-values latentes du CTO (purge eventuelle)',
            from_ref='CTO',
            rationale='Une moins-value realisee sur CTO est imputable sur les plus-values des 10 prochaines annees. A faire en fin d\'annee si pertinent.',
        ))

    av_positions = by_env.get('Assurance-vie', [])
    if av_positions:
        out.append(_proposal(
            kind='fiscal',
            label='Verifier l\'anciennete des contrats AV (>8 ans = abattement annuel 4 600 € / 9 200 €)',
            from_ref='Assurance-vie',
            rationale='Apres 8 ans, les rachats sont exoneres dans la limite de 4 600 € (celibataire) ou 9 200 € (couple) de gains par an. Source de tresorerie defiscalisee.',
        ))

    if profile.get('employment_type') == 'TNS':
        out.append(_proposal(
            kind='fiscal',
            label='Optimiser l\'arbitrage remuneration / dividendes / PER',
            from_ref='Remuneration',
            rationale='En tant que TNS, les versements PER sont deductibles du revenu pro dans la limite des plafonds. A rapprocher du calcul dividendes vs salaire selon la TMI marginale.',
        ))

    pension_age = profile.get('pension_age')
    horizon = profile.get('horizon_years')
    if pension_age and horizon and horizon <= 10:
        out.append(_proposal(
            kind='fiscal',
            label='Anticiper la sortie en capital ou rente du PER',
            from_ref='PER',
            rationale=f'Approche de la retraite ({horizon} ans). Le PER permet une sortie en capital (TMI), en rente (annuite viagere imposee), ou un mix. Choix structurant a calibrer.',
        ))

    return out


# ─── Security level ──────────────────────────────────────────────────────────

def _security_proposals(positions, gap, threshold_eur=2000):
    """Pour chaque categorie surponderee (delta_eur fortement negatif), liste
    les holdings reelles a alleger. On suggere par ordre de poids decroissant."""
    over_categories = {g['category'] for g in gap if g['delta_eur'] < -threshold_eur}
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
                qty = h.get('quantity') or 0
                price = h.get('last_price') or 0
                mv = (qty * price) if price else (h.get('market_value') or 0)
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
            if pnl is not None:
                pnl_txt = f' (P&L latent {round(pnl):+,.0f} €)'.replace(',', ' ')
            out.append(_proposal(
                kind='security',
                label=f'Alleger {label_isin} ({r["isin"]}) — exposition {round(r["mv"]):,.0f} €'.replace(',', ' '),
                from_ref=r['isin'], to_ref=cat,
                amount=r['mv'],
                rationale=f'Categorie {cat} surponderee. {label_isin} est l\'une des plus grosses lignes ({round(r["mv"]):,.0f} €){pnl_txt}.'.replace(',', ' '),
            ))
    return out


# ─── Orchestration + persistence ─────────────────────────────────────────────

def generate_proposals(profile, positions, allocation):
    """Renvoie une liste de propositions (sans les sauvegarder)."""
    gap = allocation.get('gap') or []
    return [
        *_bucket_proposals(gap),
        *_fiscal_proposals(profile, positions),
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
