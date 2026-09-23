"""D'ou vient la hausse : ce que vous avez verse, ce que le marche a produit.

« +60 000 EUR sur un an » ne dit pas l'essentiel. Une hausse peut venir de
l'epargne — qui se pilote — ou de la performance — qui se subit. Les deux
appellent des decisions opposees, et aucun ecran ne les separait.

Decomposition, entre deux arretes consecutifs :

    variation du net = apports externes + comptes entres ou sortis + performance

d'ou `performance = Δnet − apports − hors suivi`. C'est un residu, pas une mesure : il
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


def _apports_par_compte(conn, debut, fin, owner=None):
    """Apports nets sur ]debut, fin], par (titulaire, enveloppe, etablissement).
    Un flux sans etablissement se rattache a l'enveloppe seule (cle '')."""
    from routes.performance import _flux_signed
    q = 'SELECT type, amount, owner, envelope, establishment FROM flux WHERE date > ? AND date <= ?'
    p = [debut, fin]
    if owner:
        q += ' AND owner = ?'
        p.append(owner)
    out = {}
    for r in conn.execute(q, p):
        cle = (r['owner'], r['envelope'] or '', r['establishment'] or '')
        out[cle] = out.get(cle, 0.0) + _flux_signed(dict(r))
    return out


def _hors_suivi(conn, precedent, courant, owner=None):
    """Comptes qui entrent dans le suivi ou en sortent entre deux arretes.

    Un compte saisi pour la premiere fois n'a pas « rapporte » sa valeur : il
    etait ailleurs, ou alimente par un virement dont une seule jambe est
    enregistree. Le 03/03/2026, une assurance-vie apparue avec 100 000 €, sans
    le versement qui l'avait alimentee, passait pour 100 000 € de performance.
    Sa valeur, moins les flux enregistres sur elle, forme une part a part —
    nommee, pour qu'on sache quel flux manque.
    """
    a, b = precedent.get('comptes'), courant.get('comptes')
    if a is None or b is None:
        return 0.0, []
    flux = _apports_par_compte(conn, precedent['date'], courant['date'], owner)
    def apports(cle):
        o, env, etab = cle[0], cle[1], cle[2]
        return flux.get((o, env, etab), 0.0) + (flux.get((o, env, ''), 0.0) if etab else 0.0)
    total, details = 0.0, []
    for cle in set(a) | set(b):
        if owner and cle[0] != owner:
            continue
        if cle not in a:                      # entree : sa valeur, moins ce qu'on y a verse
            x = b[cle]['net'] - apports(cle)
        elif cle not in b:                    # sortie : sa valeur perdue, moins ce qu'on en a retire
            x = -(a[cle]['net'] + apports(cle))
        else:
            continue
        total += x
        libelle = ' · '.join(v for v in (cle[4] or cle[3] or cle[1], cle[2], cle[0]) if v)
        # Le sens vient de l'evenement, pas du signe : une entite apparue avec
        # un net negatif est une entree.
        details.append({'compte': libelle, 'montant': x, 'date': courant['date'],
                        'sens': 'entree' if cle not in a else 'sortie'})
    # Un compte dont l'enveloppe change sort et rentre sous le meme nom : les
    # deux jambes s'annulent et ne disent rien. On les fusionne par libelle.
    fusion = {}
    for d in details:
        f = fusion.get(d['compte'])
        if f is None:
            fusion[d['compte']] = dict(d)
        else:
            f['montant'] += d['montant']
            f['sens'] = 'deplace'
    details = [dict(d, montant=round(d['montant'], 2)) for d in fusion.values() if abs(d['montant']) >= 1]
    details.sort(key=lambda d: -abs(d['montant']))
    return round(total, 2), details


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
            'variation': 0.0, 'apports': 0.0, 'performance': 0.0, 'hors_suivi': 0.0,
            'comptes_hors_suivi': [],
        })
        # La periode la plus ancienne du trimestre en donne le debut, la plus
        # recente la fin : les bornes doivent couvrir tout ce qu'on additionne.
        g['debut'] = min(g['debut'], p['debut'])
        g['fin'] = max(g['fin'], p['fin'])
        for champ in ('variation', 'apports', 'performance', 'hors_suivi'):
            g[champ] += p.get(champ, 0.0)
        g['comptes_hors_suivi'] += p.get('comptes_hors_suivi', [])
    for g in groupes.values():
        for champ in ('variation', 'apports', 'performance', 'hors_suivi'):
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
        hors, comptes = _hors_suivi(conn, precedent, courant, owner)
        periodes.append({
            'debut':       precedent['date'],
            'fin':         courant['date'],
            'variation':   delta,
            'apports':     apports,
            'hors_suivi':  hors,
            'comptes_hors_suivi': comptes,
            'performance': round(delta - apports - hors, 2),
        })

    periodes = _par_trimestre(periodes)[-limite:]
    return {
        'periodes':          periodes,
        'total_apports':     round(sum(p['apports'] for p in periodes), 2),
        'total_performance': round(sum(p['performance'] for p in periodes), 2),
        'total_hors_suivi':  round(sum(p['hors_suivi'] for p in periodes), 2),
        'total_variation':   round(sum(p['variation'] for p in periodes), 2),
    }
