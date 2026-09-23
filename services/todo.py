"""Signaux systeme a traiter, agreges pour la synthese.

L'interface empilait des bandeaux independants (avertissements d'entites, note
de snapshot, objectif) sans hiérarchie, pendant que d'autres signaux n'etaient
visibles que si l'on ouvrait le bon onglet — un ecart de quantite ne se voyait
que depuis Actifs, un cours perime nulle part. Resultat : trois achats d'aout
ont manque 2 600 EUR a la valorisation sans que rien ne le dise sur la page
d'accueil.

Ce module rassemble les signaux CALCULABLES EN BASE. Les avertissements de
double-comptage d'entites et les alertes de seuil definies par l'utilisateur
restent evalues cote client, contre la synthese qu'il a deja en main : les
rapatrier ici dupliquerait leur logique sans rien simplifier.

Chaque signal porte sa severite, ce qu'il faut faire, et de quoi juger sans
cliquer — un decompte seul obligerait a ouvrir pour savoir si c'est grave.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('financy.todo')

# Un cours de cloture vieux de plus d'une semaine ouvree ne decrit plus le
# marche. En deca on ne dit rien : signaler tous les jours use le signal.
COURS_PERIMES_JOURS = 5


def _signal(cle, severite, titre, detail, action, onglet, montant=None, nombre=None):
    return {
        'cle': cle, 'severite': severite, 'titre': titre, 'detail': detail,
        'action': action, 'onglet': onglet, 'montant': montant, 'nombre': nombre,
    }


def _ecarts_de_quantite(conn, date):
    """Arretes en retard sur le journal des operations."""
    from services.reconcile import reconcile_snapshot

    rapport = reconcile_snapshot(conn, date)
    ecarts, absents = rapport['ecarts'], rapport['absents']
    if not ecarts and not absents:
        return None

    impact = sum(abs(e['cost_delta'] or 0) for e in ecarts)
    n = len(ecarts) + len(absents)
    titre = (f"{n} ligne en retard sur le journal des opérations" if n == 1
             else f"{n} lignes en retard sur le journal des opérations")
    return _signal(
        'reconcile', 'warn', titre,
        "Des avis d'opérés postérieurs à votre dernière saisie ne sont pas répercutés",
        'Examiner', 'actifs', montant=round(impact, 2), nombre=n)


def _cours_perimes(conn, aujourdhui):
    """Titres cotes dont le dernier cours connu a vieilli.

    Deux populations a ne pas confondre : un cours PERIME se regle par un
    rafraichissement, un titre qui n'a JAMAIS eu de cours et pas de ticker ne se
    resoudra pas ainsi (ELTIF, produit structure, support non cote mal classe).
    Les melanger gonfle le decompte et fait douter du signal entier.
    """
    limite = (aujourdhui - timedelta(days=COURS_PERIMES_JOURS)).strftime('%Y-%m-%d')
    # Seuls comptent les titres encore detenus, c'est-a-dire presents au
    # dernier arrete : un titre vendu depuis garde ses lignes dans les
    # arretes anciens, et son cours fige y restait signale pour toujours.
    rows = conn.execute(
        """SELECT s.isin, s.name, s.ticker, s.last_price_date
           FROM securities s
           WHERE s.is_priceable = 1
             AND EXISTS (SELECT 1 FROM holdings h JOIN positions p ON p.id = h.position_id
                         WHERE h.isin = s.isin
                           AND p.date = (SELECT MAX(date) FROM positions))
             AND (s.last_price_date IS NULL OR s.last_price_date < ?)""",
        (limite,)
    ).fetchall()
    if not rows:
        return None

    perimes = [r for r in rows if r['last_price_date']]
    sans_ticker = [r for r in rows if not r['last_price_date'] and not r['ticker']]

    if perimes:
        # Le plus ancien cours REEL donne la mesure du retard ; trier en placant
        # les valeurs nulles en tete la masquerait derriere un « jamais cote ».
        plus_vieux = min(r['last_price_date'] for r in perimes)
        jours = (aujourdhui - datetime.strptime(plus_vieux, '%Y-%m-%d')).days
        n = len(perimes)
        detail = (f"Le plus ancien remonte au "
                  f"{datetime.strptime(plus_vieux, '%Y-%m-%d').strftime('%d/%m/%Y')}"
                  f", soit {jours} jour{'s' if jours > 1 else ''}")
        if sans_ticker:
            detail += (f" · {len(sans_ticker)} titre{'s' if len(sans_ticker) > 1 else ''} "
                       f"sans ticker, qu'un rafraîchissement ne résoudra pas")
        # Un cours de plus de trois semaines ne decrit plus rien : on hausse le ton.
        severite = 'warn' if jours > 21 else 'info'
        return _signal(
            'cours', severite,
            f"{n} titre{'s' if n > 1 else ''} sans cours récent",
            detail, 'Rafraîchir', 'actifs', nombre=n)

    # Aucun cours perime : seuls restent des titres jamais valorises.
    n = len(rows)
    return _signal(
        'cours', 'info',
        f"{n} titre{'s' if n > 1 else ''} sans cours connu",
        "Aucun cours n'a jamais été récupéré — vérifiez le ticker ou décochez « coté »",
        'Ouvrir le référentiel', 'referentiel', nombre=n)


def _flux_provisoires(conn):
    """Mouvements saisis mais pas encore attestes par un document."""
    from routes.movements_import import PROVISIONAL

    rows = conn.execute(
        "SELECT id, date, owner, envelope, amount FROM flux "
        "WHERE notes LIKE ? ORDER BY date DESC", (f'%{PROVISIONAL}%',)
    ).fetchall()
    if not rows:
        return None

    n = len(rows)
    total = sum(abs(r['amount'] or 0) for r in rows)
    # Le plus recent nomme le cas, le decompte dit l'ampleur : on juge sans ouvrir.
    r = rows[0]
    detail = (f"{r['owner']}" + (f" · {r['envelope']}" if r['envelope'] else '')
              + f", et {n - 1} autre{'s' if n > 2 else ''}" if n > 1
              else f"{r['owner']}" + (f" · {r['envelope']}" if r['envelope'] else ''))
    return _signal(
        'provisoires', 'info',
        f"{n} mouvement{'s' if n > 1 else ''} en attente de justificatif",
        detail, 'Voir les flux', 'flux', montant=round(total, 2), nombre=n)


def collect(conn, date, aujourdhui=None):
    """Signaux a traiter pour l'arrete `date`, du plus grave au moins grave.

    Returns {'signaux': [...], 'total': n}
    """
    aujourdhui = aujourdhui or datetime.now()
    signaux = []
    for calcul in (lambda: _ecarts_de_quantite(conn, date),
                   lambda: _cours_perimes(conn, aujourdhui),
                   lambda: _flux_provisoires(conn)):
        try:
            s = calcul()
        except Exception:
            # Un signal qui echoue ne doit pas emporter les autres : la page
            # d'accueil reste utile meme si un controle tombe.
            logger.exception('Signal « a traiter » en echec')
            continue
        if s:
            signaux.append(s)

    ordre = {'warn': 0, 'info': 1}
    signaux.sort(key=lambda s: ordre.get(s['severite'], 9))
    return {'signaux': signaux, 'total': len(signaux)}
