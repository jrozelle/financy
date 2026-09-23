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


def resume(conn, date=None):
    """Chaque pret, vu a `date` (defaut : aujourd'hui)."""
    date = date or _date.today().isoformat()
    out = []
    for p in conn.execute('SELECT * FROM prets ORDER BY entity, libelle'):
        p = dict(p)
        ech = conn.execute('SELECT * FROM pret_echeances WHERE pret_id=? ORDER BY rang', (p['id'],)).fetchall()
        a_venir = [e for e in ech if e['date'] > date]
        # La mensualite courante : la prochaine echeance, hors franchise.
        prochaine = next((e for e in a_venir if e['capital'] > 0), a_venir[0] if a_venir else None)
        out.append({
            **p,
            'crd': round(crd_a(conn, p['id'], date), 2),
            'echeances': len(ech),
            'restantes': len(a_venir),
            'prochaine': dict(prochaine) if prochaine else None,
            'mensualite': round(prochaine['capital'] + prochaine['interets'] + prochaine['assurance'], 2)
                          if prochaine else None,
            'interets_restants': round(sum(e['interets'] + e['assurance'] for e in a_venir), 2),
            'rembourse': round((p['montant'] or 0) - crd_a(conn, p['id'], date), 2),
        })
    return {'date': date, 'prets': out}


def projection(conn, depuis=None):
    """Capital restant du, pret par pret et au total, au premier de chaque mois
    depuis `depuis` (defaut : aujourd'hui) jusqu'a la derniere echeance."""
    depuis = depuis or _date.today().isoformat()
    prets = [dict(p) for p in conn.execute('SELECT id, libelle, entity, fin FROM prets ORDER BY fin')]
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
        series.append({**p, 'points': [round(crd_a(conn, p['id'], d), 2) for d in dates]})
    total = [round(sum(s['points'][i] for s in series), 2) for i in range(len(dates))]
    return {'dates': dates, 'prets': series, 'total': total}


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
