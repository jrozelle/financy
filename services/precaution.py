"""Epargne de precaution : ce qui se retire vite et sans perte, garde pour
l'imprevu, face a la cible du profil (charges mensuelles x nombre de mois).

Une seule regle, lue par le conseil (propositions, constats, DCA) et par la
synthese :
- les livrets et comptes d'epargne (especes hors enveloppe de placement),
  PEL/CEL compris ; jamais un compte courant — l'argent qui tourne n'est pas
  une reserve ;
- les fonds euros ;
- dans les deux cas, pas ce qui est bloque : liquidite « Bloqué » (PER) ou
  part mobilisable nulle (contrat nanti) ;
- ni la tresorerie d'une societe (un compte au nom d'une entite).
L'argent tenu au nom d'un titulaire est son epargne, meme destine a un autre.

Ce qui est garde, dans cet ordre : les livrets reglementes (Livret A, LDDS,
LEP) toujours en entier ; puis, jusqu'a la cible, les autres supports du plus
au moins rentable (rendement mesure du compte, onglet Performance). Le
surplus — a investir — est donc pris sur ce qui rapporte le moins. Sans cible,
les seuls livrets reglementes sont gardes. La reserve libre d'autrefois
(`reserve_eur`) n'est plus lue.
"""
from services.categories import est_financier

REGLEMENTES = {'Livret A', 'LDDS', 'LEP'}
ENVELOPPES_DE_PLACEMENT = {'PEA', 'PEA-PME', 'Assurance-vie', 'PER', 'CTO', 'Crypto'}
COMPTE_COURANT = 'Compte courant'


def est_bloque(p):
    return p.get('liquidity') == 'Bloqué' or (p.get('mobilizable_value') or 0) <= 0


def est_precaution(p, entites=()):
    cat, env = p.get('category'), p.get('envelope') or ''
    if not est_financier(cat) or (p.get('net_attributed') or 0) <= 0:
        return False
    if {p.get('label'), p.get('entity')} & set(entites):
        return False                                   # tresorerie de societe
    if cat == 'Cash & dépôts':
        eligible = env not in ENVELOPPES_DE_PLACEMENT and env != COMPTE_COURANT
    else:
        eligible = cat == 'Fond Euro'
    return eligible and not est_bloque(p)


def cible(profil):
    """Charges mensuelles x mois, ou None si l'un des deux manque."""
    if not profil:
        return None
    charges, mois = profil.get('charges_mensuelles'), profil.get('mois_precaution')
    if not charges or not mois:
        return None
    return round(charges * mois, 2)


def repartition(positions, profil=None, entites=(), rendements=None):
    """Ce que la precaution garde et ce qui la depasse, support par support.

    `rendements` : {cle de compte: taux} (routes/performance.rendements_par_compte).
    Un support sans rendement mesure passe apres ceux qui en ont un.
    Renvoie {'garde', 'source', 'gardees': [(p, montant)], 'surplus': [(p, montant)]}."""
    from routes.performance import cle_compte
    lignes = [p for p in positions if est_precaution(p, entites)]
    reglementes = sum(p['net_attributed'] for p in lignes if (p.get('envelope') or '') in REGLEMENTES)
    c = cible(profil)
    base, source = (c, 'cible') if c is not None else (0.0, 'reglementes')
    garde = max(base, reglementes)
    taux = lambda p: (rendements or {}).get(cle_compte(p))
    ordre = sorted(lignes, key=lambda p: ((p.get('envelope') or '') not in REGLEMENTES,
                                          taux(p) is None, -(taux(p) or 0), -p['net_attributed']))
    gardees, surplus, reste = [], [], garde
    for p in ordre:
        k = min(p['net_attributed'], max(0.0, reste))
        reste -= k
        if k > 0:
            gardees.append((p, round(k, 2)))
        if p['net_attributed'] - k > 0.005:
            surplus.append((p, round(p['net_attributed'] - k, 2)))
    return {'garde': round(garde, 2), 'source': source, 'reglementes': round(reglementes, 2),
            'gardees': gardees, 'surplus': surplus}


def _libelle(p):
    tete = p.get('label') or ('Fonds euros' if p.get('category') == 'Fond Euro' else None)
    return ' '.join(x for x in (tete, p.get('envelope'), p.get('establishment')) if x) or p.get('category')


def bilan(positions, profil=None, entites=(), rendements=None):
    """Montant, lignes, cible, garde et ecart. `ecart` (avec une cible) > 0 :
    a investir ; < 0 : a reconstituer. La garde est la cible, portee aux
    livrets reglementes s'ils la depassent (ils restent entiers)."""
    r = repartition(positions, profil, entites, rendements)
    lignes = [p for p in positions if est_precaution(p, entites)]
    montant = round(sum(p['net_attributed'] for p in lignes), 2)
    c = cible(profil)
    return {
        'montant': montant,
        'cible': c,
        'garde': r['garde'],
        'source': r['source'],
        'charges_mensuelles': (profil or {}).get('charges_mensuelles'),
        'mois': (profil or {}).get('mois_precaution'),
        'ecart': None if c is None else round(montant - r['garde'], 2),
        'lignes': [{'libelle': _libelle(p), 'categorie': p.get('category'), 'montant': round(p['net_attributed'], 2)}
                   for p in sorted(lignes, key=lambda p: -p['net_attributed'])],
        'gardees': [{'libelle': _libelle(p), 'montant': k} for p, k in r['gardees']],
        'surplus': [{'libelle': _libelle(p), 'montant': k} for p, k in r['surplus']],
    }
