"""Montants en centimes entiers.

En base, un montant en euros est un entier de centimes, dans une table STRICT :
les sommes SQL sont exactes, et une valeur non arrondie ne peut pas entrer
(SQLite refuse un REAL non entier dans une colonne INTEGER d'une table STRICT).
Le reste de l'application — calculs, API, export — parle en euros : la
conversion se fait ici, et nulle part ailleurs.

Ne sont PAS des montants, et restent en REAL : cours unitaires d'un titre,
quantites, taux, pourcentages, nombre de parts.
"""
from decimal import Decimal, ROUND_HALF_UP

# Colonnes stockees en centimes, table par table. Sert a la migration, a
# l'export et a l'import JSON : une table ajoutee ici doit l'etre aussi dans
# la migration qui la reconstruit.
COLONNES = {
    'entite_operations':      ('montant',),
    'entite_soldes_initiaux': ('solde',),
    'entite_parts':           ('montant_souscrit',),
    'entite_exercices':       ('resultat',),
}


def centimes(euros):
    """Euros -> centimes entiers, arrondi commercial (0,005 -> 0,01).

    Par la chaine decimale du flottant : 2.675 vaut 2.67499999... en binaire,
    et round() donnerait 267 au lieu de 268."""
    if euros is None or euros == '':
        return None
    return int(Decimal(str(euros)).scaleb(2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def euros(cts):
    """Centimes -> euros (flottant a deux decimales exactes a l'affichage)."""
    if cts is None:
        return None
    return cts / 100


def ligne_en_euros(table, ligne):
    """Copie d'une ligne (dict) avec ses colonnes de montant en euros."""
    d = dict(ligne)
    for col in COLONNES.get(table, ()):
        if col in d:
            d[col] = euros(d[col])
    return d


def ligne_en_centimes(table, ligne):
    """Copie d'une ligne (dict) avec ses colonnes de montant en centimes."""
    d = dict(ligne)
    for col in COLONNES.get(table, ()):
        if col in d:
            d[col] = centimes(d[col])
    return d
