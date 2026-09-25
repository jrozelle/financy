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

Au-dela de la cible, le reste est a investir ; en deca, a reconstituer.
"""
from services.categories import est_financier

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


def bilan(positions, profil=None, entites=()):
    """Montant, lignes, cible et ecart. `ecart` > 0 : a investir ; < 0 : a
    reconstituer ; None sans cible."""
    lignes = [p for p in positions if est_precaution(p, entites)]
    montant = round(sum(p['net_attributed'] for p in lignes), 2)
    c = cible(profil)
    return {
        'montant': montant,
        'cible': c,
        'charges_mensuelles': (profil or {}).get('charges_mensuelles'),
        'mois': (profil or {}).get('mois_precaution'),
        'ecart': None if c is None else round(montant - c, 2),
        'lignes': [{'libelle': ' '.join(x for x in (p.get('envelope'), p.get('establishment')) if x) or p.get('category'),
                    'categorie': p.get('category'), 'montant': round(p['net_attributed'], 2)}
                   for p in sorted(lignes, key=lambda p: -p['net_attributed'])],
    }
