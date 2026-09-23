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

# Enveloppes dont un compte « Cash & dépôts » reste du financier (les especes
# d'un PEA) : meme jeu que `ENVELOPPES_DE_PLACEMENT` cote navigateur.
PLACEMENT = {'PEA', 'PEA-PME', 'Assurance-vie', 'PER', 'CTO', 'Crypto'}


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


CHAMPS = ('variation', 'epargne', 'versements', 'capital', 'performance', 'hors_suivi')


def _versements_placements(conn, debut, fin, owner=None):
    """Versements nets vers les placements sur ]debut, fin] : l'argent qui a
    quitte les liquidites (ou qui arrive d'ailleurs) pour etre investi."""
    from routes.performance import _flux_signed
    q = ('SELECT type, amount FROM flux WHERE date > ? AND date <= ? AND envelope IN (%s)'
         % ','.join('?' * len(PLACEMENT)))
    p = [debut, fin, *PLACEMENT]
    if owner:
        q += ' AND owner = ?'
        p.append(owner)
    return round(sum(_flux_signed(dict(r)) for r in conn.execute(q, p)), 2)


def _epargne_et_capital(precedent, courant, owner=None):
    """Sur les comptes presents aux deux arretes : la variation des liquidites
    (le salaire epargne, moins ce qui en est parti) et la baisse des dettes (le
    capital rembourse, qui est de l'epargne aussi). Un compte qui entre ou sort
    du suivi releve de `_hors_suivi`."""
    a, b = precedent.get('comptes') or {}, courant.get('comptes') or {}
    liq = capital = 0.0
    for cle in set(a) & set(b):
        if owner and cle[0] != owner:
            continue
        if a[cle].get('liq') and b[cle].get('liq'):
            liq += b[cle]['net'] - a[cle]['net']
        capital += a[cle].get('dette', 0.0) - b[cle].get('dette', 0.0)
    return round(liq, 2), round(capital, 2)


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
            'variation': 0.0, 'epargne': 0.0, 'versements': 0.0, 'capital': 0.0,
            'performance': 0.0, 'hors_suivi': 0.0,
            'comptes_hors_suivi': [],
        })
        # La periode la plus ancienne du trimestre en donne le debut, la plus
        # recente la fin : les bornes doivent couvrir tout ce qu'on additionne.
        g['debut'] = min(g['debut'], p['debut'])
        g['fin'] = max(g['fin'], p['fin'])
        for champ in CHAMPS:
            g[champ] += p.get(champ, 0.0)
        g['comptes_hors_suivi'] += p.get('comptes_hors_suivi', [])
    for g in groupes.values():
        for champ in CHAMPS:
            g[champ] = round(g[champ], 2)
    return [groupes[c] for c in sorted(groupes)]


def decompose(conn, arretes, owner=None, limite=8):
    """Decompose la variation du net entre arretes consecutifs.

    Args:
        arretes: liste de {date, family_net, by_owner} triee par date croissante
        owner:   titulaire, ou None pour la famille
        limite:  nombre de periodes rendues, les plus recentes

    Quatre parts, dont la somme redonne la variation :
    - epargne : l'argent qui entre — hausse des liquidites plus versements vers
      les placements. Un DCA depuis un livret n'y compte pas : il sort du livret
      et entre au PEA. Le salaire, qui arrive sans flux, y compte ;
    - capital : la baisse des dettes, du salaire transforme en patrimoine ;
    - hors_suivi : les comptes qui entrent dans le suivi ou en sortent ;
    - performance : le reste, rendement des placements et revalorisations.
    """
    net = (lambda h: (h.get('by_owner') or {}).get(owner, 0.0)) if owner \
        else (lambda h: h.get('family_net') or 0.0)

    periodes = []
    for precedent, courant in zip(arretes, arretes[1:]):
        delta = round(net(courant) - net(precedent), 2)
        versements = _versements_placements(conn, precedent['date'], courant['date'], owner)
        epargne, capital = _epargne_et_capital(precedent, courant, owner)
        hors, comptes = _hors_suivi(conn, precedent, courant, owner)
        epargne = round(epargne + versements, 2)
        periodes.append({
            'debut':       precedent['date'],
            'fin':         courant['date'],
            'variation':   delta,
            'epargne':     epargne,
            'versements':  versements,
            'capital':     capital,
            'hors_suivi':  hors,
            'comptes_hors_suivi': comptes,
            'performance': round(delta - epargne - capital - hors, 2),
        })

    periodes = _par_trimestre(periodes)[-limite:]
    return {
        'periodes':          periodes,
        'total_epargne':     round(sum(p['epargne'] for p in periodes), 2),
        'total_capital':     round(sum(p['capital'] for p in periodes), 2),
        'total_performance': round(sum(p['performance'] for p in periodes), 2),
        'total_hors_suivi':  round(sum(p['hors_suivi'] for p in periodes), 2),
        'total_variation':   round(sum(p['variation'] for p in periodes), 2),
    }


