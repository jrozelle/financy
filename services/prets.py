"""Prets : capital restant du a une date, et projection.

Le capital restant du a une date est celui APRES la derniere echeance tombee
a cette date ; avant la premiere echeance, c'est le montant emprunte.
"""
from __future__ import annotations

from datetime import date as _date


def crd_a(conn, pret_id, date):
    r = conn.execute('SELECT crd FROM pret_echeances WHERE pret_id=? AND date<=? '
                     'ORDER BY date DESC, rang DESC LIMIT 1', (pret_id, date)).fetchone()
    if r:
        return r['crd']
    m = conn.execute('SELECT montant FROM prets WHERE id=?', (pret_id,)).fetchone()
    return (m['montant'] or 0.0) if m else 0.0


def dettes_par_entite(conn, date):
    """{entite: capital restant du a `date`} pour les prets rattaches."""
    out = {}
    for p in conn.execute('SELECT id, entity FROM prets WHERE entity IS NOT NULL'):
        out[p['entity']] = out.get(p['entity'], 0.0) + crd_a(conn, p['id'], date)
    return {k: round(v, 2) for k, v in out.items()}


def parts_titulaire(conn, owner, date=None):
    """{pret_id: part de dette de `owner`}, d'apres ses positions sur l'entite
    qui porte chaque pret, au dernier arrete a `date`. La part est `debt_pct` :
    detenir la moitie d'une indivision ne dit pas qu'on porte la moitie de son
    credit (66 / 34 sur une residence, par exemple). Un pret qu'il ne porte pas
    n'y figure pas."""
    date = date or _date.today().isoformat()
    d = conn.execute('SELECT MAX(date) d FROM positions WHERE date <= ?', (date,)).fetchone()['d']
    if not d:
        return {}
    parts = {}
    for r in conn.execute('SELECT entity, SUM(COALESCE(debt_pct, ownership_pct, 1)) part FROM positions '
                          'WHERE date=? AND owner=? AND entity IS NOT NULL GROUP BY entity', (d, owner)):
        parts[r['entity']] = min(1.0, r['part'] or 0)
    return {p['id']: parts[p['entity']] for p in conn.execute('SELECT id, entity FROM prets')
            if p['entity'] in parts and parts[p['entity']] > 0}


_MONTANTS = ('crd', 'echeance_du_mois', 'interets_restants', 'ira', 'mensualite', 'montant', 'rembourse')


def a_la_part(pret, part):
    """Un pret vu par un titulaire : chaque montant a sa part de dette."""
    out = dict(pret, part=part)
    for k in _MONTANTS:
        if isinstance(out.get(k), (int, float)):
            out[k] = round(out[k] * part, 2)
    if isinstance(out.get('prochaine'), dict):
        out['prochaine'] = {k: (round(v * part, 2) if k in ('assurance', 'capital', 'crd', 'interets', 'montant')
                                and isinstance(v, (int, float)) else v) for k, v in out['prochaine'].items()}
    return out


def taux_effectif(echeances):
    """Taux annuel deduit de l'echeancier : interets d'une echeance amortie
    rapportes au restant du qui la precede. Les tableaux Caisse d'Epargne
    n'impriment pas le taux ; l'echeancier le contient."""
    for a, b in zip(echeances, echeances[1:]):
        if b['capital'] > 0 and b['interets'] > 0 and a['crd'] > 1000:
            return round(b['interets'] / a['crd'] * 12 * 100, 2)
    return None


def ira(crd, taux_annuel, mode='legale'):
    """Indemnites de remboursement anticipe si l'on solde `crd` maintenant.

    Plafond legal d'un credit immobilier (art. L313-47 du Code de la
    consommation) : le plus faible de six mois d'interets sur le capital
    rembourse, au taux du pret, et de 3 % du capital restant du. Un contrat
    peut y renoncer : mode 'aucune'."""
    if mode == 'aucune' or not crd or not taux_annuel:
        return 0.0
    return round(min(crd * taux_annuel / 100 / 2, crd * 0.03), 2)


