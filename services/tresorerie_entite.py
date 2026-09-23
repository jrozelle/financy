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
import sqlite3

from services.montants import centimes, euros, ligne_en_euros

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
_FRAIS = re.compile(r'qonto|abonnement|frais|cotisation|commission|honoraires|facture|fact-\d', re.I)
# Fournisseurs propres a une entite (son cabinet comptable...) : ils se
# reglent en base, cle `tresorerie_fournisseurs` (noms separes par des
# virgules), et non dans le code — le depot est public.
CLE_FOURNISSEURS = 'tresorerie_fournisseurs'


def classer(libelle, montant, entite='', associes=(), fournisseurs=()):
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
    if montant < 0 and (_FRAIS.search(libelle) or any(f.lower() in libelle.lower() for f in fournisseurs if f)):
        return 'frais'
    return 'autre'


def associes(conn, entite):
    """Les titulaires des positions de l'entite : leur prenom figure dans les
    libelles de leurs virements (« M Martin Paul Ou Mlle ... »)."""
    return {r['owner'] for r in conn.execute(
        'SELECT DISTINCT owner FROM positions WHERE entity=?', (entite,))}


def fournisseurs(conn):
    try:
        r = conn.execute('SELECT value FROM config WHERE key=?', (CLE_FOURNISSEURS,)).fetchone()
    except Exception:
        return ()
    return tuple(x.strip() for x in (r['value'] if r else '').split(',') if x.strip())


def enregistrer(conn, entite, releve, source, noms_associes=()):
    """Enregistre les operations d'un releve verifie. Renvoie (ajoutees, deja_la)."""
    ajoutees = 0
    connus = fournisseurs(conn)
    for o in releve.operations:
        cur = conn.execute(
            'INSERT OR IGNORE INTO entite_operations '
            '(entity, date, libelle, montant, nature, banque, compte, source) VALUES (?,?,?,?,?,?,?,?)',
            (entite, o.date, o.libelle, centimes(o.montant), classer(o.libelle, o.montant, entite, noms_associes, connus),
             releve.banque, releve.compte, source))
        ajoutees += cur.rowcount
    enregistrer_solde_initial(conn, entite, releve, source)
    return ajoutees, len(releve.operations) - ajoutees


def enregistrer_solde_initial(conn, entite, releve, source=None):
    """Retient le solde d'ouverture du plus ancien releve de chaque compte.

    Les operations seules reconstituaient la tresorerie comme si le compte
    avait ete ouvert a zero le jour du premier releve importe. Un releve plus
    ancien, importe apres coup, remplace le solde retenu ; un plus recent n'y
    touche pas : son solde d'ouverture est deja la somme des precedents.
    """
    if releve.solde_initial is None or not releve.debut:
        return
    conn.execute(
        'INSERT INTO entite_soldes_initiaux (entity, banque, compte, date, solde, source) VALUES (?,?,?,?,?,?) '
        'ON CONFLICT(entity, banque, compte) DO UPDATE SET date=excluded.date, solde=excluded.solde, '
        'source=excluded.source WHERE excluded.date < entite_soldes_initiaux.date',
        (entite, releve.banque or '', releve.compte or '', releve.debut, centimes(releve.solde_initial), source))


def soldes_initiaux(conn, entite, date=None):
    """Somme des soldes d'ouverture des comptes de l'entite ouverts a `date`
    (tous si `date` est None)."""
    try:
        sql, params = 'SELECT SUM(solde) s FROM entite_soldes_initiaux WHERE entity=?', [entite]
        if date is not None:
            sql += ' AND date<=?'
            params.append(date)
        r = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return 0.0                # table absente (base non migree)
    return euros(r['s'] or 0)


def tresorerie_a(conn, entite, date):
    """Solde de tous les comptes de l'entite a `date` : solde d'ouverture du
    premier releve de chaque compte, plus les operations depuis. Rend aussi la
    date de la derniere operation connue. None sans releve."""
    r = conn.execute('SELECT COUNT(*) n, SUM(montant) s, MAX(date) d FROM entite_operations '
                     'WHERE entity=? AND date<=?', (entite, date)).fetchone()
    if not r['n']:
        return None
    return {'montant': round(euros(r['s']) + soldes_initiaux(conn, entite, date), 2), 'au': r['d']}


# Commission de souscription d'une SCPI, deduite du prix de souscription pour
# donner le prix de retrait quand le bulletin ne le publie pas.
FRAIS_RETRAIT_DEFAUT = 0.10


def parts(conn, entite):
    """Les parts de l'entite, valorisees au prix de retrait."""
    out = []
    for r in conn.execute('SELECT * FROM entite_parts WHERE entity=? ORDER BY nom', (entite,)):
        r = ligne_en_euros('entite_parts', r)
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


# Impot sur les societes, taux 2026 : reduit jusqu'a 42 500 € de benefice pour
# une PME dont le capital est detenu a 75 % au moins par des personnes physiques.
IS_SEUIL_REDUIT = 42500.0
IS_TAUX_REDUIT = 0.15
IS_TAUX_NORMAL = 0.25


def impot_societes(benefice):
    if benefice <= 0:
        return 0.0
    return round(min(benefice, IS_SEUIL_REDUIT) * IS_TAUX_REDUIT
                 + max(0.0, benefice - IS_SEUIL_REDUIT) * IS_TAUX_NORMAL, 2)


def exercices(conn, entite):
    return [ligne_en_euros('entite_exercices', r) for r in conn.execute(
        'SELECT * FROM entite_exercices WHERE entity=? ORDER BY fin', (entite,))]


