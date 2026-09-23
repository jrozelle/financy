"""Tresorerie d'une entite, lue sur ses releves bancaires : ce qu'elle recoit,
ce qu'elle rembourse, ce qu'elle coute, et ce que ses associes y remettent.

Pour une SCI qui achete des parts de SCPI a credit, c'est la mesure du levier :
les loyers couvrent-ils l'echeance, combien les associes ajoutent-ils chaque
mois, et combien de capital ce complement rembourse-t-il. Le patrimoine de la
SCI grandit du capital rembourse, pas de ses loyers — qui partent dans les
interets.
"""
from __future__ import annotations

import re
from datetime import date as _date

NATURES = {
    'revenu': 'Revenus',
    'revenu_exceptionnel': 'Revenus exceptionnels',
    'echeance': 'Échéances du crédit',
    'apport': 'Apports des associés',
    'frais': 'Frais',
    'interne': 'Virements internes',
    'autre': 'Autres',
}

# Distributions qui ne se renouvellent pas : remboursement de capital, plus-value
# de cession. Les compter en revenus surestimerait le rendement.
_EXCEPTIONNEL = re.compile(r'distrib\w* capital|plus-value', re.I)
_REVENU = re.compile(r'scpi|dividende|distribution|activimmo|immorente|pierre europe|transitions europe', re.I)
_ECHEANCE = re.compile(r'federal finance|pechean|echeance pret|remboursement pret', re.I)
_FRAIS = re.compile(r'qonto|cabinet|abonnement|frais|cotisation|commission', re.I)


def classer(libelle, montant, entite='', associes=()):
    """Nature d'une operation, d'apres son libelle.

    La tete du libelle (avant « — ») nomme la contrepartie ; le motif qui suit
    peut citer l'entite elle-meme (« SCPI IMMORENTE ... SCI EXEMPLIA ») sans que
    ce soit un virement interne.
    """
    tete = libelle.split(' — ')[0].lower()
    racine = (entite or '').lower()[:6]
    if racine and racine in tete:
        return 'interne'
    if montant > 0 and any(a.lower() in tete for a in associes if a):
        return 'apport'
    if _ECHEANCE.search(libelle):
        return 'echeance'
    if montant > 0 and _EXCEPTIONNEL.search(libelle):
        return 'revenu_exceptionnel'
    if montant > 0 and _REVENU.search(libelle):
        return 'revenu'
    if montant < 0 and _FRAIS.search(libelle):
        return 'frais'
    return 'autre'


def associes(conn, entite):
    """Les titulaires des positions de l'entite : leur prenom figure dans les
    libelles de leurs virements (« M Martin Paul Ou Mlle ... »)."""
    return {r['owner'] for r in conn.execute(
        'SELECT DISTINCT owner FROM positions WHERE entity=?', (entite,))}


def enregistrer(conn, entite, releve, source, noms_associes=()):
    """Enregistre les operations d'un releve verifie. Renvoie (ajoutees, deja_la)."""
    ajoutees = 0
    for o in releve.operations:
        cur = conn.execute(
            'INSERT OR IGNORE INTO entite_operations '
            '(entity, date, libelle, montant, nature, banque, compte, source) VALUES (?,?,?,?,?,?,?,?)',
            (entite, o.date, o.libelle, o.montant, classer(o.libelle, o.montant, entite, noms_associes),
             releve.banque, releve.compte, source))
        ajoutees += cur.rowcount
    return ajoutees, len(releve.operations) - ajoutees


def tresorerie_a(conn, entite, date):
    """Solde de tous les comptes de l'entite a `date`, reconstitue depuis le
    premier releve, et date de la derniere operation connue. None sans releve."""
    r = conn.execute('SELECT COUNT(*) n, SUM(montant) s, MAX(date) d FROM entite_operations '
                     'WHERE entity=? AND date<=?', (entite, date)).fetchone()
    if not r['n']:
        return None
    return {'montant': round(r['s'], 2), 'au': r['d']}


# Commission de souscription d'une SCPI, deduite du prix de souscription pour
# donner le prix de retrait quand le bulletin ne le publie pas.
FRAIS_RETRAIT_DEFAUT = 0.10


def parts(conn, entite):
    """Les parts de l'entite, valorisees au prix de retrait."""
    out = []
    for r in conn.execute('SELECT * FROM entite_parts WHERE entity=? ORDER BY nom', (entite,)):
        r = dict(r)
        retrait = r['prix_retrait']
        r['retrait_estime'] = retrait is None and r['prix_souscription'] is not None
        if retrait is None and r['prix_souscription'] is not None:
            retrait = r['prix_souscription'] * (1 - FRAIS_RETRAIT_DEFAUT)
        r['prix_retrait_retenu'] = round(retrait, 2) if retrait is not None else None
        r['valeur_retrait'] = round(r['parts'] * retrait, 2) if retrait is not None else None
        out.append(r)
    valeur = sum(p['valeur_retrait'] for p in out if p['valeur_retrait'] is not None)
    souscrit = sum(p['montant_souscrit'] or 0 for p in out)
    return {'lignes': out, 'valeur_retrait': round(valeur, 2), 'montant_souscrit': round(souscrit, 2),
            'complet': all(p['valeur_retrait'] is not None for p in out)} if out else None