def resume(conn, date=None):
    """Chaque pret, vu a `date` (defaut : aujourd'hui)."""
    date = date or _date.today().isoformat()
    out = []
    for p in conn.execute('SELECT * FROM prets ORDER BY entity, libelle'):
        p = dict(p)
        ech = conn.execute('SELECT * FROM pret_echeances WHERE pret_id=? ORDER BY rang', (p['id'],)).fetchall()
        a_venir = [e for e in ech if e['date'] > date]
        # En differe, l'echeance du mois (interets seuls, ou rien) n'est pas la
        # mensualite qui suivra : les deux se disent. Le differe court tant que
        # le capital ne baisse pas.
        prochaine = a_venir[0] if a_venir else None
        amortie = next((e for e in a_venir if e['capital'] > 0), None)
        differe = None
        if prochaine and prochaine['capital'] <= 0:
            fin_d = [e for e in a_venir if amortie is None or e['rang'] < amortie['rang']]
            differe = {'type': 'total' if prochaine['capital'] < 0 else 'partiel',
                       'jusqu_au': fin_d[-1]['date'] if fin_d else None}
        out.append({
            **p,
            'crd': round(crd_a(conn, p['id'], date), 2),
            'echeances': len(ech),
            'restantes': len(a_venir),
            'prochaine': dict(prochaine) if prochaine else None,
            # Ce qui sera preleve a la prochaine echeance (0 en differe total)...
            'echeance_du_mois': round(max(prochaine['capital'], 0) + prochaine['interets'] + prochaine['assurance'], 2)
                                if prochaine else None,
            # ... et la mensualite d'amortissement, une fois le differe fini.
            'mensualite': round(amortie['capital'] + amortie['interets'] + amortie['assurance'], 2)
                          if amortie else None,
            'differe': differe,
            # Solder aujourd'hui : ce que cela couterait (IRA), et ce que cela
            # economiserait (les interets et l'assurance a venir).
            'taux_retenu': p['taux'] or taux_effectif(ech),
            'taux_deduit': not p['taux'],
            'ira_contrat': p.get('ira') or 'legale',
            'ira': ira(crd_a(conn, p['id'], date), p['taux'] or taux_effectif(ech), p.get('ira') or 'legale'),
            'interets_restants': round(sum(e['interets'] + e['assurance'] for e in a_venir), 2),
            'rembourse': round((p['montant'] or 0) - crd_a(conn, p['id'], date), 2),
        })
    return {'date': date, 'prets': out}


def projection(conn, depuis=None, parts=None):
    """Capital restant du, pret par pret et au total, au premier de chaque mois
    depuis `depuis` (defaut : aujourd'hui) jusqu'a la derniere echeance."""
    depuis = depuis or _date.today().isoformat()
    prets = [dict(p) for p in conn.execute('SELECT id, libelle, entity, fin FROM prets ORDER BY fin')]
    if parts is not None:
        prets = [p for p in prets if p['id'] in parts]
    if not prets:
        return {'dates': [], 'prets': [], 'total': []}
    fin = max(p['fin'] for p in prets if p['fin'])
    a, m = int(depuis[:4]), int(depuis[5:7])
    dates = []
    while f'{a:04d}-{m:02d}-01' <= fin:
        dates.append(f'{a:04d}-{m:02d}-01')
        m += 1
        if m > 12:
            a, m = a + 1, 1
    dates.append(fin)
    series = []
    for p in prets:
        k = parts[p['id']] if parts is not None else 1.0
        series.append({**p, 'in_fine': est_in_fine(conn, p['id']), 'part': k,
                       'points': [round(crd_a(conn, p['id'], d) * k, 2) for d in dates]})
    total = [round(sum(s['points'][i] for s in series), 2) for i in range(len(dates))]
    # Le restant du des seuls prets amortissables : leur capital se rembourse
    # sur les revenus, et c'est un enrichissement. Un pret in fine se rembourse
    # d'un bloc, sur des actifs deja comptes : sa baisse n'enrichit personne.
    amortissable = [round(sum(s['points'][i] for s in series if not s['in_fine']), 2)
                    for i in range(len(dates))]
    return {'dates': dates, 'prets': series, 'total': total, 'total_amortissable': amortissable}


def est_in_fine(conn, pret_id):
    """Un pret dont tout le capital se rembourse a la derniere echeance."""
    r = conn.execute('SELECT COUNT(*) n, SUM(CASE WHEN capital > 0.005 THEN 1 ELSE 0 END) k, '
                     'MAX(rang) dernier FROM pret_echeances WHERE pret_id=?', (pret_id,)).fetchone()
    if not r['n'] or r['k'] != 1:
        return False
    d = conn.execute('SELECT capital FROM pret_echeances WHERE pret_id=? AND rang=?',
                     (pret_id, r['dernier'])).fetchone()
    return bool(d and d['capital'] > 0.005)


def enregistrer(conn, tableau, entity=None, libelle=None, source=None):
    """Insere un tableau lu (services.parsers.amortissement.Tableau)."""
    e = tableau.echeances
    cur = conn.execute(
        'INSERT INTO prets (libelle, preteur, emprunteur, entity, montant, taux, debut, fin, source) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (libelle or tableau.libelle, tableau.preteur, tableau.emprunteur, entity,
         tableau.montant, tableau.taux, e[0].date, e[-1].date, source))
    pid = cur.lastrowid
    conn.executemany('INSERT INTO pret_echeances (pret_id, rang, date, capital, interets, assurance, crd) '
                     'VALUES (?,?,?,?,?,?,?)',
                     [(pid, x.rang, x.date, x.capital, x.interets, x.assurance, x.crd) for x in e])
    return pid


