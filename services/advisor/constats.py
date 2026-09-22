"""Constats : ce qu'un conseiller remarquerait en ouvrant le dossier.

Les propositions d'arbitrage partent d'une allocation cible et d'un profil de
risque ; elles disent « allegez 130 000 EUR de liquidites » sans savoir que ces
liquidites servent a nantir un credit. Les constats font l'inverse : ils ne
proposent rien d'autre que de REGARDER, et ne s'appuient que sur des faits
verifiables dans les donnees — un plafond legal, un montant, une enveloppe.

Chaque constat porte son montant et sa raison. Aucun ne cite de taux
d'interet : ils changent plusieurs fois par an, et un constat doit rester vrai
le jour ou on le lit. Les PLAFONDS, eux, sont des constantes legales, datees
ci-dessous.
"""
from __future__ import annotations

from models import compute_position, get_entity_map, get_holdings_map, load_referential

# Plafonds des versements, en vigueur en 2026. Les interets capitalises peuvent
# faire depasser le plafond ; les versements, non.
PLAFONDS = {'Livret A': 22950.0, 'LDDS': 12000.0, 'LEP': 10000.0}
# Au-dela de ce depassement, ce ne sont plus des interets capitalises : plus
# probablement deux livrets saisis sur une seule ligne, ou une erreur.
MARGE_INTERETS = 1.10

ENVELOPPES_DE_PLACEMENT = {'PEA', 'PEA-PME', 'Assurance-vie', 'PER', 'CTO'}
SEUIL_ESPECES_DORMANTES = 500.0        # en deca, c'est de la poussiere
SEUIL_LIVRET_FISCALISE = 10000.0
SEUIL_COMPTES_COURANTS = 15000.0
SEUIL_CONCENTRATION_IMMO = 0.60


def _eur(v):
    """Un montant marque ⟦v⟧, que le front formate — et masque en mode
    discretion. Ecrit ici en toutes lettres, il s'afficherait en clair."""
    return f"⟦{round(v, 2)}⟧"


