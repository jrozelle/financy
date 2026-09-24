"""Poches du patrimoine : la seule definition du « patrimoine financier ».

La synthese range chaque categorie dans une poche ; le conseil calcule sur la
poche financiere. Deux listes tenues a part avaient diverge : « Autre »,
patrimoine autre pour la synthese, entrait dans le financier du conseil, et
les propositions d'arbitrage pouvaient y puiser. Miroir JavaScript :
static/modules/categories.js (un test verifie qu'ils concordent).
"""

FINANCIER = 'Patrimoine financier'

MACRO_ORDER = [FINANCIER, 'Patrimoine immobilier', 'Patrimoine autre']
MACRO_BUCKETS = {
    FINANCIER: {
        'Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
        'Fond Euro', 'Produits Structurés', 'Crypto',
    },
    'Patrimoine immobilier': {'Immobilier', 'SCPI'},
    # 'Société' est l'ancien nom de 'Parts sociales' : les deux sont listes,
    # une base non migree restant classee comme avant.
    'Patrimoine autre': {'Objets de valeur', 'Société', 'Parts sociales', 'Autre'},
}


def macro_bucket(category):
    """Poche d'une categorie ; une categorie inconnue tombe dans « autre »."""
    for bucket, cats in MACRO_BUCKETS.items():
        if category in cats:
            return bucket
    return 'Patrimoine autre'


def est_financier(category):
    return macro_bucket(category) == FINANCIER
