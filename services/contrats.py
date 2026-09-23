"""Anciennete des contrats : la date d'effet, source de verite fiscale.

Un contrat se designe comme ses positions (titulaire, enveloppe,
etablissement). Sa date d'effet dit quand l'assurance-vie atteint 8 ans — le
seuil de l'abattement annuel sur les gains retires — et quand un PEA atteint
5 ans. Sans elle, l'application ne peut que supposer.
"""
from __future__ import annotations

from datetime import date as _date

SEUILS_ANS = {'Assurance-vie': 8, 'PEA': 5, 'PEA-PME': 5}


def _anniversaire(d, ans):
    j = _date.fromisoformat(d)
    try:
        return j.replace(year=j.year + ans).isoformat()
    except ValueError:                          # 29 fevrier
        return j.replace(year=j.year + ans, day=28).isoformat()


def contrats(conn, date, envelopes=tuple(SEUILS_ANS)):
    """Les contrats detenus a l'arrete `date` pour ces enveloppes, avec leur
    date d'effet si elle est connue, et la date de maturite fiscale."""
    q = ('SELECT DISTINCT owner, envelope, COALESCE(establishment, \'\') AS establishment '
         'FROM positions WHERE date=? AND envelope IN (%s)' % ','.join('?' * len(envelopes)))
    detenus = [dict(r) for r in conn.execute(q, (date, *envelopes))]
    connus = {(r['owner'], r['envelope'], r['establishment']): dict(r)
              for r in conn.execute('SELECT * FROM contrats')}
    out = []
    for d in sorted(detenus, key=lambda x: (x['envelope'], x['owner'], x['establishment'])):
        c = connus.get((d['owner'], d['envelope'], d['establishment']), {})
        effet = c.get('date_effet')
        seuil = SEUILS_ANS.get(d['envelope'])
        maturite = _anniversaire(effet, seuil) if effet and seuil else None
        out.append({**d, 'date_effet': effet, 'numero': c.get('numero'), 'source': c.get('source'),
                    'seuil_ans': seuil, 'maturite': maturite,
                    'mature': (maturite <= date) if maturite else None})
    return out


def enregistrer(conn, lignes):
    for l in lignes:
        conn.execute(
            'INSERT INTO contrats (owner, envelope, establishment, date_effet, numero, source) '
            'VALUES (?,?,?,?,?,?) ON CONFLICT(owner, envelope, establishment) DO UPDATE SET '
            'date_effet=excluded.date_effet, numero=excluded.numero, source=excluded.source',
            (l['owner'], l['envelope'], l.get('establishment') or '', l.get('date_effet') or None,
             l.get('numero') or None, l.get('source') or None))