def fiscal(conn, entite, ops, mensuel, pret_ids):
    """Estimation de l'IS de l'exercice en cours, deficits anterieurs imputes.

    En tresorerie, la ou le cabinet travaille en droits constates : une
    distribution de decembre versee en janvier change d'exercice. D'ou une
    projection sur l'annee a partir des douze derniers mois, plutot que le
    seul cumul a date. Revenus et frais s'annualisent sur les mois REELLEMENT
    couverts par des operations : la fenetre compte toujours ses douze mois,
    et trois mois de releves passaient pour une annee.
    """
    clos = exercices(conn, entite)
    if not clos:
        return None
    report = 0.0                              # deficits reportables, cumules
    for e in clos:
        report = report - e['resultat'] if e['resultat'] < 0 else max(0.0, report - e['resultat'])
    annee = str(int(clos[-1]['fin'][:4]) + 1)
    interets = 0.0
    if isinstance(pret_ids, int):
        pret_ids = [pret_ids]
    pret_ids = list(pret_ids or [])
    if pret_ids:
        r = conn.execute(f"SELECT SUM(interets) i, SUM(assurance) a FROM pret_echeances "
                         f"WHERE pret_id IN ({','.join('?' * len(pret_ids))}) AND substr(date,1,4)=?",
                         (*pret_ids, annee)).fetchone()
        interets = euros((r['i'] or 0) + (r['a'] or 0))
    fenetre = {m['mois'] for m in mensuel}
    couverts = len({_mois(o['date']) for o in ops} & fenetre) or 1
    revenus = sum(m['revenu'] for m in mensuel) * 12 / couverts
    frais = -sum(m['frais'] for m in mensuel) * 12 / couverts
    resultat = round(revenus - interets - frais, 2)
    base = resultat - report if resultat > 0 else 0.0
    return {
        'exercices': clos, 'annee': annee, 'deficit_reportable': round(report, 2),
        'projection': {'revenus': round(revenus, 2), 'interets': round(interets, 2),
                       'frais': round(frais, 2), 'resultat': resultat},
        'impot': impot_societes(base),
        'deficit_apres': round(report - resultat if resultat < 0 else max(0.0, report - resultat), 2),
    }


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
    ops = [ligne_en_euros('entite_operations', r) for r in conn.execute(
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
    # Tous les prets de l'entite : n'en retenir que le premier taisait
    # l'echeance, le capital et les interets des suivants.
    prets = [ligne_en_euros('prets', p) for p in conn.execute('SELECT * FROM prets WHERE entity=? ORDER BY id', (entite,))]
    credit = None
    if prets:
        capital = interets = assurance = crd_total = 0.0
        ponderation = taux_pondere = 0.0
        for pret in prets:
            ech = [ligne_en_euros('pret_echeances', e) for e in conn.execute(
                "SELECT * FROM pret_echeances WHERE pret_id=? AND substr(date,1,7) BETWEEN ? AND ?",
                (pret['id'], fenetre[0], fenetre[-1]))]
            capital += sum(e['capital'] for e in ech if e['capital'] > 0)
            interets += sum(e['interets'] for e in ech)
            assurance += sum(e['assurance'] for e in ech)
            r = conn.execute('SELECT crd FROM pret_echeances WHERE pret_id=? AND substr(date,1,7)<=? '
                             'ORDER BY date DESC LIMIT 1', (pret['id'], fin)).fetchone()
            crd = euros(r['crd']) if r else (pret['montant'] or 0.0)
            crd_total += crd
            if pret['taux'] is not None:
                # Taux moyen pondere par le restant du (a defaut, le montant).
                poids = crd or pret['montant'] or 0.0
                ponderation += poids
                taux_pondere += poids * pret['taux']
        taux = (round(taux_pondere / ponderation, 4) if ponderation
                else next((p['taux'] for p in prets if p['taux'] is not None), None))
        credit = {'libelle': ', '.join(p['libelle'] for p in prets), 'taux': taux,
                  'prets': len(prets), 'capital': round(capital, 2),
                  'interets': round(interets, 2), 'assurance': round(assurance, 2),
                  'crd': round(crd_total, 2)}

    snap = conn.execute('SELECT gross_assets FROM entity_snapshots WHERE entity_name=? AND date<=? '
                        'ORDER BY date DESC LIMIT 1', (entite, f'{fin}-31')).fetchone()
    valeur = euros(snap['gross_assets']) if snap else None

    revenus = tot['revenu']
    echeances = -tot['echeance']
    frais = -tot['frais']
    apports = tot['apport']
    net = revenus + tot['revenu_exceptionnel'] - echeances - frais
    # Tresorerie reconstituee : tous comptes, solde d'ouverture du premier
    # releve de chacun plus les operations depuis.
    tresorerie = round(sum(o['montant'] for o in ops) + soldes_initiaux(conn, entite), 2)

    fisc = fiscal(conn, entite, ops, mensuel, [p['id'] for p in prets])
    detenues = parts(conn, entite)
    base_rendement = (detenues or {}).get('montant_souscrit') or valeur
    # Frais d'entree deja partis : ce que les parts ont coute, moins ce qu'on en
    # tirerait en les revendant. Le capital rembourse doit d'abord les absorber.
    frais_latents = (round(detenues['montant_souscrit'] - detenues['valeur_retrait'], 2)
                     if detenues and detenues['complet'] and detenues['montant_souscrit'] else None)
    return {
        'entite': entite,
        'parts': detenues,
        'fiscal': fisc,
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