def _mois(d):
    return d[:7]


def _mois_precedents(fin, n):
    a, m = int(fin[:4]), int(fin[5:7])
    out = []
    for _ in range(n):
        out.append(f'{a:04d}-{m:02d}')
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out[::-1]


def bilan(conn, entite, mois=12):
    """Le levier de l'entite sur ses `mois` derniers mois couverts par les releves."""
    ops = [dict(r) for r in conn.execute(
        'SELECT * FROM entite_operations WHERE entity=? ORDER BY date, id', (entite,))]
    if not ops:
        return {'entite': entite, 'operations': [], 'mensuel': [], 'periode': None}

    fin = _mois(ops[-1]['date'])
    fenetre = _mois_precedents(fin, mois)
    par_mois = {m: {n: 0.0 for n in NATURES} for m in fenetre}
    for o in ops:
        if _mois(o['date']) in par_mois:
            par_mois[_mois(o['date'])][o['nature']] += o['montant']
    mensuel = [{'mois': m, **{k: round(v, 2) for k, v in par_mois[m].items()}} for m in fenetre]
    tot = {n: round(sum(x[n] for x in mensuel), 2) for n in NATURES}

    # Le credit de l'entite, echeance par echeance sur la meme fenetre : le
    # releve ne montre qu'un prelevement, le tableau d'amortissement dit ce
    # qu'il contient de capital.
    pret = conn.execute('SELECT * FROM prets WHERE entity=? ORDER BY id LIMIT 1', (entite,)).fetchone()
    credit = None
    if pret:
        ech = conn.execute(
            "SELECT * FROM pret_echeances WHERE pret_id=? AND substr(date,1,7) BETWEEN ? AND ?",
            (pret['id'], fenetre[0], fenetre[-1])).fetchall()
        capital = sum(e['capital'] for e in ech if e['capital'] > 0)
        interets = sum(e['interets'] for e in ech)
        assurance = sum(e['assurance'] for e in ech)
        crd = conn.execute('SELECT crd FROM pret_echeances WHERE pret_id=? AND substr(date,1,7)<=? '
                           'ORDER BY date DESC LIMIT 1', (pret['id'], fin)).fetchone()
        credit = {'libelle': pret['libelle'], 'taux': pret['taux'], 'capital': round(capital, 2),
                  'interets': round(interets, 2), 'assurance': round(assurance, 2),
                  'crd': round(crd['crd'], 2) if crd else pret['montant']}

    snap = conn.execute('SELECT gross_assets FROM entity_snapshots WHERE entity_name=? AND date<=? '
                        'ORDER BY date DESC LIMIT 1', (entite, f'{fin}-31')).fetchone()
    valeur = snap['gross_assets'] if snap else None

    revenus = tot['revenu']
    echeances = -tot['echeance']
    frais = -tot['frais']
    apports = tot['apport']
    net = revenus + tot['revenu_exceptionnel'] - echeances - frais
    # Tresorerie reconstituee : tous comptes, depuis le premier releve.
    tresorerie = round(sum(o['montant'] for o in ops), 2)

    detenues = parts(conn, entite)
    base_rendement = (detenues or {}).get('montant_souscrit') or valeur
    # Frais d'entree deja partis : ce que les parts ont coute, moins ce qu'on en
    # tirerait en les revendant. Le capital rembourse doit d'abord les absorber.
    frais_latents = (round(detenues['montant_souscrit'] - detenues['valeur_retrait'], 2)
                     if detenues and detenues['complet'] and detenues['montant_souscrit'] else None)
    return {
        'entite': entite,
        'parts': detenues,
        'frais_latents': frais_latents,
        'periode': {'debut': fenetre[0], 'fin': fin, 'mois': mois},
        'premiere_operation': ops[0]['date'],
        'mensuel': mensuel,
        'totaux': tot,
        'natures': NATURES,
        'credit': credit,
        'valeur': valeur,
        'tresorerie': tresorerie,
        'indicateurs': {
            # Part de l'echeance payee par les loyers recurrents.
            'couverture': round(revenus / echeances, 4) if echeances else None,
            # Rendement distribue recurrent, sur le prix paye des parts : c'est
            # la convention du taux de distribution des SCPI. A defaut, sur la
            # valeur retenue de l'entite.
            'rendement': (round(revenus / base_rendement, 4) if base_rendement else None),
            'effort_mensuel': round(-net / mois, 2) if net < 0 else 0.0,
            'apports': round(apports, 2),
            # Pour chaque euro remis par les associes, le capital rembourse.
            'capital_par_euro_apporte': (round(credit['capital'] / apports, 2)
                                         if credit and apports > 0 else None),
            'cash_flow_net': round(net, 2),
        },
        'operations': ops[::-1],
    }