def constats(conn, date, owner=None):
    rows = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
    hm = get_holdings_map(conn, [r['id'] for r in rows])
    em = get_entity_map(conn, date)
    ref = load_referential(conn)
    ps = [compute_position(dict(r), em, ref, hm) for r in rows]
    if owner:
        ps = [p for p in ps if p['owner'] == owner]

    out = []
    titulaires = sorted({p['owner'] for p in ps})

    # 1. Livrets reglementes : au-dessus du plafond, ou de la place a prendre
    #    alors que de l'argent dort sur un livret fiscalise du meme titulaire.
    for qui in titulaires:
        siens = [p for p in ps if p['owner'] == qui]
        fiscalise = sum(p['value'] for p in siens if _livret_fiscalise(p))
        place = []
        for env, plafond in PLAFONDS.items():
            livrets = [p for p in siens if p.get('envelope') == env]
            if not livrets:
                continue
            total = sum(p['value'] for p in livrets)
            if total > plafond * MARGE_INTERETS:
                out.append({
                    'niveau': 'alerte', 'onglet': 'positions',
                    'titre': f'{env} de {qui} au-dessus du plafond légal',
                    'detail': (f"{_eur(total)} pour un plafond de versements de {_eur(plafond)}. "
                               "Les intérêts capitalisés peuvent le dépasser, pas de cet ordre : "
                               "deux livrets saisis sur une ligne, ou une erreur de saisie ?"),
                    'montant': round(total - plafond, 2),
                })
            elif total < plafond - 100:
                place.append((env, plafond - total))
        if place and fiscalise >= 1000:
            libre = sum(x for _, x in place)
            deplacable = min(libre, fiscalise)
            out.append({
                'niveau': 'action', 'onglet': 'positions',
                'titre': f'{qui} : {_eur(deplacable)} pourraient passer sur des livrets exonérés',
                'detail': (' et '.join(f"{_eur(x)} de place sur le {env}" for env, x in place)
                           + f", pendant que {_eur(fiscalise)} sont sur un livret dont les intérêts "
                             "sont imposés. Même disponibilité, sans impôt ni prélèvements sociaux."),
                'montant': round(deplacable, 2),
            })

    # 2. Livrets fiscalises importants : l'argent y est disponible, mais taxe.
    for p in ps:
        if _livret_fiscalise(p) and p['value'] >= SEUIL_LIVRET_FISCALISE:
            out.append({
                'niveau': 'info', 'onglet': 'positions',
                'titre': f"{_eur(p['value'])} sur {p.get('envelope')} ({p['owner']})",
                'detail': ("Livret bancaire : ses intérêts supportent l'impôt et les prélèvements "
                           "sociaux. C'est le bon endroit pour une réserve de précaution ; au-delà, "
                           "une assurance-vie en fonds euros offre la même sécurité, avec une "
                           "fiscalité plus douce après huit ans."),
                'montant': round(p['value'], 2),
            })

    # 3. Especes non investies a l'interieur d'une enveloppe de placement.
    for p in ps:
        if (p.get('category') == 'Cash & dépôts' and p.get('envelope') in ENVELOPPES_DE_PLACEMENT
                and p['value'] >= SEUIL_ESPECES_DORMANTES):
            out.append({
                'niveau': 'action', 'onglet': 'positions',
                'titre': f"{_eur(p['value'])} d'espèces non investies dans le {p['envelope']} "
                         f"{p.get('establishment') or ''} ({p['owner']})".replace('  ', ' '),
                'detail': ("Ces espèces profitent de l'enveloppe sans rien y rapporter. À investir, "
                           "ou à garder volontairement comme réserve d'achat."),
                'montant': round(p['value'], 2),
            })

    # 4. Comptes courants : au-dela du matelas, l'argent ne rapporte rien.
    # Seulement l'argent personnel : un compte dont le libelle ou la categorie
    # porte le nom d'une entite declaree (« Holding Exemple ») est la tresorerie de
    # cette societe, pas une epargne qui dort.
    entites = {r['name'] for r in conn.execute('SELECT name FROM entities')}
    perso = lambda p: not ({p.get('label'), p.get('category'), p.get('entity')} & entites)
    for qui in titulaires:
        cc = sum(p['value'] for p in ps if p['owner'] == qui and p.get('envelope') == 'Compte courant'
                 and perso(p))
        if cc >= SEUIL_COMPTES_COURANTS:
            out.append({
                'niveau': 'info', 'onglet': 'positions',
                'titre': f'{_eur(cc)} sur les comptes courants de {qui}',
                'detail': ("Un compte courant ne rapporte rien. Si c'est plus que vos dépenses "
                           "d'un ou deux mois, le surplus serait mieux sur un livret."),
                'montant': round(cc, 2),
            })

    # 5. Dette superieure a la valeur : un net negatif, a surveiller.
    vus = set()
    for p in ps:
        cle = p.get('entity') or f"p{p['id']}"
        if cle in vus:
            continue
        vus.add(cle)
        if p.get('entity'):
            parts = [x for x in ps if x.get('entity') == p['entity']]
            brut = sum(x['gross_attributed'] for x in parts)
            dette = sum(x['debt_attributed'] for x in parts)
            nom = p['entity']
        else:
            brut, dette, nom = p['gross_attributed'], p['debt_attributed'], (p.get('label') or p.get('envelope') or p.get('category'))
        if dette > brut + 100:
            out.append({
                'niveau': 'info', 'onglet': 'entites' if p.get('entity') else 'positions',
                'titre': f'{nom} : la dette dépasse la valeur de {_eur(dette - brut)}',
                'detail': ("Un net négatif n'est pas une anomalie en soi — un bien récent, "
                           "financé à crédit — mais il pèse sur le patrimoine net tant que le "
                           "capital restant dû dépasse la valeur retenue."),
                'montant': round(dette - brut, 2),
            })

    # 6. Concentration immobiliere.
    brut_total = sum(p['gross_attributed'] for p in ps)
    immo = sum(p['gross_attributed'] for p in ps if p.get('category') in ('Immobilier', 'SCPI'))
    if brut_total and immo / brut_total >= SEUIL_CONCENTRATION_IMMO:
        out.append({
            'niveau': 'info', 'onglet': 'synthese',
            'titre': f"L'immobilier pèse {immo / brut_total * 100:.0f} % du brut".replace('.', ','),
            'detail': ("C'est la part la moins liquide du patrimoine : elle se vend en mois, pas en "
                       "jours, et d'un bloc. Un point à garder en tête avant tout nouvel achat."),
            'montant': round(immo, 2),
        })

    ordre = {'alerte': 0, 'action': 1, 'info': 2}
    out.sort(key=lambda c: (ordre[c['niveau']], -abs(c.get('montant') or 0)))
    return {'date': date, 'owner': owner, 'constats': out}


def _livret_fiscalise(p):
    env = (p.get('envelope') or '')
    return env.lower().startswith('livret') and env not in PLAFONDS
