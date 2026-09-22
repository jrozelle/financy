"""D'ou vient la hausse : ce que vous avez verse, ce que le marche a produit.

« +60 000 EUR sur un an » ne dit pas l'essentiel. Une hausse peut venir de
l'epargne — qui se pilote — ou de la performance — qui se subit. Les deux
appellent des decisions opposees, et aucun ecran ne les separait.

Decomposition, entre deux arretes consecutifs :

    variation du net = apports externes + performance

d'ou `performance = Δnet − apports`. C'est un residu, pas une mesure : il
absorbe tout ce qui n'est ni une variation de valeur ni un apport declare —
une position ajoutee a la main, un oubli de flux. La TWR de `/api/performance`
reste la mesure rigoureuse ; ici on cherche a repondre « d'ou ca vient », pas
« combien ca rapporte », et cette lecture-la supporte l'approximation.

Ce qui compte comme apport suit la meme regle qu'ailleurs dans l'application
(`routes/performance.py`) : ni les dividendes ni les frais ne sont des flux
EXTERNES. Les premiers sont produits par les actifs deja detenus, les seconds
preleves a l'interieur du contrat ; tous deux appartiennent au rendement.
"""
from __future__ import annotations
import logging

logger = logging.getLogger('financy.contribution')


def _apports(conn, debut, fin, owner=None):
    """Apports externes nets sur ]debut, fin]. La borne basse est exclue :
    un flux tombant le jour d'un arrete est deja dans sa valeur."""
    from routes.performance import _flux_signed

    q = 'SELECT type, amount, owner FROM flux WHERE date > ? AND date <= ?'
    p = [debut, fin]
    if owner:
        q += ' AND owner = ?'
        p.append(owner)
    return round(sum(_flux_signed(dict(r)) for r in conn.execute(q, p)), 2)


def _trimestre(date):
    """'2026-08-31' -> ('2026-T3', 'T3 26')"""
    an, mois = int(date[:4]), int(date[5:7])
    t = (mois - 1) // 3 + 1
    return f'{an}-T{t}', f'T{t} {str(an)[2:]}'


def _par_trimestre(periodes):
    """Regroupe les periodes entre arretes en trimestres calendaires.

    Les arretes sont irreguliers — deux en aout, aucun en septembre — donc les
    barres d'un graphe par arrete ne sont pas comparables entre elles : une
    colonne peut couvrir trois semaines et sa voisine trois mois. Le trimestre
    est une unite de temps homogene, et c'est la maille a laquelle on juge un
    patrimoine.
    """
    groupes = {}
    for p in periodes:
        cle, libelle = _trimestre(p['fin'])
        g = groupes.setdefault(cle, {
            'cle': cle, 'libelle': libelle, 'debut': p['debut'], 'fin': p['fin'],
            'variation': 0.0, 'apports': 0.0, 'performance': 0.0,
        })
        # La periode la plus ancienne du trimestre en donne le debut, la plus
        # recente la fin : les bornes doivent couvrir tout ce qu'on additionne.
        g['debut'] = min(g['debut'], p['debut'])
        g['fin'] = max(g['fin'], p['fin'])
        for champ in ('variation', 'apports', 'performance'):
            g[champ] += p[champ]
    for g in groupes.values():
        for champ in ('variation', 'apports', 'performance'):
            g[champ] = round(g[champ], 2)
    return [groupes[c] for c in sorted(groupes)]


def decompose(conn, arretes, owner=None, limite=8):
    """Decompose la variation du net entre arretes consecutifs.

    Args:
        arretes: liste de {date, family_net, by_owner} triee par date croissante
        owner:   titulaire, ou None pour la famille
        limite:  nombre de periodes rendues, les plus recentes

    Returns {'periodes': [...], 'total_apports': x, 'total_performance': y}
    """
    net = (lambda h: (h.get('by_owner') or {}).get(owner, 0.0)) if owner \
        else (lambda h: h.get('family_net') or 0.0)

    periodes = []
    for precedent, courant in zip(arretes, arretes[1:]):
        delta = round(net(courant) - net(precedent), 2)
        apports = _apports(conn, precedent['date'], courant['date'], owner)
        periodes.append({
            'debut':       precedent['date'],
            'fin':         courant['date'],
            'variation':   delta,
            'apports':     apports,
            'performance': round(delta - apports, 2),
        })

    periodes = _par_trimestre(periodes)[-limite:]
    return {
        'periodes':          periodes,
        'total_apports':     round(sum(p['apports'] for p in periodes), 2),
        'total_performance': round(sum(p['performance'] for p in periodes), 2),
        'total_variation':   round(sum(p['variation'] for p in periodes), 2),
    }