def epargne_mensuelle(conn, fin, mois=6):
    """Apports externes nets par mois sur les `mois` mois pleins avant `fin`,
    et leur MEDIANE : un versement exceptionnel (un heritage, un contrat
    transfere) ne doit pas etre extrapole sur dix ans, ce que ferait une
    moyenne."""
    from datetime import date as _d
    a, m = int(fin[:4]), int(fin[5:7])
    bornes = []
    for _ in range(mois + 1):
        bornes.append(_d(a, m, 1).isoformat())
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    bornes.reverse()
    # ]debut, fin] : le premier du mois appartient au mois precedent, a un
    # jour pres ; sans consequence pour une mediane mensuelle.
    parmois = [{'mois': d0[:7], 'apports': _apports(conn, d0, d1)} for d0, d1 in zip(bornes, bornes[1:])]
    v = sorted(x['apports'] for x in parmois)
    n = len(v)
    mediane = (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2) if n else 0.0
    return {'mois': parmois, 'mediane': round(mediane, 2)}


def _liquidites_par_compte(conn, date):
    """Liquidites personnelles a un arrete, par compte (titulaire, enveloppe,
    etablissement, libelle) : hors entites, hors especes d'enveloppe."""
    from models import compute_position, get_entity_map, get_holdings_map, load_referential
    rows = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
    hm = get_holdings_map(conn, [r['id'] for r in rows])
    em, ref = get_entity_map(conn, date), load_referential(conn)
    out = {}
    for r in rows:
        if r['category'] != 'Cash & dépôts' or r['envelope'] in PLACEMENT or r['entity']:
            continue
        p = compute_position(dict(r), em, ref, hm)
        cle = (r['owner'], r['envelope'] or '', r['establishment'] or '', r['label'] or '')
        out[cle] = out.get(cle, 0.0) + (p['net_attributed'] or 0.0)
    return out


def epargne_nouvelle(conn, fin, jours=183):
    """L'argent qui ENTRE dans le patrimoine, par mois : la variation des
    liquidites plus ce qui en est parti vers les placements.

    Les versements seuls ne le disent pas : un DCA qui investit l'excedent
    d'un livret est un versement sans etre de l'epargne — l'argent change de
    poche. Le salaire, lui, arrive sur un compte courant sans aucun flux. Sa
    trace est la hausse des liquidites, versements vers les placements
    rajoutes.

    La variation ne porte que sur les comptes presents aux deux arretes : un
    compte qui entre dans le suivi n'est pas de l'epargne. Le rythme retenu est
    celui de toute la fenetre ; un versement exceptionnel s'y voit dans la
    liste des periodes.
    """
    from datetime import date as _d, timedelta
    from routes.performance import _flux_signed
    debut = (_d.fromisoformat(fin[:10]) - timedelta(days=jours)).isoformat()
    arretes = [r['date'] for r in conn.execute('SELECT DISTINCT date FROM positions ORDER BY date')]
    avant = [a for a in arretes if a <= debut]
    fenetre = ([avant[-1]] if avant else []) + [a for a in arretes if debut < a <= fin]
    periodes = []
    precedent = None
    for a in fenetre:
        courant = _liquidites_par_compte(conn, a)
        if precedent is not None:
            communs = set(precedent[1]) & set(courant)
            dliq = sum(courant[k] - precedent[1][k] for k in communs)
            vers = sum(_flux_signed(dict(r)) for r in conn.execute(
                'SELECT type, amount FROM flux WHERE date > ? AND date <= ? AND envelope IN (%s)'
                % ','.join('?' * len(PLACEMENT)), (precedent[0], a, *PLACEMENT)))
            duree = (_d.fromisoformat(a) - _d.fromisoformat(precedent[0])).days
            if duree > 0:
                periodes.append({'debut': precedent[0], 'fin': a, 'jours': duree,
                                 'epargne': round(dliq + vers, 2), 'versements': round(vers, 2),
                                 'par_mois': round((dliq + vers) / duree * 30.44, 2)})
        precedent = (a, courant)
    # Le rythme sur toute la fenetre : les periodes sont trop courtes et trop
    # irregulieres (un salaire tombe avant ou apres l'arrete) pour qu'une
    # mediane de periodes ait un sens. La liste les montre, pour juger.
    total = sum(p['jours'] for p in periodes)
    mois = total / 30.44 if total else 0
    return {'periodes': periodes,
            'par_mois': round(sum(p['epargne'] for p in periodes) / mois, 2) if mois else 0.0,
            }