def calendrier(conn, depuis=None, nb=12, parts=None):
    """Les `nb` prochaines echeances, tous prets confondus, et le cumul par
    annee civile : capital rembourse, interets, assurance, restant du en fin
    d'annee."""
    depuis = depuis or _date.today().isoformat()
    libelles = {r['id']: r['libelle'] for r in conn.execute('SELECT id, libelle FROM prets')
                if parts is None or r['id'] in parts}
    part_de = (lambda i: parts[i]) if parts is not None else (lambda i: 1.0)
    montants = ('capital', 'interets', 'assurance', 'crd', 'montant')
    lignes = [dict(r) for r in conn.execute('SELECT * FROM pret_echeances WHERE date > ? ORDER BY date, pret_id',
                                            (depuis,)) if r['pret_id'] in libelles]
    prochaines = [dict({c: (round(v * part_de(r['pret_id']), 2) if c in montants else v) for c, v in r.items()},
                       pret=libelles[r['pret_id']]) for r in lignes[:nb]]
    annees = {}
    for r in lignes:
        a = annees.setdefault(r['date'][:4], {'annee': r['date'][:4], 'capital': 0.0, 'interets': 0.0,
                                              'assurance': 0.0, 'echeances': 0})
        x = part_de(r['pret_id'])
        a['capital'] += r['capital'] * x; a['interets'] += r['interets'] * x; a['assurance'] += r['assurance'] * x
        a['echeances'] += 1
    ids = list(libelles)
    for a in annees.values():
        fin = f"{a['annee']}-12-31"
        a['crd_fin'] = round(sum(crd_a(conn, i, fin) * part_de(i) for i in ids), 2)
        for k in ('capital', 'interets', 'assurance'):
            a[k] = round(a[k], 2)
    return {'prochaines': prochaines, 'annees': [annees[k] for k in sorted(annees)]}


def echeancier_calcule(montant, taux_annuel, mois, premiere, assurance=0.0, differe=0, type_differe='partiel'):
    """Echeancier a mensualite constante, pour un pret sans tableau.

    `mois` : duree totale, differe compris. `differe` : nombre de premieres
    echeances en differe —
      - 'partiel' (de capital seul) : on paie les interets, le capital ne
        bouge pas ;
      - 'total' : on ne paie rien, les interets s'ajoutent au capital, qui
        augmente (c'est la franchise d'un pret immobilier).
    L'amortissement a mensualite constante porte ensuite sur le capital du a la
    fin du differe, sur les mois restants. `premiere` : date de la premiere
    echeance ; les suivantes tombent le meme jour des mois suivants (au plus
    le 28).
    """
    from services.parsers.amortissement import Tableau, Echeance
    r = (taux_annuel or 0) / 100 / 12
    differe = max(0, min(int(differe or 0), mois - 1))
    a, m, j = int(premiere[:4]), int(premiere[5:7]), min(int(premiere[8:10]), 28)
    crd, e = float(montant), []

    def suivant():
        nonlocal a, m
        m += 1
        if m > 12:
            a, m = a + 1, 1

    for i in range(1, differe + 1):
        interets = round(crd * r, 2)
        if type_differe == 'total':
            # Rien n'est preleve : les interets grossissent le capital du.
            e.append(Echeance(rang=i, date=f'{a:04d}-{m:02d}-{j:02d}', capital=-interets, interets=0.0,
                              assurance=round(assurance or 0, 2), crd=round(crd + interets, 2)))
            crd = round(crd + interets, 2)
        else:
            e.append(Echeance(rang=i, date=f'{a:04d}-{m:02d}-{j:02d}', capital=0.0, interets=interets,
                              assurance=round(assurance or 0, 2), crd=round(crd, 2)))
        suivant()
    reste = mois - differe
    mensu = crd / reste if r == 0 else crd * r / (1 - (1 + r) ** -reste)
    for i in range(differe + 1, mois + 1):
        interets = round(crd * r, 2)
        capital = round(mensu - interets, 2) if i < mois else round(crd, 2)
        crd = round(crd - capital, 2)
        e.append(Echeance(rang=i, date=f'{a:04d}-{m:02d}-{j:02d}', capital=capital, interets=interets,
                          assurance=round(assurance or 0, 2), crd=max(crd, 0.0)))
        suivant()
    return Tableau(preteur=None, libelle='Prêt', emprunteur=None, montant=round(montant, 2),
                   taux=taux_annuel, echeances=e)
